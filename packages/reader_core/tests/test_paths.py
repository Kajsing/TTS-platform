from __future__ import annotations

from pathlib import Path

import pytest
from reader_core import ReaderConfigurationError, resolve_reader_paths


def test_windows_default_paths_use_local_app_data_without_creating_directories(
    tmp_path: Path,
) -> None:
    local_app_data = tmp_path / "LocalAppData"

    paths = resolve_reader_paths(
        env={"LOCALAPPDATA": str(local_app_data)},
        platform_name="nt",
    )

    assert paths.home == (local_app_data / "TTSPlatform" / "Reader").resolve()
    assert paths.database == paths.home / "reader.db"
    assert paths.managed_files == paths.home / "library"
    assert not paths.home.exists()


def test_explicit_reader_home_supports_test_and_development_overrides(tmp_path: Path) -> None:
    paths = resolve_reader_paths(
        home_path=tmp_path / "reader-home",
        database_path="data/reader.sqlite3",
        managed_files_path="managed",
    )

    assert paths.database == paths.home / "data" / "reader.sqlite3"
    assert paths.managed_files == paths.home / "managed"


@pytest.mark.parametrize("value", ["../outside.db", "nested/../../outside.db"])
def test_relative_reader_paths_cannot_escape_home(tmp_path: Path, value: str) -> None:
    with pytest.raises(ReaderConfigurationError, match="must not escape"):
        resolve_reader_paths(home_path=tmp_path / "reader", database_path=value)


def test_windows_default_requires_local_app_data() -> None:
    with pytest.raises(ReaderConfigurationError, match="LOCALAPPDATA"):
        resolve_reader_paths(env={}, platform_name="nt")
