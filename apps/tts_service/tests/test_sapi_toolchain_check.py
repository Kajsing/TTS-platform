from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_sapi_toolchain.py"


def test_sapi_toolchain_check_reports_project_and_missing_tools(
    monkeypatch,
    tmp_path: Path,
) -> None:
    check_module = _load_check_module()
    monkeypatch.setattr(check_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(check_module, "DEFAULT_WINDOWS_KITS_INCLUDE", tmp_path)

    summary = check_module.check_sapi_toolchain(require_build_tools=False)

    assert summary["project_exists"] is True
    assert summary["can_attempt_msvc_build"] is False
    assert "cl" in summary["missing_required"]
    assert "msbuild" in summary["missing_required"]
    assert "sapi.h" in summary["missing_required"]
    assert summary["ok"] is True


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_sapi_toolchain",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

