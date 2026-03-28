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
        },
    )

    assert config.server.port == 8888
    assert config.streaming.enabled is False
    assert config.limits.max_concurrent_jobs == 5


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
