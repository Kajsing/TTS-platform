from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from tts_core.models import AudioChunk, SynthesisRequest, SynthesisResult, VoiceDescriptor


class BackendError(RuntimeError):
    """Base error for backend failures."""


class BackendNotReadyError(BackendError):
    """Raised when a backend contract exists but the implementation is not ready."""


class UnsupportedOperationError(BackendError):
    """Raised when a backend does not support the requested operation."""


class TTSBackend(Protocol):
    name: str

    def list_voices(self) -> list[VoiceDescriptor]:
        ...

    def warmup(self, voice_id: str | None = None) -> None:
        ...

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        ...

    def synthesize_stream(self, request: SynthesisRequest) -> Iterator[AudioChunk]:
        ...

    def cancel(self, job_id: str) -> bool:
        ...

    def is_cancelled(self, job_id: str) -> bool:
        ...

    def clear_cancel(self, job_id: str) -> None:
        ...
