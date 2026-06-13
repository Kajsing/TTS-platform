from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AudioFormat(str, Enum):
    WAV = "wav"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ProsodySettings:
    rate: float = 1.0
    volume: float = 1.0
    pitch: int = 0
    pause_strategy: str = "auto"
    sentence_pause_ms: int = 120
    comma_pause_ms: int = 60
    emphasis: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SynthesisOptions:
    normalize_text: bool = True
    streaming_preferred: bool = False
    input_format: str = "plain_text"
    stream_frame_ms: int = 40


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    text: str
    voice: str
    format: AudioFormat = AudioFormat.WAV
    prosody: ProsodySettings = field(default_factory=ProsodySettings)
    options: SynthesisOptions = field(default_factory=SynthesisOptions)
    language_hint: str | None = None
    job_id: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("text must not be empty")
        if not self.voice.strip():
            raise ValueError("voice must not be empty")


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    audio_bytes: bytes
    sample_rate_hz: int
    channels: int
    format: AudioFormat = AudioFormat.WAV


@dataclass(frozen=True, slots=True)
class PlannedChunk:
    index: int
    text: str
    char_count: int
    pause_ms_hint: int


@dataclass(frozen=True, slots=True)
class ChunkPlan:
    chunks: tuple[PlannedChunk, ...]
    source_segments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AudioChunk:
    job_id: str
    chunk_index: int
    sample_rate_hz: int
    channels: int
    pcm_bytes: bytes
    duration_ms: int
    is_last: bool = False
    text_chunk_index: int | None = None
    text_chunk_count: int | None = None
    text_char_start: int | None = None
    text_char_end: int | None = None
    text_char_count: int | None = None


@dataclass(frozen=True, slots=True)
class VoiceCapabilities:
    supports_pitch: bool = False
    supports_streaming: bool = False
    supports_multi_speaker: bool = False


@dataclass(frozen=True, slots=True)
class VoiceDescriptor:
    id: str
    name: str
    engine: str
    language: str
    sample_rate_hz: int
    license: str
    source: str
    gender_style_hint: str | None = None
    quality_tier: str = "unknown"
    latency_tier: str = "unknown"
    tags: tuple[str, ...] = ()
    capabilities: VoiceCapabilities = field(default_factory=VoiceCapabilities)
    quality_score: float | None = None
    speed_score: float | None = None
    stability_score: float | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("voice id must not be empty")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")


@dataclass(frozen=True, slots=True)
class JobState:
    job_id: str
    status: JobStatus
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    error_message: str | None = None
