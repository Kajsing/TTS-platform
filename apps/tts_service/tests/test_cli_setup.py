from __future__ import annotations

import json
from pathlib import Path

import pytest
from tts_service import cli
from tts_service.config import load_config


def _write_setup_config(path: Path, *, default_voice: str = "voice-a") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "[server]",
                'host = "127.0.0.1"',
                "port = 7777",
                "",
                "[auth]",
                "enabled = true",
                'token_file = "./config/token.txt"',
                "",
                "[tts]",
                f'default_voice = "{default_voice}"',
                "max_chars_per_request = 4000",
                "max_chars_per_stream = 48000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_manifest(path: Path, *, voice_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "voices": [{"id": voice_id, "name": voice_id} for voice_id in voice_ids],
            }
        ),
        encoding="utf-8",
    )


def test_setup_local_creates_config_and_token(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    example_config_path = tmp_path / "config" / "config.example.toml"
    config_path = tmp_path / "config" / "config.toml"
    manifest_path = tmp_path / "models" / "MANIFEST.json"
    _write_setup_config(example_config_path, default_voice="voice-a")
    _write_manifest(manifest_path, voice_ids=["voice-a"])

    cli.main(
        [
            "setup-local",
            "--repo-root",
            str(tmp_path),
            "--config-path",
            str(config_path),
            "--example-config-path",
            str(example_config_path),
            "--manifest-path",
            str(manifest_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["config_created"] is True
    assert payload["auth_enabled"] is True
    assert payload["token_created"] is True
    written_config = Path(payload["config_path"]).read_text(encoding="utf-8")
    example_config = example_config_path.read_text(encoding="utf-8")
    assert written_config == example_config
    assert Path(payload["token_file"]).read_text(encoding="utf-8").strip()
    assert payload["service"]["base_url"] == "http://127.0.0.1:7777"
    assert payload["manifest"]["default_voice_in_manifest"] is True
    assert payload["next_steps"] == [
        "tts extension-allow-origin <chrome-extension-origin>",
        "tts model-check",
        "tts serve",
        "tts health",
        "tts list-voices",
        "read config/token.txt when a protected client needs the bearer token",
    ]


def test_setup_local_preserves_existing_config_and_token(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config" / "config.toml"
    token_path = tmp_path / "config" / "token.txt"
    manifest_path = tmp_path / "models" / "MANIFEST.json"
    _write_setup_config(config_path, default_voice="voice-a")
    token_path.write_text("existing-token\n", encoding="utf-8")

    cli.main(
        [
            "setup-local",
            "--repo-root",
            str(tmp_path),
            "--config-path",
            str(config_path),
            "--example-config-path",
            str(tmp_path / "config" / "missing-example.toml"),
            "--manifest-path",
            str(manifest_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["config_created"] is False
    assert payload["token_created"] is False
    assert token_path.read_text(encoding="utf-8") == "existing-token\n"
    assert payload["manifest"] == {
        "path": str(manifest_path),
        "exists": False,
        "voice_count": 0,
        "default_voice_in_manifest": False,
    }
    assert payload["next_steps"][:3] == [
        "tts model-install <model-id> --catalog <catalog> --activate",
        "tts extension-allow-origin <chrome-extension-origin>",
        "tts model-check",
    ]


def test_extension_allow_origin_adds_chrome_extension_origin(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config" / "config.toml"
    _write_setup_config(config_path, default_voice="voice-a")

    cli.main(
        [
            "extension-allow-origin",
            " chrome-extension://abcdefghijklmnopabcdefghijklmnop/ ",
            "--repo-root",
            str(tmp_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["added"] is True
    assert payload["origin"] == "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    assert payload["allowed_origins"] == [
        "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    ]
    config = load_config(config_path, env={})
    assert config.security.allowed_origins == (
        "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
    )


def test_extension_allow_origin_preserves_existing_origins_and_is_idempotent(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config" / "config.toml"
    _write_setup_config(config_path, default_voice="voice-a")
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[security]\n"
        + 'allowed_origins = ["chrome-extension://existingexistingexistingexis"]\n',
        encoding="utf-8",
    )

    added = cli._allow_extension_origin(
        repo_root=tmp_path,
        config_path=Path("config/config.toml"),
        origin="chrome-extension://abcdefghijklmnopabcdefghijklmnop",
    )
    duplicate = cli._allow_extension_origin(
        repo_root=tmp_path,
        config_path=Path("config/config.toml"),
        origin="chrome-extension://abcdefghijklmnopabcdefghijklmnop",
    )

    assert added["added"] is True
    assert duplicate["added"] is False
    config = load_config(config_path, env={})
    assert config.security.allowed_origins == (
        "chrome-extension://existingexistingexistingexis",
        "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
    )


def test_extension_allow_origin_rejects_non_extension_origin(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "config.toml"
    _write_setup_config(config_path, default_voice="voice-a")

    with pytest.raises(SystemExit, match="chrome-extension://"):
        cli._allow_extension_origin(
            repo_root=tmp_path,
            config_path=Path("config/config.toml"),
            origin="http://localhost:7777",
        )


def test_setup_local_requires_example_config_when_config_is_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="Example config does not exist"):
        cli._setup_local(
            repo_root=tmp_path,
            config_path=tmp_path / "config" / "config.toml",
            example_config_path=tmp_path / "config" / "missing-example.toml",
            manifest_path=tmp_path / "models" / "MANIFEST.json",
        )
