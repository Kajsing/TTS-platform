from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_security_defaults.py"


def test_security_defaults_check_passes_repo_defaults() -> None:
    check_module = _load_security_defaults_module()

    summary = check_module.check_security_defaults(
        config_path=REPO_ROOT / "config" / "config.example.toml",
        gitignore_path=REPO_ROOT / ".gitignore",
    )

    assert summary["checked_items"] == [
        "loopback_host",
        "token_auth_enabled",
        "repo_local_token_file",
        "empty_allowed_origins",
        "rate_limit_enabled",
        "metrics_enabled",
        "stream_limit_supports_long_pages",
        "local_cpu_backend_default",
        "local_secret_and_model_ignores",
    ]


def test_security_defaults_check_reports_unsafe_defaults(tmp_path: Path) -> None:
    check_module = _load_security_defaults_module()
    config_path = tmp_path / "config.example.toml"
    gitignore_path = tmp_path / ".gitignore"
    config_path.write_text(
        "\n".join(
            [
                "[server]",
                'host = "0.0.0.0"',
                "",
                "[auth]",
                "enabled = false",
                'token_file = "./config/plain-token.txt"',
                "",
                "[security]",
                'allowed_origins = ["chrome-extension://abc123"]',
                "",
                "[metrics]",
                "enabled = false",
                "",
                "[backend]",
                'mode = "real"',
                'provider = "cuda"',
                "debug = true",
            ]
        ),
        encoding="utf-8",
    )
    gitignore_path.write_text("config/config.toml\n", encoding="utf-8")

    with pytest.raises(check_module.SecurityDefaultsError) as exc_info:
        check_module.check_security_defaults(
            config_path=config_path,
            gitignore_path=gitignore_path,
        )

    message = str(exc_info.value)
    assert "server.host must default to '127.0.0.1'" in message
    assert "auth.enabled must default to true" in message
    assert "auth.token_file must default to './config/token.txt'" in message
    assert "security.allowed_origins must default to an empty fail-closed allow-list" in message
    assert "metrics.enabled must default to true" in message
    assert "backend.mode must default to 'auto'" in message
    assert "backend.provider must default to 'cpu'" in message
    assert "backend.debug must default to false" in message
    assert ".gitignore must include 'config/token.txt'" in message
    assert ".gitignore must include 'models/voices/'" in message


def _load_security_defaults_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_security_defaults",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
