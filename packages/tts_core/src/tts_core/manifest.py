from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import VoiceCapabilities, VoiceDescriptor


class VoiceManifestError(ValueError):
    """Raised when a voice manifest cannot be parsed into valid descriptors."""


@dataclass(frozen=True, slots=True)
class VoiceManifestBundle:
    voices: tuple[VoiceDescriptor, ...]
    backend_configs: dict[str, dict[str, Any]]


def load_voice_manifest(path: str | Path) -> list[VoiceDescriptor]:
    return list(load_voice_manifest_bundle(path).voices)


def load_voice_manifest_bundle(path: str | Path) -> VoiceManifestBundle:
    manifest_path = Path(path)
    with manifest_path.open("r", encoding="utf-8") as manifest_file:
        payload = json.load(manifest_file)

    if not isinstance(payload, dict):
        raise VoiceManifestError("Voice manifest root must be an object.")

    version = payload.get("version")
    if version != 1:
        raise VoiceManifestError(f"Unsupported voice manifest version: {version!r}")

    raw_voices = payload.get("voices", [])
    if not isinstance(raw_voices, list):
        raise VoiceManifestError("Voice manifest 'voices' field must be a list.")

    voices: list[VoiceDescriptor] = []
    backend_configs: dict[str, dict[str, Any]] = {}
    for index, raw_voice in enumerate(raw_voices):
        voice, backend_config = _voice_from_mapping(index, raw_voice)
        voices.append(voice)
        if backend_config is not None:
            backend_configs[voice.id] = backend_config

    return VoiceManifestBundle(
        voices=tuple(voices),
        backend_configs=backend_configs,
    )


def _voice_from_mapping(
    index: int,
    raw_voice: Any,
) -> tuple[VoiceDescriptor, dict[str, Any] | None]:
    if not isinstance(raw_voice, dict):
        raise VoiceManifestError(f"Voice entry at index {index} must be an object.")

    capabilities = raw_voice.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise VoiceManifestError(
            f"Voice entry at index {index} has invalid 'capabilities' field."
        )
    backend = raw_voice.get("backend")
    if backend is not None and not isinstance(backend, dict):
        raise VoiceManifestError(f"Voice entry at index {index} has invalid 'backend' field.")

    try:
        descriptor = VoiceDescriptor(
            id=str(raw_voice["id"]),
            name=str(raw_voice["name"]),
            engine=str(raw_voice["engine"]),
            language=str(raw_voice["language"]),
            sample_rate_hz=int(raw_voice["sample_rate_hz"]),
            license=str(raw_voice["license"]),
            source=str(raw_voice["source"]),
            gender_style_hint=_optional_string(raw_voice.get("gender_style_hint")),
            quality_tier=str(raw_voice.get("quality_tier", "unknown")),
            latency_tier=str(raw_voice.get("latency_tier", "unknown")),
            tags=tuple(_string_list(raw_voice.get("tags", []), field_name="tags", index=index)),
            capabilities=VoiceCapabilities(
                supports_pitch=bool(capabilities.get("supports_pitch", False)),
                supports_streaming=bool(capabilities.get("supports_streaming", False)),
                supports_multi_speaker=bool(capabilities.get("supports_multi_speaker", False)),
            ),
            quality_score=_optional_float(raw_voice.get("quality_score")),
            speed_score=_optional_float(raw_voice.get("speed_score")),
            stability_score=_optional_float(raw_voice.get("stability_score")),
            )
    except KeyError as exc:
        raise VoiceManifestError(
            f"Voice entry at index {index} is missing required field: {exc.args[0]}"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise VoiceManifestError(f"Voice entry at index {index} is invalid: {exc}") from exc

    return descriptor, dict(backend) if backend is not None else None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _string_list(value: Any, *, field_name: str, index: int) -> list[str]:
    if not isinstance(value, list):
        raise VoiceManifestError(
            f"Voice entry at index {index} has invalid '{field_name}' field."
        )
    return [str(item) for item in value]
