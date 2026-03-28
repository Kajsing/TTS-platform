from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tts_core.backends.sherpa_onnx import SherpaOnnxBackend
from tts_core.manifest import load_voice_manifest
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
    manifest_path = base_path / "models" / "MANIFEST.json"
    manifest_voices = load_voice_manifest(manifest_path) if manifest_path.exists() else []
    registry = VoiceRegistry(
        voices=manifest_voices or backend.list_voices(),
        default_voice_id=config.tts.default_voice,
    )
    return ApplicationState(config=config, voice_registry=registry, backend=backend)
