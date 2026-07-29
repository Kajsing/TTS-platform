from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError
from reader_core import ReaderError
from speech_rules import RuleContext
from tts_core.backends.base import BackendError
from tts_core.models import AudioFormat, ProsodySettings, SynthesisOptions, SynthesisRequest

from .errors import APIError
from .reader_errors import (
    reader_api_error,
    reader_database_unavailable,
    reader_disabled,
    translate_reader_error,
)
from .reader_service import ReaderApplicationService
from .reader_streaming import (
    ReaderSpeechCompiler,
    ReaderSpeechFragment,
    ReaderStreamCursor,
    ReaderStreamWindow,
    ReaderStreamWindowBuilder,
)
from .schemas import ProsodyPayload
from .security import (
    enforce_headers_access,
    extract_bearer_token_from_headers,
    validate_auth_token,
)

READER_WEBSOCKET_START_TIMEOUT_SECONDS = 10.0
READER_WEBSOCKET_START_MAX_CHARS = 65_536
READER_WEBSOCKET_RELEASE_TIMEOUT_SECONDS = 30.0


class ReaderStreamCursorPayload(BaseModel):
    block_id: str | None = None
    block_ordinal: int = Field(ge=0)
    character_offset: int = Field(ge=0)
    content_revision: int | None = Field(default=None, gt=0)


class ReaderStreamWindowPayload(BaseModel):
    max_blocks: int | None = Field(default=None, gt=0)
    max_source_characters: int | None = Field(default=None, gt=0)


class ReaderStreamStartPayload(BaseModel):
    document_id: str
    cursor: ReaderStreamCursorPayload
    voice_profile_id: str | None = None
    voice: str | None = None
    language_hint: str | None = Field(default=None, max_length=64)
    prosody: ProsodyPayload = Field(default_factory=ProsodyPayload)
    rule_set_ids: list[str] = Field(default_factory=list, max_length=100)
    window: ReaderStreamWindowPayload = Field(default_factory=ReaderStreamWindowPayload)


def build_reader_stream_router() -> APIRouter:
    router = APIRouter(prefix="/v1/reader", tags=["reader"])

    @router.websocket("/stream")
    async def reader_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        container = websocket.app.state.container
        try:
            enforce_headers_access(
                headers=websocket.headers,
                client_host=(
                    websocket.client.host if websocket.client is not None else "unknown"
                ),
                auth_state=container.auth,
                origin_policy=container.origin_policy,
                rate_limiter=container.rate_limiter,
                require_auth=False,
            )
            initial = await _receive_start_message(websocket)
            header_token = extract_bearer_token_from_headers(websocket.headers)
            validate_auth_token(container.auth, header_token or initial.get("auth_token"))
            if initial.get("type") != "start":
                raise reader_api_error(
                    "reader_conflict",
                    status_code=400,
                    message="First Reader WebSocket event must be a start event.",
                    param="type",
                )
            payload = ReaderStreamStartPayload.model_validate(initial.get("payload", {}))
            service = _reader_service(websocket)
            stream_id = str(uuid4())
            await _run_reader_stream(
                websocket,
                container=container,
                service=service,
                payload=payload,
                stream_id=stream_id,
            )
        except TimeoutError:
            await _send_error(
                websocket,
                reader_api_error(
                    "reader_conflict",
                    status_code=400,
                    message="First Reader WebSocket event timed out.",
                    param="type",
                ),
                close_code=1008,
            )
        except ValidationError:
            await _send_error(
                websocket,
                reader_api_error(
                    "reader_conflict",
                    status_code=400,
                    message="Reader stream start payload is invalid.",
                ),
                close_code=1003,
            )
        except APIError as error:
            await _send_error(websocket, error, close_code=1008)
        except WebSocketDisconnect:
            return

    return router


