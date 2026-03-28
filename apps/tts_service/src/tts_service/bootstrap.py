from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tts_core.backends.sherpa_onnx import SherpaOnnxBackend, build_stub_voice
from tts_core.manifest import load_voice_manifest
from tts_core.registry import VoiceRegistry
from tts_core.text import SentenceSegmenter, TextNormalizer, TextPipeline

from .config import AppConfig


@dataclass(slots=True)
class ApplicationState:
    config: AppConfig
    voice_registry: VoiceRegistry
    backend: SherpaOnnxBackend
    text_pipeline: TextPipeline
    started_at: datetime


def build_application_state(
    config: AppConfig,
    *,
    repo_root: Path | None = None,
) -> ApplicationState:
    base_path = repo_root or Path.cwd()
    manifest_path = base_path / "models" / "MANIFEST.json"
    manifest_voices = load_voice_manifest(manifest_path) if manifest_path.exists() else []
    backend_voices = tuple(manifest_voices) if manifest_voices else (build_stub_voice(),)
    backend = SherpaOnnxBackend(
        models_root=base_path / "models" / "voices",
        voices=backend_voices,
    )
    registry = VoiceRegistry(
        voices=manifest_voices or backend.list_voices(),
        default_voice_id=config.tts.default_voice,
    )
    text_pipeline = TextPipeline(
        normalizer=TextNormalizer(),
        segmenter=SentenceSegmenter(),
    )
    if config.tts.warmup_on_start:
        backend.warmup(config.tts.default_voice)
    return ApplicationState(
        config=config,
        voice_registry=registry,
        backend=backend,
        text_pipeline=text_pipeline,
        started_at=datetime.now(timezone.utc),
    )
