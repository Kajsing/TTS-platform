from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


ENV_PREFIX = "TTS_PLATFORM__"
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 7777
DEFAULT_LOG_LEVEL = "info"
DEFAULT_TOKEN_FILE = "./config/token.txt"
DEFAULT_VOICE_ID = "sherpa-en-debug"
DEFAULT_MAX_CHARS_PER_REQUEST = 4000
DEFAULT_MAX_CHARS_PER_STREAM = 48000
DEFAULT_WARMUP_ON_START = True
DEFAULT_STREAMING_ENABLED = True
DEFAULT_AUDIO_FRAME_MS = 40
DEFAULT_PREBUFFER_MS = 200
DEFAULT_METRICS_ENABLED = True
DEFAULT_MAX_CONCURRENT_JOBS = 2
DEFAULT_MAX_JOB_SECONDS = 300
DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = ()
DEFAULT_REQUESTS_PER_MINUTE = 30
DEFAULT_COMPLETED_JOB_TTL_SECONDS = 300
DEFAULT_MAX_STORED_JOBS = 128
DEFAULT_BACKEND_MODE = "auto"
DEFAULT_BACKEND_PROVIDER = "cpu"
DEFAULT_BACKEND_NUM_THREADS = 1
DEFAULT_BACKEND_DEBUG = False
DEFAULT_BACKEND_MAX_NUM_SENTENCES = 1


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str = DEFAULT_SERVER_HOST
    port: int = DEFAULT_SERVER_PORT
    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ServerConfig":
        config = cls(
            host=str(data.get("host", DEFAULT_SERVER_HOST)),
            port=int(data.get("port", DEFAULT_SERVER_PORT)),
            log_level=str(data.get("log_level", DEFAULT_LOG_LEVEL)),
        )
        if not config.host:
            raise ValueError("server.host must not be empty")
        if config.port <= 0:
            raise ValueError("server.port must be positive")
        return config


@dataclass(frozen=True, slots=True)
class AuthConfig:
    enabled: bool = True
    token_file: str = DEFAULT_TOKEN_FILE

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "AuthConfig":
        config = cls(
            enabled=bool(data.get("enabled", cls.enabled)),
            token_file=str(data.get("token_file", DEFAULT_TOKEN_FILE)),
        )
        if not config.token_file:
            raise ValueError("auth.token_file must not be empty")
        return config


@dataclass(frozen=True, slots=True)
class TTSConfig:
    default_voice: str = DEFAULT_VOICE_ID
    max_chars_per_request: int = DEFAULT_MAX_CHARS_PER_REQUEST
    max_chars_per_stream: int = DEFAULT_MAX_CHARS_PER_STREAM
    warmup_on_start: bool = DEFAULT_WARMUP_ON_START

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TTSConfig":
        config = cls(
            default_voice=str(data.get("default_voice", DEFAULT_VOICE_ID)),
            max_chars_per_request=int(
                data.get("max_chars_per_request", DEFAULT_MAX_CHARS_PER_REQUEST)
            ),
            max_chars_per_stream=int(
                data.get("max_chars_per_stream", DEFAULT_MAX_CHARS_PER_STREAM)
            ),
            warmup_on_start=bool(data.get("warmup_on_start", DEFAULT_WARMUP_ON_START)),
        )
        if not config.default_voice:
            raise ValueError("tts.default_voice must not be empty")
        if config.max_chars_per_request <= 0:
            raise ValueError("tts.max_chars_per_request must be positive")
        if config.max_chars_per_stream < config.max_chars_per_request:
            raise ValueError("tts.max_chars_per_stream must be at least max_chars_per_request")
        return config