async def _run_reader_stream(
    websocket: WebSocket,
    *,
    container: object,
    service: ReaderApplicationService,
    payload: ReaderStreamStartPayload,
    stream_id: str,
) -> None:
    voice_id = payload.voice or container.config.tts.default_voice
    if payload.voice_profile_id is not None:
        raise reader_api_error(
            "reader_voice_unavailable",
            status_code=400,
            message="Reader voice profiles are not available in this service version.",
            param="voice_profile_id",
        )
    if not container.voice_registry.has(voice_id):
        raise reader_api_error(
            "reader_voice_unavailable",
            status_code=400,
            message="The requested Reader voice is unavailable.",
            param="voice",
        )

    max_blocks = payload.window.max_blocks or service.config.max_blocks_per_stream_window
    max_source_characters = (
        payload.window.max_source_characters
        or service.config.max_source_chars_per_stream_window
    )
    if max_blocks > service.config.max_blocks_per_stream_window:
        raise reader_api_error(
            "reader_conflict",
            status_code=400,
            message="Reader stream block window exceeds the configured maximum.",
            param="window.max_blocks",
        )
    if max_source_characters > service.config.max_source_chars_per_stream_window:
        raise reader_api_error(
            "reader_conflict",
            status_code=400,
            message="Reader stream character window exceeds the configured maximum.",
            param="window.max_source_characters",
        )

    try:
        rules = service.ordered_rules(tuple(payload.rule_set_ids))
        rules_version = service.repository.get_rules_version()
    except ReaderError as error:
        raise translate_reader_error(error, missing_entity="rule set") from error
    compiler = ReaderSpeechCompiler(
        container.text_pipeline.normalizer,
        container.text_pipeline.segmenter,
        container.chunk_planner,
        rule_engine=service.rule_engine() if rules else None,
        rules=rules,
        rule_context=RuleContext(
            language=payload.language_hint,
            engine=container.backend.__class__.__name__,
            voice=voice_id,
            document_id=payload.document_id,
        ),
    )
    builder = ReaderStreamWindowBuilder(service, compiler)
    started_at = monotonic()
    outcome = "failure"
    with service.content_lease(payload.document_id, stream_id):
        try:
            window = builder.build(
                payload.document_id,
                block_ordinal=payload.cursor.block_ordinal,
                character_offset_utf16=payload.cursor.character_offset,
                block_id=payload.cursor.block_id,
                content_revision=payload.cursor.content_revision,
                max_blocks=max_blocks,
                max_source_characters=max_source_characters,
                language_hint=payload.language_hint,
                rules_version=rules_version,
            )
        except ReaderError as error:
            await _send_error(
                websocket,
                translate_reader_error(error, cursor_input=True),
                close_code=1008,
            )
            return

        voice = container.voice_registry.get(voice_id)
        cancel_event = asyncio.Event()
        release_event = asyncio.Event()
        receiver_task = asyncio.create_task(
            _receive_control(
                websocket,
                stream_id=stream_id,
                cancel_event=cancel_event,
                release_event=release_event,
                backend=container.backend,
            )
        )
        chunks_sent = 0
        latest_cursor = window.start_cursor
        first_chunk = True
        try:
            container.streaming_metrics.mark_started()
            await websocket.send_json(
                {
                    "type": "started",
                    "stream_id": stream_id,
                    "document_id": payload.document_id,
                    "sample_rate_hz": voice.sample_rate_hz,
                    "channels": 1,
                    "sample_format": "pcm16le",
                    "pipeline_version": 1,
                    "rules_version": window.rules_version,
                    "source_offset_encoding": "utf-16",
                    "cursor": _cursor_payload(window, window.start_cursor),
                }
            )
            service.observability.log_reader_operation(
                operation="reader_stream_start",
                document_id=payload.document_id,
                block_count=len(window.blocks),
                character_count=window.source_character_count,
            )
            for warning in window.rule_warnings:
                await websocket.send_json(
                    {
                        "type": "warning",
                        "stream_id": stream_id,
                        "warning": {
                            "type": warning.code,
                            "message": warning.message,
                            "rule_id": warning.rule_id,
                        },
                    }
                )

            for fragment_index, fragment in enumerate(window.fragments):
                if cancel_event.is_set():
                    break
                request = _synthesis_request(
                    fragment,
                    voice_id=voice_id,
                    stream_id=stream_id,
                    language_hint=payload.language_hint,
                    prosody=payload.prosody,
                )
                iterator = container.backend.synthesize_stream(request)
                while not cancel_event.is_set():
                    backend_chunk = await asyncio.to_thread(_next_chunk, iterator)
                    if backend_chunk is None:
                        break
                    if cancel_event.is_set():
                        break
                    if backend_chunk.sample_rate_hz != voice.sample_rate_hz:
                        raise BackendError("Reader backend changed sample rate midstream")
                    if backend_chunk.channels != 1:
                        raise BackendError("Reader backend returned non-mono audio")
                    if first_chunk:
                        container.streaming_metrics.mark_first_chunk(
                            int((monotonic() - started_at) * 1000)
                        )
                        first_chunk = False
                    chunk_cursor_end = (
                        fragment.cursor_end
                        if backend_chunk.is_last
                        else fragment.cursor_start
                    )
                    is_last = (
                        fragment_index == len(window.fragments) - 1
                        and backend_chunk.is_last
                    )
                    await websocket.send_json(
                        {
                            "type": "mark",
                            "stream_id": stream_id,
                            "document_id": payload.document_id,
                            "chunk_index": chunks_sent,
                            "pcm_byte_count": len(backend_chunk.pcm_bytes),
                            "duration_ms": backend_chunk.duration_ms,
                            "cursor_start": _cursor_payload(
                                window,
                                fragment.cursor_start,
                            ),
                            "cursor_end": _cursor_payload(window, chunk_cursor_end),
                            "source_spans": [
                                span.api_payload(window.block_text(span.block_id))
                                for span in fragment.source_spans
                            ],
                            "section_id": fragment.section_id,
                            "is_last": is_last,
                        }
                    )
                    await websocket.send_bytes(backend_chunk.pcm_bytes)
                    chunks_sent += 1
                    latest_cursor = chunk_cursor_end

            if cancel_event.is_set():
                outcome = "cancelled"
                with suppress(RuntimeError, WebSocketDisconnect):
                    await websocket.send_json(
                        {
                            "type": "cancelled",
                            "stream_id": stream_id,
                            "chunks_sent": chunks_sent,
                            "generated_cursor": _cursor_payload(window, latest_cursor),
                        }
                    )
                container.streaming_metrics.mark_cancelled()
            else:
                outcome = "success"
                done_cursor = window.next_cursor or window.generated_cursor
                await websocket.send_json(
                    {
                        "type": "done",
                        "stream_id": stream_id,
                        "chunks_sent": chunks_sent,
                        "cursor": _cursor_payload(window, done_cursor),
                        "document_complete": window.document_complete,
                        "next_window_available": window.next_cursor is not None,
                    }
                )
                container.streaming_metrics.mark_completed()
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        release_event.wait(),
                        timeout=READER_WEBSOCKET_RELEASE_TIMEOUT_SECONDS,
                    )
        except WebSocketDisconnect:
            outcome = "cancelled"
            container.backend.cancel(stream_id)
            container.streaming_metrics.mark_cancelled()
        except BackendError as error:
            outcome = "failure"
            container.backend.cancel(stream_id)
            container.streaming_metrics.mark_failed()
            container.observability.logger.exception(
                json.dumps(
                    {
                        "event": "reader_stream_error",
                        "stream_id": stream_id,
                        "document_id": payload.document_id,
                        "error_type": type(error).__name__,
                    }
                )
            )
            await _send_error(
                websocket,
                reader_api_error(
                    "reader_voice_unavailable",
                    status_code=503,
                    message="The Reader voice could not synthesize this window.",
                ),
                close_code=1011,
            )
        except Exception as error:
            outcome = "failure"
            container.backend.cancel(stream_id)
            container.streaming_metrics.mark_failed()
            container.observability.logger.exception(
                json.dumps(
                    {
                        "event": "reader_stream_error",
                        "stream_id": stream_id,
                        "document_id": payload.document_id,
                        "error_type": type(error).__name__,
                    }
                )
            )
            await _send_error(
                websocket,
                reader_api_error(
                    "reader_stream_failed",
                    status_code=500,
                    message="The Reader stream failed.",
                ),
                close_code=1011,
            )
        finally:
            clear_cancel = getattr(container.backend, "clear_cancel", None)
            if clear_cancel is not None:
                clear_cancel(stream_id)
            receiver_task.cancel()
            with suppress(asyncio.CancelledError):
                await receiver_task
            container.observability.synthesis_metrics.record(
                mode="reader_stream",
                outcome=outcome,
                latency_ms=(monotonic() - started_at) * 1000,
            )
            service.observability.log_reader_operation(
                operation=f"reader_stream_{outcome}",
                document_id=payload.document_id,
            )


