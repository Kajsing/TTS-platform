from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_extension_onboarding.py"


def test_extension_onboarding_check_validates_popup_service_and_origin_snippet() -> None:
    check_module = _load_check_module()

    summary = check_module.check_extension_onboarding(
        python_executable=sys.executable,
        startup_timeout_s=30,
        command_timeout_s=60,
    )

    assert summary["popup"] == {
        "required_element_count": 11,
        "checklist_items": 5,
        "voice_selector": True,
        "copy_snippet": True,
    }
    assert summary["allow_list"]["config_loadable"] is True
    assert summary["allow_list"]["sample_origin"].startswith("chrome-extension://")
    assert summary["allow_list"]["cli_helper"] == {
        "command": "tts extension-allow-origin <chrome-extension-origin>",
        "added": True,
        "config_loadable": True,
    }
    assert summary["service_snapshot"]["health_status"] == "ok"
    assert summary["service_snapshot"]["auth_enabled"] is True
    assert summary["service_snapshot"]["default_voice"] == "sherpa-en-debug"
    assert summary["service_snapshot"]["voice_count"] >= 1


def test_extension_onboarding_allow_list_snippet_accepts_chrome_extension_origin() -> None:
    check_module = _load_check_module()

    summary = check_module._verify_allow_list_snippet(
        "chrome-extension://ponmlkjihgfedcbaponmlkjihgfedcba"
    )

    assert summary == {
        "sample_origin": "chrome-extension://ponmlkjihgfedcbaponmlkjihgfedcba",
        "config_loadable": True,
    }


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_extension_onboarding",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
