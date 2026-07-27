from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import ReaderConfigurationError


@dataclass(frozen=True, slots=True)
class ReaderPaths:
    home: Path
    database: Path
    managed_files: Path


def resolve_reader_paths(
    *,
    home_path: str | Path = "",
    database_path: str | Path = "reader.db",
    managed_files_path: str | Path = "library",
    env: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> ReaderPaths:
    environment = env if env is not None else os.environ
    platform = platform_name or os.name
    home = (
        Path(home_path).expanduser()
        if str(home_path).strip()
        else _default_home(
            environment,
            platform,
        )
    )
    home = home.resolve()
    database = _resolve_under_home(home, database_path, "database_path")
    managed_files = _resolve_under_home(home, managed_files_path, "managed_files_path")
    if database == managed_files:
        raise ReaderConfigurationError("reader database and managed-files paths must differ")
    return ReaderPaths(home=home, database=database, managed_files=managed_files)


def _default_home(env: Mapping[str, str], platform: str) -> Path:
    if platform == "nt":
        raw = env.get("LOCALAPPDATA", "").strip()
        if not raw:
            raise ReaderConfigurationError(
                "LOCALAPPDATA is required when reader.home_path is empty on Windows"
            )
        return Path(raw) / "TTSPlatform" / "Reader"

    xdg_data_home = env.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home) / "tts-platform" / "reader"
    return Path.home() / ".local" / "share" / "tts-platform" / "reader"


def _resolve_under_home(home: Path, value: str | Path, label: str) -> Path:
    if not str(value).strip():
        raise ReaderConfigurationError(f"reader.{label} must not be empty")
    raw = Path(value).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (home / raw).resolve()
    if not raw.is_absolute() and not resolved.is_relative_to(home):
        raise ReaderConfigurationError(f"reader.{label} must not escape reader.home_path")
    return resolved