def _synthesis_request(
    fragment: ReaderSpeechFragment,
    *,
    voice_id: str,
    stream_id: str,
    language_hint: str | None,
    prosody: ProsodyPayload,
) -> SynthesisRequest:
    return SynthesisRequest(
        text=fragment.spoken_text,
        voice=voice_id,
        format=AudioFormat.WAV,
        prosody=ProsodySettings(
            rate=prosody.rate,
            volume=prosody.volume,
            pitch=prosody.pitch,
            pause_strategy=prosody.pause_strategy,
            sentence_pause_ms=max(prosody.sentence_pause_ms, fragment.pause_ms_hint),
            comma_pause_ms=prosody.comma_pause_ms,
            emphasis=tuple(prosody.emphasis),
        ),
        options=SynthesisOptions(
            normalize_text=False,
            streaming_preferred=True,
            input_format="plain_text",
            stream_frame_ms=40,
        ),
        language_hint=language_hint,
        job_id=stream_id,
    )


def _next_chunk(iterator: object):
    try:
        return next(iterator)
    except StopIteration:
        return None


def _cursor_payload(
    window: ReaderStreamWindow,
    cursor: ReaderStreamCursor,
) -> dict[str, object]:
    if cursor.character_offset == 0:
        return {
            "block_id": cursor.block_id,
            "block_ordinal": cursor.block_ordinal,
            "character_offset": 0,
            "content_revision": cursor.content_revision,
            "segment_index": cursor.segment_index,
        }
    return cursor.api_payload(window.block_text(cursor.block_id))


