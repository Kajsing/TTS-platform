from __future__ import annotations

from pathlib import Path

import pytest
from tts_service import cli


def _write_serve_config(path: Path, *, host: str = "127.0.0.1", port: int = 7788) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "[server]",
                f'host = "{host}"',
                f"port = {port}",
                'log_level = "warning"',
                "",
                "[auth]",
                "enabled = true",
                'token_file = "./config/token.txt"',
                "",
                "[tts]",
                'default_voice = "sherpa-en-debug"',
                "max_chars_per_request = 4000",
                "max_chars_per_stream = 48000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_serve_local_uses_configured_host_port_and_repo_root(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "config.toml"
    _write_serve_config(config_path, host="127.0.0.1", port=7788)
    captured: dict[str, object] = {}

    def fake_uvicorn_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured["kwargs"] = kwargs

    cli._serve_local(
        repo_root=tmp_path,
        config_path=config_path,
        host=None,
        port=None,
        allow_non_local_host=False,
        uvicorn_run=fake_uvicorn_run,
    )

    assert captured["kwargs"] == {
        "host": "127.0.0.1",
        "port": 7788,
        "log_level": "warning",
        "reload": False,
    }
    app = captured["app"]
    assert app.state.container.config.server.port == 7788
    assert app.state.container.auth.token_file == tmp_path / "config" / "token.txt"


def test_serve_local_allows_explicit_host_and_port_override(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "config.toml"
    _write_serve_config(config_path, host="127.0.0.1", port=7788)
    captured: dict[str, object] = {}

    cli._serve_local(
        repo_root=tmp_path,
        config_path=config_path,
        host="localhost",
        port=7799,
        allow_non_local_host=False,
        uvicorn_run=lambda app, **kwargs: captured.update(kwargs),
    )

    assert captured["host"] == "localhost"
    assert captured["port"] == 7799


def test_serve_local_rejects_missing_config_with_setup_guidance(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="Run 'tts setup-local' first"):
        cli._serve_local(
            repo_root=tmp_path,
            config_path=tmp_path / "config" / "config.toml",
            host=None,
            port=None,
            allow_non_local_host=False,
            uvicorn_run=lambda *args, **kwargs: None,
        )


def test_serve_local_rejects_non_loopback_host_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "config.toml"
    _write_serve_config(config_path, host="0.0.0.0", port=7788)

    with pytest.raises(SystemExit, match="Refusing to bind outside localhost"):
        cli._serve_local(
            repo_root=tmp_path,
            config_path=config_path,
            host=None,
            port=None,
            allow_non_local_host=False,
            uvicorn_run=lambda *args, **kwargs: None,
        )


def test_serve_local_can_allow_non_loopback_host_explicitly(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "config.toml"
    _write_serve_config(config_path, host="0.0.0.0", port=7788)
    captured: dict[str, object] = {}

    cli._serve_local(
        repo_root=tmp_path,
        config_path=config_path,
        host=None,
        port=None,
        allow_non_local_host=True,
        uvicorn_run=lambda app, **kwargs: captured.update(kwargs),
    )

    assert captured["host"] == "0.0.0.0"
