from __future__ import annotations

from pydantic import BaseModel, Field


class ProsodyPayload(BaseModel):
    rate: float = 1.0
    volume: float = 1.0
    pitch: int = 0
    pause_strategy: str = "auto"
    sentence_pause_ms: int = 120
    comma_pause_ms: int = 60
    emphasis: list[str] = Field(default_factory=list)


class SynthesisOptionsPayload(BaseModel):
    normalize_text: bool = True
    streaming_preferred: bool = False
    input_format: str = "plain_text"


class SynthesizeRequestPayload(BaseModel):
    text: str
    voice: str | None = None
    format: str = "wav"
    prosody: ProsodyPayload = Field(default_factory=ProsodyPayload)
    options: SynthesisOptionsPayload = Field(default_factory=SynthesisOptionsPayload)
    language_hint: str | None = None