async def _receive_start_message(websocket: WebSocket) -> dict[str, object]:
    message = await asyncio.wait_for(
        websocket.receive(),
        timeout=READER_WEBSOCKET_START_TIMEOUT_SECONDS,
    )
    if message.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect()
    raw = message.get("text")
    if not isinstance(raw, str):
        raise reader_api_error(
            "reader_conflict",
            status_code=400,
            message="Reader stream start event must be JSON text.",
        )
    if len(raw) > READER_WEBSOCKET_START_MAX_CHARS:
        raise reader_api_error(
            "reader_conflict",
            status_code=413,
            message="Reader stream start event is too large.",
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise reader_api_error(
            "reader_conflict",
            status_code=400,
            message="Reader stream start event is invalid JSON.",
        ) from error
    if not isinstance(payload, dict):
        raise reader_api_error(
            "reader_conflict",
            status_code=400,
            message="Reader stream start event must be a JSON object.",
        )
    return payload


async def _receive_control(
    websocket: WebSocket,
    *,
    stream_id: str,
    cancel_event: asyncio.Event,
    release_event: asyncio.Event,
    backend: object,
) -> None:
    while True:
        try:
            message = await websocket.receive_json()
        except WebSocketDisconnect:
            cancel_event.set()
            release_event.set()
            backend.cancel(stream_id)
            return
        if message.get("stream_id") not in {None, stream_id}:
            continue
        if message.get("type") == "cancel":
            cancel_event.set()
            release_event.set()
            backend.cancel(stream_id)
            return
        if message.get("type") == "release":
            release_event.set()
            return


async def _send_error(
    websocket: WebSocket,
    error: APIError,
    *,
    close_code: int,
) -> None:
    with suppress(RuntimeError, WebSocketDisconnect):
        await websocket.send_json({"type": "error", "error": error.to_response()["error"]})
        await websocket.close(code=close_code)


def _reader_service(websocket: WebSocket) -> ReaderApplicationService:
    runtime = websocket.app.state.container.reader
    if not runtime.enabled:
        raise reader_disabled()
    if runtime.service is None or not runtime.database_ready:
        raise reader_database_unavailable()
    return runtime.service
