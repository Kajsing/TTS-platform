from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_windows_service_task.py"


def test_windows_service_task_check_passes_repo_state() -> None:
    check_module = _load_check_module()

    summary = check_module.check_windows_service_task(repo_root=REPO_ROOT)

    assert summary["scheduled_launcher"]["forwards_run_service"] is True
    assert summary["scheduled_launcher"]["captures_all_streams"] is True
    assert summary["cli_contract"]["task_name"] == "TTS Platform Local Reader"
    assert summary["cli_contract"]["scope"] == "user"
    assert summary["cli_contract"]["run_at"] == "user-logon"
    assert summary["cli_contract"]["status_parser"] == "Ready"


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_windows_service_task",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
