from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from tts_core.backends.base import BackendError
from tts_core.models import (
    AudioChunk,
    AudioFormat,
    ProsodySettings,
    SynthesisOptions,
    SynthesisRequest,
)
from tts_core.registry import VoiceRegistry
from tts_core.text import TextPipeline

from .errors import APIError, engine_error, invalid_request
from .schemas import SynthesizeRequestPayload


@dataclass(frozen=True, slots=True)
class SynthesisExecution:
    request: SynthesisRequest
    normalized_text: str
    segments: tuple[str, ...]


@dataclass(slots=True)
class SynthesisService:
    voice_registry: VoiceRegistry
    text_pipeline: TextPipeline
    backend: object
    default_voice_id: str
    max_chars_per_request: int
    stream_frame_ms: int = 40

    def prepare_request(
        self,
        payload: SynthesizeRequestPayload,
        *,
        job_id: str | None = None,
    ) -> SynthesisExecution:
        if len(payload.text) > self.max_chars_per_request:
            raise invalid_request(
                "Text exceeds max_chars_per_request.",
                param="text",
                details={"max_chars_per_request": self.max_chars_per_request},
            )

        if payload.options.input_format != "plain_text":
            raise invalid_request(
                "Only plain_text input_format is supported in phase 2.",
                param="options.input_format",
            )

        voice_id = payload.voice or self.default_voice_id
        if not self.voice_registry.has(voice_id):
            raise invalid_request(
                "Unknown voice id.",
                param="voice",
                details={"voice": voice_id},
            )

        try:
            audio_format = AudioFormat(payload.format.lower())
        except ValueError as exc:
            raise invalid_request(
                "Unsupported audio format.",
                param="format",
                details={"supported_formats": [AudioFormat.WAV.value]},
            ) from exc

        processed_text = self.text_pipeline.process(
            payload.text,
            language_hint=payload.language_hint,
            normalize_text=payload.options.normalize_text,
        )
        if not processed_text.normalized_text:
            raise invalid_request("Text must not be empty.", param="text")

        request = SynthesisRequest(
            text=" ".join(processed_text.segments),
            voice=voice_id,
            format=audio_format,
            prosody=ProsodySettings(
                rate=payload.prosody.rate,
                volume=payload.prosody.volume,
                pitch=payload.prosody.pitch,
                pause_strategy=payload.prosody.pause_strategy,
                sentence_pause_ms=payload.prosody.sentence_pause_ms,
                comma_pause_ms=payload.prosody.comma_pause_ms,
                emphasis=tuple(payload.prosody.emphasis),
            ),
            options=SynthesisOptions(
                normalize_text=payload.options.normalize_text,
                streaming_preferred=payload.options.streaming_preferred,
                input_format=payload.options.input_format,
                stream_frame_ms=self.stream_frame_ms,
            ),
            language_hint=payload.language_hint,
            job_id=job_id,
        )
        return SynthesisExecution(
            request=request,
            normalized_text=processed_text.normalized_text,
            segments=processed_text.segments,
        )

    def synthesize(self, payload: SynthesizeRequestPayload):
        execution = self.prepare_request(payload)
        return self.synthesize_execution(execution)

    def synthesize_execution(self, execution: SynthesisExecution):
        try:
            return self.backend.synthesize(execution.request)
        except BackendError as exc:
            raise engine_error(
                str(exc),
                details={"backend": getattr(self.backend, "name", "unknown")},
            ) from exc
        except APIError:
            raise

    def synthesize_stream_execution(
        self,
        execution: SynthesisExecution,
    ) -> Iterator[AudioChunk]:
        try:
            return iter(self.backend.synthesize_stream(execution.request))
        except BackendError as exc:
            raise engine_error(
                str(exc),
                details={"backend": getattr(self.backend, "name", "unknown")},
            ) from exc
        except APIError:
            raise
