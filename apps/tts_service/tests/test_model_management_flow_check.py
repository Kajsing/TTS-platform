from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_model_management_flow.py"


def test_model_management_flow_check_installs_activates_smokes_and_removes() -> None:
    check_module = _load_check_module()

    summary = check_module.check_model_management_flow(
        python_executable=sys.executable,
        startup_timeout_s=30,
        command_timeout_s=60,
        stream_text_repeat=1,
    )

    assert summary["model_id"] == "local-flow-voice"
    assert summary["default_catalog"] == {
        "source": "models/catalog.json",
        "model_count": 1,
        "installable_count": 1,
        "checksum_count": 1,
        "next_steps": [
            "review model_summaries for installable models and checksum coverage",
            "tts model-install local-flow-voice --activate",
        ],
    }
    assert summary["catalog"] == {
        "source": "local_http",
        "model_count": 1,
        "installable_count": 1,
        "checksum_count": 1,
        "warnings": [],
    }
    assert summary["install"]["installed_model"] == "local-flow-voice"
    assert summary["install"]["activated_model"] == "local-flow-voice"
    assert summary["install"]["files_installed"] == 3
    assert summary["install"]["checksum_verified"] is True
    assert summary["model_list"]["default_voice"] == "local-flow-voice"
    assert summary["model_list"]["manifest_voice_count"] == 2
    assert summary["model_list"]["default_voice_in_manifest"] is True
    assert summary["model_list"]["model_ids"] == [
        "sherpa-en-debug",
        "local-flow-voice",
    ]
    assert summary["model_list"]["default_model_id"] == "local-flow-voice"
    assert summary["model_list"]["default_model_has_backend_config"] is False
    assert summary["model_list"]["default_catalog_exists"] is True
    assert summary["model_list"]["next_steps"] == [
        "tts model-install local-flow-voice --activate --overwrite",
        "tts model-check",
    ]
    assert summary["model_check"]["model_id"] == "local-flow-voice"
    assert summary["model_check"]["voice_found"] is True
    assert summary["model_check"]["backend_configured"] is False
    assert summary["model_check"]["assets_ready"] is False
    assert summary["model_check"]["default_catalog_exists"] is True
    assert summary["model_check"]["next_steps"][0] == (
        "tts model-install local-flow-voice --activate --overwrite"
    )
    assert summary["service"]["health"]["status"] == "ok"
    assert summary["service"]["voice"] == "local-flow-voice"
    assert summary["service"]["http_bytes"] > 0
    assert summary["service"]["stream_frames"] > 0
    assert summary["service"]["job_status"] == "completed"
    assert summary["remove"]["removed_files"] is True
    assert summary["remove"]["removed_manifest_entry"] is True
    assert summary["remove"]["active_default_voice"] is True
    assert "default_voice" in summary["remove"]["warning"]


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_model_management_flow",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
