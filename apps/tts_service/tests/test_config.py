from __future__ import annotations

from pathlib import Path

import pytest
from tts_service.config import load_config


def test_load_config_reads_toml_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[server]",
                'host = "127.0.0.1"',
                "port = 9001",
                "",
                "[tts]",
                'default_voice = "voice-x"',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path, env={})

    assert config.server.port == 9001
    assert config.tts.default_voice == "voice-x"
    assert config.tts.max_chars_per_stream == 48000
    assert config.streaming.prebuffer_ms == 200


def test_load_config_applies_environment_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")

    config = load_config(
        config_path,
        env={
            "TTS_PLATFORM__SERVER__PORT": "8888",
            "TTS_PLATFORM__STREAMING__ENABLED": "false",
            "TTS_PLATFORM__LIMITS__MAX_CONCURRENT_JOBS": "5",
            "TTS_PLATFORM__BACKEND__MODE": "real",
            "TTS_PLATFORM__READER__ENABLED": "false",
            "TTS_PLATFORM__READER__DEFAULT_PAGE_SIZE": "75",
        },
    )

    assert config.server.port == 8888
    assert config.streaming.enabled is False
    assert config.limits.max_concurrent_jobs == 5
    assert config.backend.mode == "real"
    assert config.reader.enabled is False
    assert config.reader.default_page_size == 75


def test_load_config_rejects_invalid_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[limits]",
                "max_job_seconds = 0",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_config(config_path, env={})


def test_load_config_rejects_stream_limit_below_request_limit(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[tts]",
                "max_chars_per_request = 4000",
                "max_chars_per_stream = 2000",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_chars_per_stream"):
        load_config(config_path, env={})


def test_load_config_reads_stream_text_limit(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[tts]",
                "max_chars_per_request = 2000",
                "max_chars_per_stream = 16000",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path, env={})

    assert config.tts.max_chars_per_request == 2000
    assert config.tts.max_chars_per_stream == 16000


def test_load_config_reads_backend_section(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[backend]",
                'mode = "real"',
                'provider = "cpu"',
                "num_threads = 2",
                "debug = true",
                "max_num_sentences = 3",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path, env={})

    assert config.backend.mode == "real"
    assert config.backend.provider == "cpu"
    assert config.backend.num_threads == 2
    assert config.backend.debug is True
    assert config.backend.max_num_sentences == 3


def test_load_config_reads_reader_core_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[reader]",
                "enabled = true",
                'home_path = "D:/Portable/Reader"',
                'database_path = "data/library.db"',
                'managed_files_path = "documents"',
                "copy_imported_files = true",
                "default_page_size = 25",
                "max_page_size = 250",
                "max_blocks_per_stream_window = 32",
                "max_source_chars_per_stream_window = 16000",
                "max_edit_history_operations = 200",
                "max_edit_history_bytes = 2097152",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path, env={})

    assert config.reader.enabled is True
    assert config.reader.home_path == "D:/Portable/Reader"
    assert config.reader.database_path == "data/library.db"
    assert config.reader.managed_files_path == "documents"
    assert config.reader.copy_imported_files is True
    assert config.reader.default_page_size == 25
    assert config.reader.max_page_size == 250
    assert config.reader.max_edit_history_operations == 200
    assert config.reader.max_edit_history_bytes == 2_097_152


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("database_path", '""', "database_path"),
        ("managed_files_path", '""', "managed_files_path"),
        ("default_page_size", "0", "default_page_size"),
        ("max_edit_history_operations", "0", "max_edit_history_operations"),
        ("max_edit_history_bytes", "-1", "max_edit_history_bytes"),
    ],
)
def test_load_config_rejects_invalid_reader_settings(
    tmp_path: Path,
    setting: str,
    value: str,
    message: str,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(f"[reader]\n{setting} = {value}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_config(config_path, env={})


def test_load_config_rejects_reader_default_page_above_maximum(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[reader]\ndefault_page_size = 501\nmax_page_size = 500\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must not exceed"):
        load_config(config_path, env={})


def test_load_config_normalizes_allowed_origins(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[security]",
                'allowed_origins = [" chrome-extension://abc123/ ", "http://localhost:7777/"]',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path, env={})

    assert config.security.allowed_origins == (
        "chrome-extension://abc123",
        "http://localhost:7777",
    )


@pytest.mark.parametrize(
    ("origin", "message"),
    [
        ('"*"', "wildcard"),
        ('"null"', "null origin"),
        ('"file://local-file"', "explicit http, https, or chrome-extension origins"),
        ('"http://localhost:7777/path"', "must not include paths"),
    ],
)
def test_load_config_rejects_unsafe_allowed_origins(
    tmp_path: Path,
    origin: str,
    message: str,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[security]",
                f"allowed_origins = [{origin}]",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_config(config_path, env={})
