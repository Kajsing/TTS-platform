from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_reader_secure_transport.py"


def test_secure_transport_spike_layout_is_isolated_and_loopback_only(tmp_path: Path) -> None:
    check_module = _load_check_module()

    layout = check_module._write_spike_layout(tmp_path)

    config = layout["config_path"].read_text(encoding="utf-8")
    assert 'host = "127.0.0.1"' in config
    assert "0.0.0.0" not in config
    assert "allowed_origins = []" in config
    assert json.dumps(str(layout["reader_home"])) in config
    assert layout["token_path"].read_text(encoding="utf-8").strip()
    manifest = json.loads(
        (layout["repo_root"] / "models" / "MANIFEST.json").read_text(encoding="utf-8")
    )
    assert [voice["id"] for voice in manifest["voices"]] == ["sherpa-en-debug"]


def test_secure_transport_spike_server_command_requires_tls_and_loopback(
    tmp_path: Path,
) -> None:
    check_module = _load_check_module()
    certificate = tmp_path / "certificate.pem"
    private_key = tmp_path / "private-key.pem"

    command = check_module._server_command(
        python_executable="python.exe",
        port=7443,
        certificate_path=certificate,
        private_key_path=private_key,
    )

    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--ssl-certfile") + 1] == str(certificate)
    assert command[command.index("--ssl-keyfile") + 1] == str(private_key)
    assert "--allow-non-local-host" not in command


def test_secure_transport_spike_env_strips_existing_service_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    monkeypatch.setenv("TTS_PLATFORM_TOKEN", "existing-secret")
    monkeypatch.setenv("TTS_PLATFORM__SERVER__HOST", "0.0.0.0")
    monkeypatch.setenv("UVICORN_HOST", "0.0.0.0")
    monkeypatch.setenv("TTS_READER_SPIKE_CONFIG", "old-config")

    env = check_module._source_env()

    assert "TTS_PLATFORM_TOKEN" not in env
    assert "TTS_PLATFORM__SERVER__HOST" not in env
    assert "UVICORN_HOST" not in env
    assert "TTS_READER_SPIKE_CONFIG" not in env
    assert str(check_module.REPO_ROOT) in env["PYTHONPATH"]
    assert str(check_module.SERVICE_SRC) in env["PYTHONPATH"]


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_reader_secure_transport",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
