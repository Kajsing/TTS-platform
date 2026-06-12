from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from time import monotonic

from tts_core.audio import decode_wav_pcm16, encode_wav_pcm16
from tts_core.backends.base import BackendError
from tts_core.models import (
    AudioChunk,
    AudioFormat,
    ChunkPlan,
    ProsodySettings,
    SynthesisOptions,
    SynthesisRequest,
    SynthesisResult,
)
from tts_core.registry import VoiceRegistry
from tts_core.text import ChunkPlanner, TextPipeline

from .errors import APIError, engine_error, invalid_request
from .observability import ObservabilityState
from .schemas import SynthesizeRequestPayload


class SynthesisCancelledError(RuntimeError):
    """Raised when synthesis sees a cancellation request for its job id."""


@dataclass(frozen=True, slots=True)
class SynthesisExecution:
    request: SynthesisRequest
    normalized_text: str
    segments: tuple[str, ...]
    chunk_plan: ChunkPlan


@dataclass(slots=True)
class SynthesisService:
    voice_registry: VoiceRegistry
    text_pipeline: TextPipeline
    chunk_planner: ChunkPlanner
    backend: object
    default_voice_id: str
    max_chars_per_request: int
    stream_frame_ms: int = 40
    observability: ObservabilityState | None = None

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

        chunk_plan = self.chunk_planner.plan(
            processed_text.segments,
            sentence_pause_ms=payload.prosody.sentence_pause_ms,
            comma_pause_ms=payload.prosody.comma_pause_ms,
        )
        if not chunk_plan.chunks:
            raise invalid_request("Text must not be empty.", param="text")

        request = SynthesisRequest(
            text=processed_text.normalized_text,
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
            chunk_plan=chunk_plan,
        )

    def synthesize(self, payload: SynthesizeRequestPayload):
        execution = self.prepare_request(payload)
        return self.synthesize_execution(execution)

    def synthesize_execution(self, execution: SynthesisExecution):
        start_time = monotonic()
        try:
            result = self._synthesize_chunk_plan(execution)
            self._record_synthesis("sync", "success", start_time)
            return result
        except SynthesisCancelledError:
            self._record_synthesis("sync", "cancelled", start_time)
            raise
        except BackendError as exc:
            self._record_synthesis("sync", "failure", start_time)
            raise engine_error(
                str(exc),
                details={"backend": getattr(self.backend, "name", "unknown")},
            ) from exc
        except APIError:
            self._record_synthesis("sync", "failure", start_time)
            raise

    def synthesize_stream_execution(
        self,
        execution: SynthesisExecution,
    ) -> Iterator[AudioChunk]:
        start_time = monotonic()
        try:
            for chunk in self._stream_chunk_plan(execution):
                yield chunk
            self._record_synthesis("stream", "success", start_time)
        except SynthesisCancelledError:
            self._record_synthesis("stream", "cancelled", start_time)
            raise
        except BackendError as exc:
            self._record_synthesis("stream", "failure", start_time)
            raise engine_error(
                str(exc),
                details={"backend": getattr(self.backend, "name", "unknown")},
            ) from exc
        except APIError:
            self._record_synthesis("stream", "failure", start_time)
            raise

    def _record_synthesis(self, mode: str, outcome: str, start_time: float) -> None:
        if self.observability is None:
            return
        self.observability.synthesis_metrics.record(
            mode=mode,
            outcome=outcome,
            latency_ms=(monotonic() - start_time) * 1000,
        )

    def _synthesize_chunk_plan(self, execution: SynthesisExecution) -> SynthesisResult:
        combined_pcm = bytearray()
        sample_rate_hz: int | None = None
        channels: int | None = None

        for planned_chunk in execution.chunk_plan.chunks:
            self._raise_if_cancelled(execution)
            chunk_request = self._build_chunk_request(execution.request, planned_chunk.text)
            result = self.backend.synthesize(chunk_request)
            self._raise_if_cancelled(execution)
            pcm_bytes, chunk_sample_rate_hz, chunk_channels = decode_wav_pcm16(result.audio_bytes)
            if sample_rate_hz is None:
                sample_rate_hz = chunk_sample_rate_hz
                channels = chunk_channels
            elif sample_rate_hz != chunk_sample_rate_hz or channels != chunk_channels:
                raise engine_error(
                    "Backend returned inconsistent audio settings across chunks.",
                    details={
                        "expected_sample_rate_hz": sample_rate_hz,
                        "actual_sample_rate_hz": chunk_sample_rate_hz,
                        "expected_channels": channels,
                        "actual_channels": chunk_channels,
                    },
                )
            combined_pcm.extend(pcm_bytes)

        resolved_sample_rate_hz = sample_rate_hz or self.voice_registry.get(
            execution.request.voice
        ).sample_rate_hz
        resolved_channels = channels or 1
        return SynthesisResult(
            audio_bytes=encode_wav_pcm16(
                bytes(combined_pcm),
                sample_rate_hz=resolved_sample_rate_hz,
                channels=resolved_channels,
            ),
            sample_rate_hz=resolved_sample_rate_hz,
            channels=resolved_channels,
        )

    def _stream_chunk_plan(self, execution: SynthesisExecution) -> Iterator[AudioChunk]:
        global_chunk_index = 0
        total_chunks = len(execution.chunk_plan.chunks)
        expected_sample_rate_hz: int | None = None
        expected_channels: int | None = None
        for plan_index, planned_chunk in enumerate(execution.chunk_plan.chunks):
            self._raise_if_cancelled(execution)
            chunk_request = self._build_chunk_request(execution.request, planned_chunk.text)
            for backend_chunk in self.backend.synthesize_stream(chunk_request):
                self._raise_if_cancelled(execution)
                if expected_sample_rate_hz is None:
                    expected_sample_rate_hz = backend_chunk.sample_rate_hz
                    expected_channels = backend_chunk.channels
                elif (
                    expected_sample_rate_hz != backend_chunk.sample_rate_hz
                    or expected_channels != backend_chunk.channels
                ):
                    raise engine_error(
                        "Backend returned inconsistent audio settings across stream chunks.",
                        details={
                            "expected_sample_rate_hz": expected_sample_rate_hz,
                            "actual_sample_rate_hz": backend_chunk.sample_rate_hz,
                            "expected_channels": expected_channels,
                            "actual_channels": backend_chunk.channels,
                        },
                    )

                is_last = plan_index == total_chunks - 1 and backend_chunk.is_last
                yield AudioChunk(
                    job_id=backend_chunk.job_id,
                    chunk_index=global_chunk_index,
                    sample_rate_hz=backend_chunk.sample_rate_hz,
                    channels=backend_chunk.channels,
                    pcm_bytes=backend_chunk.pcm_bytes,
                    duration_ms=max(backend_chunk.duration_ms, 1),
                    is_last=is_last,
                )
                global_chunk_index += 1

    def _build_chunk_request(
        self,
        request: SynthesisRequest,
        chunk_text: str,
    ) -> SynthesisRequest:
        return SynthesisRequest(
            text=chunk_text,
            voice=request.voice,
            format=request.format,
            prosody=request.prosody,
            options=request.options,
            language_hint=request.language_hint,
            job_id=request.job_id,
        )

    def _raise_if_cancelled(self, execution: SynthesisExecution) -> None:
        job_id = execution.request.job_id
        if job_id is None:
            return
        is_cancelled = getattr(self.backend, "is_cancelled", None)
        if is_cancelled is not None and is_cancelled(job_id):
            raise SynthesisCancelledError(f"Synthesis job '{job_id}' was cancelled.")
