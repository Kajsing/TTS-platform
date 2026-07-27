from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_extension_library_flow.py"


def test_extension_library_flow_source_wiring_keeps_raw_text_transient() -> None:
    check_module = _load_check_module()

    summary = check_module._verify_extension_wiring()

    assert summary == {
        "selection_save": True,
        "page_save": True,
        "queue_action": True,
        "desktop_handoff": True,
        "raw_text_persisted": False,
    }


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_extension_library_flow",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
