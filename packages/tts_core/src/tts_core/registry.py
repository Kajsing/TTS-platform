from __future__ import annotations

from collections.abc import Iterable

from .models import VoiceDescriptor


class VoiceRegistryError(Exception):
    """Base error for voice registry failures."""


class DuplicateVoiceError(VoiceRegistryError):
    """Raised when a voice id is registered more than once."""


class VoiceNotFoundError(VoiceRegistryError):
    """Raised when the requested voice id is unknown."""


class VoiceRegistry:
    def __init__(
        self,
        voices: Iterable[VoiceDescriptor] = (),
        default_voice_id: str | None = None,
    ) -> None:
        self._voices: dict[str, VoiceDescriptor] = {}
        self._default_voice_id = default_voice_id
        for voice in voices:
            self.register(voice)
        if self._default_voice_id is not None and self._default_voice_id not in self._voices:
            raise VoiceNotFoundError(f"Unknown default voice id: {self._default_voice_id}")

    def register(self, voice: VoiceDescriptor) -> None:
        if voice.id in self._voices:
            raise DuplicateVoiceError(f"Voice id is already registered: {voice.id}")
        self._voices[voice.id] = voice

    def list(
        self,
        *,
        language: str | None = None,
        engine: str | None = None,
    ) -> list[VoiceDescriptor]:
        voices = self._voices.values()
        if language is not None:
            voices = (voice for voice in voices if voice.language == language)
        if engine is not None:
            voices = (voice for voice in voices if voice.engine == engine)
        return sorted(voices, key=lambda voice: voice.id)

    def get(self, voice_id: str) -> VoiceDescriptor:
        try:
            return self._voices[voice_id]
        except KeyError as exc:
            raise VoiceNotFoundError(f"Unknown voice id: {voice_id}") from exc

    def has(self, voice_id: str) -> bool:
        return voice_id in self._voices

    @property
    def default_voice(self) -> VoiceDescriptor | None:
        if self._default_voice_id is None:
            return None
        return self.get(self._default_voice_id)
