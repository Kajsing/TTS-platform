from __future__ import annotations

import io
import math
import wave
from array import array
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WavStats:
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frame_count: int
    duration_ms: int
    rms: float


def encode_wav_pcm16(
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


def inspect_wav(audio_bytes: bytes) -> WavStats:
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width_bytes = wav_file.getsampwidth()
        sample_rate_hz = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        pcm_bytes = wav_file.readframes(frame_count)

    samples = array("h")
    samples.frombytes(pcm_bytes)
    rms = 0.0
    if samples:
        mean_square = sum(sample * sample for sample in samples) / len(samples)
        rms = math.sqrt(mean_square)

    duration_ms = int(frame_count / sample_rate_hz * 1000) if sample_rate_hz else 0
    return WavStats(
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        sample_width_bytes=sample_width_bytes,
        frame_count=frame_count,
        duration_ms=duration_ms,
        rms=rms,
    )
