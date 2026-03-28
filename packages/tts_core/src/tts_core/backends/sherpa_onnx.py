from __future__ import annotations

import io
import math
import wave
from array import array
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
        voice = self._resolve_voice(request.voice)
        pcm_bytes = self._render_pcm16(
            request.text,
            sample_rate_hz=voice.sample_rate_hz,
            rate=request.prosody.rate,
            volume=request.prosody.volume,
            pitch=request.prosody.pitch,
        )
        wav_bytes = self._encode_wav(
            pcm_bytes,
            sample_rate_hz=voice.sample_rate_hz,
            channels=1,
        )
        return SynthesisResult(
            audio_bytes=wav_bytes,
            sample_rate_hz=voice.sample_rate_hz,
            channels=1,
        )

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

    def _render_pcm16(
        self,
        text: str,
        *,
        sample_rate_hz: int,
        rate: float,
        volume: float,
        pitch: int,
    ) -> bytes:
        safe_rate = max(rate, 0.25)
        clamped_volume = min(max(volume, 0.0), 1.5)
        amplitude = int(32767 * 0.18 * clamped_volume)
        base_frequency = 170 + max(min(pitch, 24), -24) * 2
        samples = array("h")

        self._append_silence(samples, sample_rate_hz, duration_ms=40)
        for token in self._tokenize(text):
            if token.isspace():
                self._append_silence(samples, sample_rate_hz, duration_ms=30)
                continue

            if token in {".", "!", "?"}:
                self._append_silence(samples, sample_rate_hz, duration_ms=150)
                continue

            if token in {",", ";", ":"}:
                self._append_silence(samples, sample_rate_hz, duration_ms=80)
                continue

            token_duration_ms = max(70, int((80 + len(token) * 28) / safe_rate))
            token_frequency = base_frequency + (sum(ord(char) for char in token) % 110)
            self._append_tone(
                samples,
                sample_rate_hz,
                frequency_hz=token_frequency,
                duration_ms=token_duration_ms,
                amplitude=amplitude,
            )
            self._append_silence(samples, sample_rate_hz, duration_ms=20)

        self._append_silence(samples, sample_rate_hz, duration_ms=60)
        return samples.tobytes()

    def _tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        current = []
        punctuation = {".", ",", "!", "?", ";", ":"}

        for character in text:
            if character.isspace():
                if current:
                    tokens.append("".join(current))
                    current = []
                tokens.append(" ")
                continue
            if character in punctuation:
                if current:
                    tokens.append("".join(current))
                    current = []
                tokens.append(character)
                continue
            current.append(character)

        if current:
            tokens.append("".join(current))
        return tokens

    def _append_silence(
        self,
        samples: array,
        sample_rate_hz: int,
        *,
        duration_ms: int,
    ) -> None:
        silence_samples = int(sample_rate_hz * (duration_ms / 1000))
        samples.extend([0] * silence_samples)

    def _append_tone(
        self,
        samples: array,
        sample_rate_hz: int,
        *,
        frequency_hz: int,
        duration_ms: int,
        amplitude: int,
    ) -> None:
        sample_count = max(1, int(sample_rate_hz * (duration_ms / 1000)))
        attack_count = max(1, int(sample_count * 0.1))
        release_count = max(1, int(sample_count * 0.12))

        for sample_index in range(sample_count):
            attack = min(1.0, sample_index / attack_count)
            release = min(1.0, (sample_count - sample_index - 1) / release_count)
            envelope = min(attack, release, 1.0)
            phase = 2 * math.pi * frequency_hz * (sample_index / sample_rate_hz)
            sample = int(amplitude * envelope * math.sin(phase))
            samples.append(sample)

    def _encode_wav(
        self,
        pcm_bytes: bytes,
        *,
        sample_rate_hz: int,
        channels: int,
    ) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate_hz)
            wav_file.writeframes(pcm_bytes)
        return buffer.getvalue()
