from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tts_core.backends.base import BackendError
from tts_core.backends.sherpa_onnx import SherpaOnnxBackend, build_stub_voice
from tts_core.manifest import load_voice_manifest
from tts_core.registry import VoiceRegistry
from tts_core.text import SentenceSegmenter, TextNormalizer, TextPipeline

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
    origin_policy = OriginPolicy(allowed_origins=config.security.allowed_origins)
    rate_limiter = RateLimiter(requests_per_minute=config.limits.requests_per_minute)
    job_manager = InMemoryJobManager(
        max_workers=config.limits.max_concurrent_jobs,
        backend=backend,
        completed_job_ttl_seconds=config.limits.completed_job_ttl_seconds,
        max_stored_jobs=config.limits.max_stored_jobs,
    )
    streaming_metrics = StreamingMetrics()
    observability = ObservabilityState(
        enabled=config.metrics.enabled,
        logger=configure_structured_logging(config.server.log_level),
    )
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
