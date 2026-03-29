from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi import Response as FastAPIResponse
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from .auth import rotate_auth_token
from .bootstrap import build_application_state
from .config import AppConfig, load_config
from .errors import APIError, invalid_request
from .schemas import SynthesizeRequestPayload
from .security import (
    enforce_headers_access,
    enforce_write_access,
    extract_bearer_token_from_headers,
    validate_auth_token,
)
from .synthesis import SynthesisService


def create_app(
    *,
    config: AppConfig | None = None,
    config_path: str | Path | None = None,
    repo_root: Path | None = None,
) -> FastAPI:
    resolved_config = config or load_config(config_path)
    app = FastAPI(title="Local TTS Service", version="0.1.0")
    app.state.container = build_application_state(
        resolved_config,
        repo_root=repo_root or _repo_root(),
    )
    _register_middleware(app)
    _register_exception_handlers(app)
    _register_routes(app)
    return app


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def handle_api_error(_, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_response(),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(_, exc: RequestValidationError) -> JSONResponse:
        issues = []
        first_param: str | None = None
        for issue in exc.errors():
            location = issue.get("loc", ())
            path = ".".join(str(part) for part in location if part != "body")
            if first_param is None and path:
                first_param = path
            issues.append(
                {
                    "param": path or None,
                    "message": issue.get("msg", "Invalid request body."),
                    "type": issue.get("type"),
                }
            )
        api_error = invalid_request(
            "Request body validation failed.",
            param=first_param,
            details={"issues": issues},
        )
        return JSONResponse(status_code=api_error.status_code, content=api_error.to_response())


def _register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def observe_http_requests(request: Request, call_next) -> FastAPIResponse:
        container = app.state.container
        request_id = request.headers.get("x-request-id", str(uuid4()))
        start_time = monotonic()
        response: FastAPIResponse | None = None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (monotonic() - start_time) * 1000
            container.observability.request_metrics.record(
                endpoint=request.url.path,
                status_code=status_code,
                latency_ms=duration_ms,
            )
            container.observability.log_http_request(
                request_id=request_id,
                method=request.method,
                endpoint=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
            if response is not None:
                response.headers["x-request-id"] = request_id


def _register_routes(app: FastAPI) -> None:
    @app.get("/v1/health")
    async def health() -> dict[str, object]:
        container = app.state.container
        uptime_seconds = int(
            (datetime.now(timezone.utc) - container.started_at).total_seconds()
        )
        default_voice = container.voice_registry.default_voice
        checks = {
            "process_running": True,
            "backend_ready": container.backend_ready,
            "default_voice_loaded": container.default_voice_loaded,
        }
        return {
            "status": "ok" if all(checks.values()) else "degraded",
            "version": app.version,
            "uptime_s": uptime_seconds,
            "default_voice": default_voice.id if default_voice is not None else None,
            "checks": checks,
            "startup_error": container.startup_error,
            "auth_enabled": container.auth.enabled,
            "backend": container.backend.snapshot(),
            "streaming": container.streaming_metrics.snapshot(),
            "observability": container.observability.snapshot(),
        }

    @app.get("/v1/voices")
    async def voices() -> dict[str, object]:
        container = app.state.container
        return {
            "voices": [asdict(voice) for voice in container.voice_registry.list()],
            "default_voice": container.config.tts.default_voice,
        }

    @app.post("/v1/tts")
    async def synthesize(request: Request, payload: SynthesizeRequestPayload) -> Response:
        container = app.state.container
        _enforce_protected_request(container, request)
        synthesis_service = _build_synthesis_service(container)
        result = synthesis_service.synthesize(payload)
        return Response(content=result.audio_bytes, media_type="audio/wav")

    @app.post("/v1/auth/rotate")
    async def rotate_token(request: Request) -> dict[str, object]:
        container = app.state.container
        _enforce_protected_request(container, request)
        container.auth = rotate_auth_token(container.auth)
        return {
            "token": container.auth.token,
            "token_file": str(container.auth.token_file),
        }

    @app.post("/v1/tts/jobs")
    async def create_tts_job(
        request: Request,
        payload: SynthesizeRequestPayload,
    ) -> dict[str, object]:
        container = app.state.container
        _enforce_protected_request(container, request)
        job = container.job_manager.create_job(
            payload,
            synthesis_service=_build_synthesis_service(container),
        )
        return {
            "job_id": job.job_id,
            "status": "queued",
        }

    @app.get("/v1/tts/jobs/{job_id}")
    async def get_tts_job(request: Request, job_id: str) -> dict[str, object]:
        container = app.state.container
        _enforce_protected_request(container, request)
        return container.job_manager.get_job(job_id).to_payload()

    @app.get("/v1/tts/jobs/{job_id}/result")
    async def get_tts_job_result(request: Request, job_id: str) -> Response:
        container = app.state.container
        _enforce_protected_request(container, request)
        result = container.job_manager.get_job_result(job_id)
        return Response(content=result.audio_bytes, media_type="audio/wav")

    @app.delete("/v1/tts/jobs/{job_id}")
    async def cancel_tts_job(request: Request, job_id: str) -> dict[str, object]:
        container = app.state.container
        _enforce_protected_request(container, request)
        return container.job_manager.cancel_job(job_id).to_payload()

    @app.websocket("/v1/tts/stream")
    async def tts_stream(websocket: WebSocket) -> None:
        container = app.state.container
        await websocket.accept()

        try:
            enforce_headers_access(
                headers=websocket.headers,
                client_host=websocket.client.host if websocket.client is not None else "unknown",
                auth_state=container.auth,
                origin_policy=container.origin_policy,
                rate_limiter=container.rate_limiter,
                require_auth=False,
            )
        except APIError as exc:
            await websocket.send_json({"type": "error", "error": exc.to_response()["error"]})
            await websocket.close(code=1008)
            return

        try:
            initial_message = await websocket.receive_json()
            if initial_message.get("type") != "start":
                raise invalid_request(
                    "First WebSocket event must be a start event.",
                    param="type",
                )

            header_token = extract_bearer_token_from_headers(websocket.headers)
            provided_token = header_token or initial_message.get("auth_token")
            validate_auth_token(container.auth, provided_token)

            payload = SynthesizeRequestPayload.model_validate(initial_message.get("payload", {}))
            stream_id = str(uuid4())
            synthesis_service = _build_synthesis_service(container)
            execution = synthesis_service.prepare_request(payload, job_id=stream_id)
        except ValidationError as exc:
            api_error = invalid_request(
                "Request body validation failed.",
                details={"issues": exc.errors()},
            )
            await websocket.send_json({"type": "error", "error": api_error.to_response()["error"]})
            await websocket.close(code=1003)
            return
        except APIError as exc:
            await websocket.send_json({"type": "error", "error": exc.to_response()["error"]})
            await websocket.close(code=1003)
            return

        cancel_event = asyncio.Event()
        container.streaming_metrics.mark_started()
        start_time = monotonic()

        await websocket.send_json(
            {
                "type": "started",
                "job_id": stream_id,
                "sample_rate_hz": container.voice_registry.get(
                    execution.request.voice
                ).sample_rate_hz,
                "channels": 1,
            }
        )

        receiver_task = asyncio.create_task(
            _receive_stream_control(
                websocket,
                job_id=stream_id,
                cancel_event=cancel_event,
                backend=container.backend,
            )
        )

        first_chunk_sent = False
        chunk_count = 0
        bytes_sent = 0

        try:
            iterator = synthesis_service.synthesize_stream_execution(execution)
            while True:
                if cancel_event.is_set():
                    container.backend.cancel(stream_id)
                    break
                try:
                    chunk = next(iterator)
                except StopIteration:
                    break

                if cancel_event.is_set():
                    container.backend.cancel(stream_id)
                    break

                if not first_chunk_sent:
                    container.streaming_metrics.mark_first_chunk(
                        int((monotonic() - start_time) * 1000)
                    )
                    first_chunk_sent = True

                await websocket.send_json(
                    {
                        "type": "mark",
                        "job_id": stream_id,
                        "chunk_index": chunk.chunk_index,
                        "duration_ms": chunk.duration_ms,
                        "is_last": chunk.is_last,
                    }
                )
                await websocket.send_bytes(chunk.pcm_bytes)
                chunk_count += 1
                bytes_sent += len(chunk.pcm_bytes)
                await asyncio.sleep(0.001)

            if cancel_event.is_set():
                container.streaming_metrics.mark_cancelled()
                await websocket.send_json(
                    {
                        "type": "cancelled",
                        "job_id": stream_id,
                        "chunks_sent": chunk_count,
                    }
                )
            else:
                container.streaming_metrics.mark_completed()
                await websocket.send_json(
                    {
                        "type": "done",
                        "job_id": stream_id,
                        "chunks_sent": chunk_count,
                        "bytes_sent": bytes_sent,
                    }
                )
        except WebSocketDisconnect:
            container.backend.cancel(stream_id)
            container.streaming_metrics.mark_cancelled()
        except Exception as exc:
            container.backend.cancel(stream_id)
            container.streaming_metrics.mark_failed()
            await websocket.send_json(
                {
                    "type": "error",
                    "error": {
                        "type": "internal_error",
                        "message": str(exc),
                        "param": None,
                        "request_id": stream_id,
                        "details": {},
                    },
                }
            )
        finally:
            receiver_task.cancel()
            with suppress(asyncio.CancelledError):
                await receiver_task


def _enforce_protected_request(container: object, request: Request) -> None:
    enforce_write_access(
        request,
        auth_state=container.auth,
        origin_policy=container.origin_policy,
        rate_limiter=container.rate_limiter,
    )


def _build_synthesis_service(container: object) -> SynthesisService:
    return SynthesisService(
        voice_registry=container.voice_registry,
        text_pipeline=container.text_pipeline,
        chunk_planner=container.chunk_planner,
        backend=container.backend,
        default_voice_id=container.config.tts.default_voice,
        max_chars_per_request=container.config.tts.max_chars_per_request,
        stream_frame_ms=container.config.streaming.audio_frame_ms,
        observability=container.observability,
    )


async def _receive_stream_control(
    websocket: WebSocket,
    *,
    job_id: str,
    cancel_event: asyncio.Event,
    backend: object,
) -> None:
    while True:
        try:
            message = await websocket.receive_json()
        except WebSocketDisconnect:
            cancel_event.set()
            backend.cancel(job_id)
            return

        if message.get("type") == "cancel":
            cancel_event.set()
            backend.cancel(job_id)
            return


app = create_app()
