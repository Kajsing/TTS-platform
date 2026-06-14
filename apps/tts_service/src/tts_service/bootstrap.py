from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tts_core.backends.base import BackendError
from tts_core.backends.sherpa_onnx import (
    SherpaOnnxBackend,
    SherpaOnnxBackendSettings,
    build_stub_voice,
)
from tts_core.manifest import VoiceManifestBundle, load_voice_manifest_bundle
from tts_core.registry import VoiceRegistry
from tts_core.text import ChunkPlanner, SentenceSegmenter, TextNormalizer, TextPipeline

from .auth import AuthState, initialize_auth
from .config import AppConfig
from .jobs import InMemoryJobManager
from .observability import ObservabilityState, configure_structured_logging
from .security import OriginPolicy, RateLimiter
from .streaming import StreamingMetrics


@dataclass(slots=True)
class ApplicationState:
    config: AppConfig
    voice_registry: VoiceRegistry
    backend: SherpaOnnxBackend
    text_pipeline: TextPipeline
    chunk_planner: ChunkPlanner
    auth: AuthState
    origin_policy: OriginPolicy
    rate_limiter: RateLimiter
    job_manager: InMemoryJobManager
    streaming_metrics: StreamingMetrics
    observability: ObservabilityState
    started_at: datetime
    backend_ready: bool
    default_voice_loaded: bool
    startup_error: str | None = None


def build_application_state(
    config: AppConfig,
    *,
    repo_root: Path | None = None,
) -> ApplicationState:
    base_path = repo_root or Path.cwd()
    auth_state = initialize_auth(config.auth, repo_root=base_path)
    manifest_path = base_path / "models" / "MANIFEST.json"
    manifest_bundle = (
        load_voice_manifest_bundle(manifest_path)
        if manifest_path.exists()
        else VoiceManifestBundle(voices=(), backend_configs={})
    )
    manifest_voices = list(manifest_bundle.voices)
    backend_voices = (
        tuple(manifest_bundle.voices) if manifest_bundle.voices else (build_stub_voice(),)
    )
    backend = SherpaOnnxBackend(
        models_root=base_path / "models" / "voices",
        voices=backend_voices,
        settings=SherpaOnnxBackendSettings(
            runtime_mode=config.backend.mode,
            provider=config.backend.provider,
            num_threads=config.backend.num_threads,
            debug=config.backend.debug,
            max_num_sentences=config.backend.max_num_sentences,
        ),
        voice_runtime_configs=manifest_bundle.backend_configs,
    )
    registry = VoiceRegistry(
        voices=manifest_voices or backend.list_voices(),
        default_voice_id=config.tts.default_voice,
    )
    text_pipeline = TextPipeline(
        normalizer=TextNormalizer(),
        segmenter=SentenceSegmenter(),
    )
    chunk_planner = ChunkPlanner()
    origin_policy = OriginPolicy(allowed_origins=config.security.allowed_origins)
    rate_limiter = RateLimiter(requests_per_minute=config.limits.requests_per_minute)
    observability = ObservabilityState(
        enabled=config.metrics.enabled,
        logger=configure_structured_logging(config.server.log_level),
    )
    job_manager = InMemoryJobManager(
        max_workers=config.limits.max_concurrent_jobs,
        backend=backend,
        observability=observability,
        completed_job_ttl_seconds=config.limits.completed_job_ttl_seconds,
        max_stored_jobs=config.limits.max_stored_jobs,
        max_job_seconds=config.limits.max_job_seconds,
    )
    streaming_metrics = StreamingMetrics()
    backend_ready = True
    startup_error: str | None = None
    if config.tts.warmup_on_start:
        try:
            backend.warmup(config.tts.default_voice)
        except BackendError as exc:
            backend_ready = False
            startup_error = str(exc)
    return ApplicationState(
        config=config,
        voice_registry=registry,
        backend=backend,
        text_pipeline=text_pipeline,
        chunk_planner=chunk_planner,
        auth=auth_state,
        origin_policy=origin_policy,
        rate_limiter=rate_limiter,
        job_manager=job_manager,
        streaming_metrics=streaming_metrics,
        observability=observability,
        started_at=datetime.now(timezone.utc),
        backend_ready=backend_ready,
        default_voice_loaded=registry.default_voice is not None,
        startup_error=startup_error,
    )
