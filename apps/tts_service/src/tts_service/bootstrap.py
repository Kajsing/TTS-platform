from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tts_core.backends.sherpa_onnx import SherpaOnnxBackend
from tts_core.registry import VoiceRegistry

from .config import AppConfig


@dataclass(slots=True)
class ApplicationState:
    config: AppConfig
    voice_registry: VoiceRegistry
    backend: SherpaOnnxBackend


def build_application_state(
    config: AppConfig,
    *,
    repo_root: Path | None = None,
) -> ApplicationState:
    base_path = repo_root or Path.cwd()
    backend = SherpaOnnxBackend(models_root=base_path / "models" / "voices")
    registry = VoiceRegistry(
        voices=backend.list_voices(),
        default_voice_id=config.tts.default_voice,
    )
    return ApplicationState(config=config, voice_registry=registry, backend=backend)
