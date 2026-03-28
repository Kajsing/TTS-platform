from __future__ import annotations

import pytest
from tts_core import VoiceCapabilities, VoiceDescriptor, VoiceRegistry
from tts_core.registry import DuplicateVoiceError, VoiceNotFoundError


def build_voice(voice_id: str, *, language: str = "en", engine: str = "test") -> VoiceDescriptor:
    return VoiceDescriptor(
        id=voice_id,
        name=f"Voice {voice_id}",
        engine=engine,
        language=language,
        sample_rate_hz=24000,
        license="Apache-2.0",
        source=f"models/{voice_id}",
        tags=("test",),
        capabilities=VoiceCapabilities(supports_streaming=True),
    )


def test_registry_returns_sorted_voices() -> None:
    registry = VoiceRegistry(
        voices=[
            build_voice("voice-b"),
            build_voice("voice-a"),
        ],
        default_voice_id="voice-a",
    )

    assert [voice.id for voice in registry.list()] == ["voice-a", "voice-b"]
    assert registry.default_voice is not None
    assert registry.default_voice.id == "voice-a"


def test_registry_filters_by_language_and_engine() -> None:
    registry = VoiceRegistry(
        voices=[
            build_voice("voice-en"),
            build_voice("voice-da", language="da"),
            build_voice("voice-other-engine", engine="other"),
        ]
    )

    assert [voice.id for voice in registry.list(language="da")] == ["voice-da"]
    assert [voice.id for voice in registry.list(engine="other")] == ["voice-other-engine"]


def test_registry_rejects_duplicate_ids() -> None:
    with pytest.raises(DuplicateVoiceError):
        VoiceRegistry(voices=[build_voice("dup"), build_voice("dup")])


def test_registry_raises_for_unknown_voice() -> None:
    registry = VoiceRegistry()

    with pytest.raises(VoiceNotFoundError):
        registry.get("missing")
