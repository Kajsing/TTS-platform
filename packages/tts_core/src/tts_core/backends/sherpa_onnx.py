from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tts_core.models import (
    AudioChunk,
    SynthesisRequest,
    SynthesisResult,
    VoiceCapabilities,
    VoiceDescriptor,
)
from tts_core.registry import VoiceNotFoundError

from .base import BackendNotReadyError


def build_stub_voice() -> VoiceDescriptor:
    return VoiceDescriptor(
        id="sherpa-en-debug",
        name="Sherpa English Debug",
        engine="sherpa_onnx",
        language="en",
        sample_rate_hz=24000,
        license="unknown",
        source="models/voices/sherpa-en-debug",
        quality_tier="development",
        latency_tier="unknown",
        tags=("stub", "debug"),
        capabilities=VoiceCapabilities(
            supports_pitch=False,
            supports_streaming=False,
            supports_multi_speaker=False,
        ),
    )


@dataclass(slots=True)
class SherpaOnnxBackend:
    models_root: Path
    voices: Sequence[VoiceDescriptor] = field(default_factory=lambda: (build_stub_voice(),))

    name: str = "sherpa_onnx"

    def list_voices(self) -> list[VoiceDescriptor]:
        return list(self.voices)

    def warmup(self, voice_id: str | None = None) -> None:
        if voice_id is None:
            return
        self._resolve_voice(voice_id)

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        self._resolve_voice(request.voice)
        raise BackendNotReadyError("Sherpa-ONNX synthesis will be implemented in phase 2.")

    def synthesize_stream(self, request: SynthesisRequest) -> Iterator[AudioChunk]:
        self._resolve_voice(request.voice)
        raise BackendNotReadyError("Sherpa-ONNX streaming will be implemented in phase 4.")
        yield  # pragma: no cover

    def cancel(self, job_id: str) -> bool:
        return False

    def _resolve_voice(self, voice_id: str) -> VoiceDescriptor:
        for voice in self.voices:
            if voice.id == voice_id:
                return voice
        raise VoiceNotFoundError(f"Unknown voice id for sherpa-onnx backend: {voice_id}")
