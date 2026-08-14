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
DEFAULT_BACKEND_NUM_THREADS = 4
DEFAULT_BACKEND_DEBUG = False
DEFAULT_BACKEND_MAX_NUM_SENTENCES = 1
DEFAULT_BACKEND_SILENCE_SCALE = 0.06
DEFAULT_READER_ENABLED = True
DEFAULT_READER_HOME_PATH = ""
DEFAULT_READER_DATABASE_PATH = "reader.db"
DEFAULT_READER_MANAGED_FILES_PATH = "library"
DEFAULT_READER_COPY_IMPORTED_FILES = False
DEFAULT_READER_PAGE_SIZE = 50
DEFAULT_READER_MAX_PAGE_SIZE = 500
DEFAULT_READER_MAX_BLOCKS_PER_STREAM_WINDOW = 64
DEFAULT_READER_MAX_SOURCE_CHARS_PER_STREAM_WINDOW = 32000
DEFAULT_READER_MAX_EDIT_HISTORY_OPERATIONS = 1000
DEFAULT_READER_MAX_EDIT_HISTORY_BYTES = 10_485_760
DEFAULT_READER_IMPORT_MAX_FILE_BYTES = 52_428_800
DEFAULT_READER_IMPORT_MAX_EXPANDED_ARCHIVE_BYTES = 209_715_200
DEFAULT_READER_IMPORT_MAX_ARCHIVE_MEMBERS = 10_000
DEFAULT_READER_IMPORT_MAX_DOCUMENT_CHARACTERS = 10_000_000
DEFAULT_READER_IMPORT_MAX_BLOCKS = 250_000
DEFAULT_READER_IMPORT_TIMEOUT_SECONDS = 60
DEFAULT_READER_RULES_ENABLED = True
DEFAULT_READER_RULE_REGEX_TIMEOUT_MS = 25
DEFAULT_READER_RULE_MAX_PATTERN_CHARS = 2_048
DEFAULT_READER_RULE_MAX_REPLACEMENT_CHARS = 4_096
DEFAULT_READER_RULE_MAX_TIME_PER_BLOCK_MS = 250
DEFAULT_READER_EXPORTS_ENABLED = True
DEFAULT_READER_EXPORT_OUTPUT_DIRECTORY = "./data/exports"
DEFAULT_READER_EXPORT_MAX_CONCURRENT = 1
DEFAULT_READER_EXPORT_FORMATS = ("wav", "mp3")
DEFAULT_READER_EXPORT_MP3_BITRATE_KBPS = 96


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
    silence_scale: float = DEFAULT_BACKEND_SILENCE_SCALE

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
            silence_scale=float(
                data.get("silence_scale", DEFAULT_BACKEND_SILENCE_SCALE)
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
        if not 0 <= config.silence_scale <= 2:
            raise ValueError("backend.silence_scale must be between 0 and 2")
        return config


@dataclass(frozen=True, slots=True)
class ReaderImportConfig:
    max_file_bytes: int = DEFAULT_READER_IMPORT_MAX_FILE_BYTES
    max_expanded_archive_bytes: int = DEFAULT_READER_IMPORT_MAX_EXPANDED_ARCHIVE_BYTES
    max_archive_members: int = DEFAULT_READER_IMPORT_MAX_ARCHIVE_MEMBERS
    max_document_characters: int = DEFAULT_READER_IMPORT_MAX_DOCUMENT_CHARACTERS
    max_blocks: int = DEFAULT_READER_IMPORT_MAX_BLOCKS
    timeout_seconds: int = DEFAULT_READER_IMPORT_TIMEOUT_SECONDS

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ReaderImportConfig":
        config = cls(
            max_file_bytes=int(
                data.get("max_file_bytes", DEFAULT_READER_IMPORT_MAX_FILE_BYTES)
            ),
            max_expanded_archive_bytes=int(
                data.get(
                    "max_expanded_archive_bytes",
                    DEFAULT_READER_IMPORT_MAX_EXPANDED_ARCHIVE_BYTES,
                )
            ),
            max_archive_members=int(
                data.get("max_archive_members", DEFAULT_READER_IMPORT_MAX_ARCHIVE_MEMBERS)
            ),
            max_document_characters=int(
                data.get(
                    "max_document_characters",
                    DEFAULT_READER_IMPORT_MAX_DOCUMENT_CHARACTERS,
                )
            ),
            max_blocks=int(data.get("max_blocks", DEFAULT_READER_IMPORT_MAX_BLOCKS)),
            timeout_seconds=int(
                data.get("timeout_seconds", DEFAULT_READER_IMPORT_TIMEOUT_SECONDS)
            ),
        )
        for name in (
            "max_file_bytes",
            "max_expanded_archive_bytes",
            "max_archive_members",
            "max_document_characters",
            "max_blocks",
            "timeout_seconds",
        ):
            if getattr(config, name) <= 0:
                raise ValueError(f"reader.imports.{name} must be positive")
        return config


@dataclass(frozen=True, slots=True)
class ReaderRuleConfig:
    enabled: bool = DEFAULT_READER_RULES_ENABLED
    default_regex_timeout_ms: int = DEFAULT_READER_RULE_REGEX_TIMEOUT_MS
    max_regex_pattern_chars: int = DEFAULT_READER_RULE_MAX_PATTERN_CHARS
    max_replacement_chars: int = DEFAULT_READER_RULE_MAX_REPLACEMENT_CHARS
    max_rule_time_per_block_ms: int = DEFAULT_READER_RULE_MAX_TIME_PER_BLOCK_MS

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ReaderRuleConfig":
        config = cls(
            enabled=bool(data.get("enabled", DEFAULT_READER_RULES_ENABLED)),
            default_regex_timeout_ms=int(
                data.get("default_regex_timeout_ms", DEFAULT_READER_RULE_REGEX_TIMEOUT_MS)
            ),
            max_regex_pattern_chars=int(
                data.get("max_regex_pattern_chars", DEFAULT_READER_RULE_MAX_PATTERN_CHARS)
            ),
            max_replacement_chars=int(
                data.get("max_replacement_chars", DEFAULT_READER_RULE_MAX_REPLACEMENT_CHARS)
            ),
            max_rule_time_per_block_ms=int(
                data.get(
                    "max_rule_time_per_block_ms",
                    DEFAULT_READER_RULE_MAX_TIME_PER_BLOCK_MS,
                )
            ),
        )
        for name in (
            "default_regex_timeout_ms",
            "max_regex_pattern_chars",
            "max_replacement_chars",
            "max_rule_time_per_block_ms",
        ):
            if getattr(config, name) <= 0:
                raise ValueError(f"reader.rules.{name} must be positive")
        return config


@dataclass(frozen=True, slots=True)
class ReaderExportConfig:
    enabled: bool = DEFAULT_READER_EXPORTS_ENABLED
    output_directory: str = DEFAULT_READER_EXPORT_OUTPUT_DIRECTORY
    max_concurrent_exports: int = DEFAULT_READER_EXPORT_MAX_CONCURRENT
    formats: tuple[str, ...] = DEFAULT_READER_EXPORT_FORMATS
    ffmpeg_path: str | None = None
    mp3_bitrate_kbps: int = DEFAULT_READER_EXPORT_MP3_BITRATE_KBPS

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ReaderExportConfig":
        raw_formats = data.get("formats", DEFAULT_READER_EXPORT_FORMATS)
        if not isinstance(raw_formats, (list, tuple)):
            raise ValueError("reader.exports.formats must be an array")
        formats = tuple(str(value).strip().lower() for value in raw_formats)
        raw_ffmpeg_path = str(data.get("ffmpeg_path", "")).strip()
        config = cls(
            enabled=bool(data.get("enabled", DEFAULT_READER_EXPORTS_ENABLED)),
            output_directory=str(
                data.get("output_directory", DEFAULT_READER_EXPORT_OUTPUT_DIRECTORY)
            ),
            max_concurrent_exports=int(
                data.get("max_concurrent_exports", DEFAULT_READER_EXPORT_MAX_CONCURRENT)
            ),
            formats=formats,
            ffmpeg_path=raw_ffmpeg_path or None,
            mp3_bitrate_kbps=int(
                data.get("mp3_bitrate_kbps", DEFAULT_READER_EXPORT_MP3_BITRATE_KBPS)
            ),
        )
        if not config.output_directory.strip():
            raise ValueError("reader.exports.output_directory must not be empty")
        output_path = Path(config.output_directory)
        if not output_path.is_absolute() and ".." in output_path.parts:
            raise ValueError(
                "reader.exports.output_directory must stay within Reader home when relative"
            )
        if config.max_concurrent_exports <= 0:
            raise ValueError("reader.exports.max_concurrent_exports must be positive")
        if (
            not config.formats
            or len(set(config.formats)) != len(config.formats)
            or not set(config.formats).issubset({"wav", "mp3"})
        ):
            raise ValueError(
                "reader.exports.formats must contain unique 'wav' and/or 'mp3' values"
            )
        if config.ffmpeg_path is not None and not Path(config.ffmpeg_path).is_absolute():
            raise ValueError("reader.exports.ffmpeg_path must be an absolute path")
        if not 32 <= config.mp3_bitrate_kbps <= 320:
            raise ValueError(
                "reader.exports.mp3_bitrate_kbps must be between 32 and 320"
            )
        return config


@dataclass(frozen=True, slots=True)
class ReaderConfig:
    enabled: bool = DEFAULT_READER_ENABLED
    home_path: str = DEFAULT_READER_HOME_PATH
    database_path: str = DEFAULT_READER_DATABASE_PATH
    managed_files_path: str = DEFAULT_READER_MANAGED_FILES_PATH
    copy_imported_files: bool = DEFAULT_READER_COPY_IMPORTED_FILES
    default_page_size: int = DEFAULT_READER_PAGE_SIZE
    max_page_size: int = DEFAULT_READER_MAX_PAGE_SIZE
    max_blocks_per_stream_window: int = DEFAULT_READER_MAX_BLOCKS_PER_STREAM_WINDOW
    max_source_chars_per_stream_window: int = DEFAULT_READER_MAX_SOURCE_CHARS_PER_STREAM_WINDOW
    max_edit_history_operations: int = DEFAULT_READER_MAX_EDIT_HISTORY_OPERATIONS
    max_edit_history_bytes: int = DEFAULT_READER_MAX_EDIT_HISTORY_BYTES
    imports: ReaderImportConfig = ReaderImportConfig()
    rules: ReaderRuleConfig = ReaderRuleConfig()
    exports: ReaderExportConfig = ReaderExportConfig()

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ReaderConfig":
        config = cls(
            enabled=bool(data.get("enabled", DEFAULT_READER_ENABLED)),
            home_path=str(data.get("home_path", DEFAULT_READER_HOME_PATH)),
            database_path=str(data.get("database_path", DEFAULT_READER_DATABASE_PATH)),
            managed_files_path=str(
                data.get("managed_files_path", DEFAULT_READER_MANAGED_FILES_PATH)
            ),
            copy_imported_files=bool(
                data.get("copy_imported_files", DEFAULT_READER_COPY_IMPORTED_FILES)
            ),
            default_page_size=int(data.get("default_page_size", DEFAULT_READER_PAGE_SIZE)),
            max_page_size=int(data.get("max_page_size", DEFAULT_READER_MAX_PAGE_SIZE)),
            max_blocks_per_stream_window=int(
                data.get(
                    "max_blocks_per_stream_window",
                    DEFAULT_READER_MAX_BLOCKS_PER_STREAM_WINDOW,
                )
            ),
            max_source_chars_per_stream_window=int(
                data.get(
                    "max_source_chars_per_stream_window",
                    DEFAULT_READER_MAX_SOURCE_CHARS_PER_STREAM_WINDOW,
                )
            ),
            max_edit_history_operations=int(
                data.get(
                    "max_edit_history_operations",
                    DEFAULT_READER_MAX_EDIT_HISTORY_OPERATIONS,
                )
            ),
            max_edit_history_bytes=int(
                data.get("max_edit_history_bytes", DEFAULT_READER_MAX_EDIT_HISTORY_BYTES)
            ),
            imports=ReaderImportConfig.from_mapping(_section(data, "imports")),
            rules=ReaderRuleConfig.from_mapping(_section(data, "rules")),
            exports=ReaderExportConfig.from_mapping(_section(data, "exports")),
        )
        if not config.database_path.strip():
            raise ValueError("reader.database_path must not be empty")
        if not config.managed_files_path.strip():
            raise ValueError("reader.managed_files_path must not be empty")
        positive_limits = {
            "default_page_size": config.default_page_size,
            "max_page_size": config.max_page_size,
            "max_blocks_per_stream_window": config.max_blocks_per_stream_window,
            "max_source_chars_per_stream_window": config.max_source_chars_per_stream_window,
            "max_edit_history_operations": config.max_edit_history_operations,
            "max_edit_history_bytes": config.max_edit_history_bytes,
        }
        for name, value in positive_limits.items():
            if value <= 0:
                raise ValueError(f"reader.{name} must be positive")
        if config.default_page_size > config.max_page_size:
            raise ValueError("reader.default_page_size must not exceed max_page_size")
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
    reader: ReaderConfig = ReaderConfig()

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
            reader=ReaderConfig.from_mapping(_section(data, "reader")),
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
