from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_v1_completion.py"


def test_v1_completion_check_passes_prefinal_repo_state() -> None:
    check_module = _load_v1_completion_module()

    summary = check_module.check_v1_completion(repo_root=REPO_ROOT)

    assert summary["criteria_ready"] == 8
    assert summary["criteria_pending_final_security"] == 1
    assert summary["final_security_pending"] is True
    assert summary["can_mark_v1_complete"] is False
    assert summary["readiness"]["manual_gates_documented"] is True


def test_v1_completion_check_require_complete_rejects_pending_final_security() -> None:
    check_module = _load_v1_completion_module()

    with pytest.raises(check_module.V1CompletionError, match="Final security-focused pass"):
        check_module.check_v1_completion(
            repo_root=REPO_ROOT,
            require_complete=True,
        )


def _load_v1_completion_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_v1_completion",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
