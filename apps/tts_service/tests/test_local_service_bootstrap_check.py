from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_local_service_bootstrap.py"


def test_local_service_bootstrap_check_runs_temp_service() -> None:
    check_module = _load_check_module()

    summary = check_module.check_local_service_bootstrap(
        python_executable=sys.executable,
        startup_timeout_s=30,
        command_timeout_s=60,
        stream_text_repeat=2,
        min_stream_text_chunks=1,
    )

    assert str(summary["base_url"]).startswith("http://127.0.0.1:")
    assert summary["setup"]["config_created"] is True
    assert summary["setup"]["token_created"] is True
    assert summary["setup"]["auth_enabled"] is True
    assert summary["setup"]["manifest_default_voice"] is True
    assert summary["smoke"]["health"]["status"] == "ok"
    assert summary["smoke"]["voices"]["count"] >= 1
    assert summary["smoke"]["http"]["bytes"] > 0
    assert summary["smoke"]["stream"]["frames"] >= 1
    assert summary["smoke"]["stream"]["text_chunk_count"] >= 1
    assert summary["smoke"]["job"]["status"] == "completed"


def test_local_service_bootstrap_env_strips_existing_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    monkeypatch.setenv("TTS_PLATFORM_TOKEN", "existing-secret")
    monkeypatch.setenv("TTS_PLATFORM__SERVER__PORT", "9999")

    env = check_module._source_env()

    assert "TTS_PLATFORM_TOKEN" not in env
    assert "TTS_PLATFORM__SERVER__PORT" not in env
    assert str(check_module.SERVICE_SRC) in env["PYTHONPATH"]
    assert str(check_module.CORE_SRC) in env["PYTHONPATH"]


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_local_service_bootstrap",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