@dataclass(frozen=True, slots=True)
class StreamingConfig:
    enabled: bool = DEFAULT_STREAMING_ENABLED
    audio_frame_ms: int = DEFAULT_AUDIO_FRAME_MS
    prebuffer_ms: int = DEFAULT_PREBUFFER_MS

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "StreamingConfig":
        config = cls(
            enabled=bool(data.get("enabled", DEFAULT_STREAMING_ENABLED)),
            audio_frame_ms=int(data.get("audio_frame_ms", DEFAULT_AUDIO_FRAME_MS)),
            prebuffer_ms=int(data.get("prebuffer_ms", DEFAULT_PREBUFFER_MS)),
        )
        if config.audio_frame_ms <= 0:
            raise ValueError("streaming.audio_frame_ms must be positive")
        if config.prebuffer_ms <= 0:
            raise ValueError("streaming.prebuffer_ms must be positive")
        return config


@dataclass(frozen=True, slots=True)
class MetricsConfig:
    enabled: bool = DEFAULT_METRICS_ENABLED

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "MetricsConfig":
        return cls(enabled=bool(data.get("enabled", DEFAULT_METRICS_ENABLED)))


@dataclass(frozen=True, slots=True)
class SecurityConfig:
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "SecurityConfig":
        raw_origins = data.get("allowed_origins", list(DEFAULT_ALLOWED_ORIGINS))
        if not isinstance(raw_origins, list):
            raise ValueError("security.allowed_origins must be a list")
        cleaned_origins = tuple(
            normalized
            for origin in raw_origins
            if (normalized := _normalize_allowed_origin(origin)) is not None
        )
        return cls(
            allowed_origins=cleaned_origins,
        )


@dataclass(frozen=True, slots=True)
class LimitsConfig:
    max_concurrent_jobs: int = DEFAULT_MAX_CONCURRENT_JOBS
    max_job_seconds: int = DEFAULT_MAX_JOB_SECONDS
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE
    completed_job_ttl_seconds: int = DEFAULT_COMPLETED_JOB_TTL_SECONDS
    max_stored_jobs: int = DEFAULT_MAX_STORED_JOBS

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "LimitsConfig":
        config = cls(
            max_concurrent_jobs=int(data.get("max_concurrent_jobs", DEFAULT_MAX_CONCURRENT_JOBS)),
            max_job_seconds=int(data.get("max_job_seconds", DEFAULT_MAX_JOB_SECONDS)),
            requests_per_minute=int(data.get("requests_per_minute", DEFAULT_REQUESTS_PER_MINUTE)),
            completed_job_ttl_seconds=int(
                data.get("completed_job_ttl_seconds", DEFAULT_COMPLETED_JOB_TTL_SECONDS)
            ),
            max_stored_jobs=int(data.get("max_stored_jobs", DEFAULT_MAX_STORED_JOBS)),
        )
        if config.max_concurrent_jobs <= 0:
            raise ValueError("limits.max_concurrent_jobs must be positive")
        if config.max_job_seconds <= 0:
            raise ValueError("limits.max_job_seconds must be positive")
        if config.requests_per_minute <= 0:
            raise ValueError("limits.requests_per_minute must be positive")
        if config.completed_job_ttl_seconds <= 0:
            raise ValueError("limits.completed_job_ttl_seconds must be positive")
        if config.max_stored_jobs <= 0:
            raise ValueError("limits.max_stored_jobs must be positive")
        return config


@dataclass(frozen=True, slots=True)
class BackendConfig:
    mode: str = DEFAULT_BACKEND_MODE
    provider: str = DEFAULT_BACKEND_PROVIDER
    num_threads: int = DEFAULT_BACKEND_NUM_THREADS
    debug: bool = DEFAULT_BACKEND_DEBUG
    max_num_sentences: int = DEFAULT_BACKEND_MAX_NUM_SENTENCES

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "BackendConfig":
        config = cls(
            mode=str(data.get("mode", DEFAULT_BACKEND_MODE)).lower(),
            provider=str(data.get("provider", DEFAULT_BACKEND_PROVIDER)).lower(),
            num_threads=int(data.get("num_threads", DEFAULT_BACKEND_NUM_THREADS)),
            debug=bool(data.get("debug", DEFAULT_BACKEND_DEBUG)),
            max_num_sentences=int(
                data.get("max_num_sentences", DEFAULT_BACKEND_MAX_NUM_SENTENCES)
            ),
        )
        if config.mode not in {"auto", "stub", "real"}:
            raise ValueError("backend.mode must be one of: auto, stub, real")
        if config.provider not in {"cpu", "cuda", "coreml"}:
            raise ValueError("backend.provider must be one of: cpu, cuda, coreml")
        if config.num_threads <= 0:
            raise ValueError("backend.num_threads must be positive")
        if config.max_num_sentences == 0 or config.max_num_sentences < -1:
            raise ValueError("backend.max_num_sentences must be positive or -1")
        return config


