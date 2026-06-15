from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_sapi_bridge.py"


def test_sapi_bridge_check_accepts_dummy_voice_spike_contract() -> None:
    check_module = _load_check_module()

    summary = check_module.check_sapi_bridge()

    assert summary == {
        "checked_files": 14,
        "dummy_voice_token": "TTS_PLATFORM_DUMMY_ALIAS",
        "dummy_voice_name": "TTS Platform Dummy Voice",
        "machine_scope_registry": True,
        "x64_registry_view": True,
        "x86_registry_view": True,
        "requires_elevated_install": True,
        "textaloud_visibility_spike": True,
        "native_skeleton": True,
        "dummy_pcm_speak": True,
        "native_build_script": True,
        "native_registration_scripts": True,
        "localhost_integration": True,
        "localhost_integration_verified_in_textaloud": False,
    }


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_sapi_bridge",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