@dataclass(frozen=True, slots=True)
class AppConfig:
    server: ServerConfig = ServerConfig()
    auth: AuthConfig = AuthConfig()
    tts: TTSConfig = TTSConfig()
    streaming: StreamingConfig = StreamingConfig()
    metrics: MetricsConfig = MetricsConfig()
    security: SecurityConfig = SecurityConfig()
    limits: LimitsConfig = LimitsConfig()
    backend: BackendConfig = BackendConfig()

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "AppConfig":
        return cls(
            server=ServerConfig.from_mapping(_section(data, "server")),
            auth=AuthConfig.from_mapping(_section(data, "auth")),
            tts=TTSConfig.from_mapping(_section(data, "tts")),
            streaming=StreamingConfig.from_mapping(_section(data, "streaming")),
            metrics=MetricsConfig.from_mapping(_section(data, "metrics")),
            security=SecurityConfig.from_mapping(_section(data, "security")),
            limits=LimitsConfig.from_mapping(_section(data, "limits")),
            backend=BackendConfig.from_mapping(_section(data, "backend")),
        )


def load_config(
    path: str | Path | None = None,
    *,
    env: dict[str, str] | None = None,
) -> AppConfig:
    raw_data: dict[str, Any] = {}
    if path is not None:
        config_path = Path(path)
        if config_path.exists():
            with config_path.open("rb") as config_file:
                raw_data = tomllib.load(config_file)

    merged = _deep_copy_mapping(raw_data)
    _apply_env_overrides(merged, env or dict(os.environ))
    return AppConfig.from_mapping(merged)


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    raw = data.get(name, {})
    if not isinstance(raw, dict):
        raise ValueError(f"{name} section must be a table")
    return raw


def _deep_copy_mapping(data: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            copied[key] = _deep_copy_mapping(value)
        else:
            copied[key] = value
    return copied


def _apply_env_overrides(data: dict[str, Any], env: dict[str, str]) -> None:
    for key, raw_value in env.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = key[len(ENV_PREFIX) :].lower().split("__")
        cursor = data
        for segment in path[:-1]:
            cursor = cursor.setdefault(segment, {})
            if not isinstance(cursor, dict):
                raise ValueError(f"Environment override path collides with scalar value: {key}")
        cursor[path[-1]] = _coerce_env_value(raw_value)


def _coerce_env_value(raw_value: str) -> Any:
    normalized = raw_value.strip()
    lowered = normalized.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered.isdigit() or (lowered.startswith("-") and lowered[1:].isdigit()):
        return int(lowered)
    try:
        return float(lowered)
    except ValueError:
        return normalized


def _normalize_allowed_origin(raw_origin: object) -> str | None:
    origin = str(raw_origin).strip()
    if not origin:
        return None
    origin = origin.rstrip("/")
    lowered = origin.lower()
    if lowered == "*":
        raise ValueError("security.allowed_origins must not include wildcard '*'")
    if lowered == "null":
        raise ValueError("security.allowed_origins must not include the null origin")

    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https", "chrome-extension"} or not parsed.netloc:
        raise ValueError(
            "security.allowed_origins entries must be explicit http, https, "
            "or chrome-extension origins"
        )
    if parsed.path or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("security.allowed_origins entries must not include paths")
    return origin
