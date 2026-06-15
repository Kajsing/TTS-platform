from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SAPI_ROOT = REPO_ROOT / "apps" / "sapi_bridge"
WINDOWS_SCRIPT_ROOT = REPO_ROOT / "scripts" / "windows"


class SapiBridgeCheckError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_sapi_bridge")
    parser.parse_args(argv)

    try:
        summary = check_sapi_bridge()
    except SapiBridgeCheckError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_sapi_bridge() -> dict[str, object]:
    required_files = [
        SAPI_ROOT / "README.md",
        SAPI_ROOT / "src" / "README.md",
        WINDOWS_SCRIPT_ROOT / "install_sapi_voice.ps1",
        WINDOWS_SCRIPT_ROOT / "remove_sapi_voice.ps1",
        WINDOWS_SCRIPT_ROOT / "check_sapi_voice.ps1",
    ]
    missing = [path for path in required_files if not path.is_file()]
    if missing:
        raise SapiBridgeCheckError(
            "Missing SAPI bridge files:\n"
            + "\n".join(str(path.relative_to(REPO_ROOT)) for path in missing)
        )

    required_fragments = {
        SAPI_ROOT / "README.md": [
            "TTS Platform Dummy Voice",
            "TextAloud",
            "aliases an existing Windows SAPI voice",
            "elevated PowerShell prompt",
            "not the final bridge",
        ],
        SAPI_ROOT / "src" / "README.md": [
            "ISpTTSEngine",
            "ISpObjectWithToken",
            "COM DLL",
            "TextAloud-required bitness",
        ],
        WINDOWS_SCRIPT_ROOT / "install_sapi_voice.ps1": [
            "TTS_PLATFORM_DUMMY_ALIAS",
            "TTS_MS_EN-US_ZIRA_11.0",
            "HKLM:\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens",
            "HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Speech\\Voices\\Tokens",
            "Test-IsAdministrator",
            "SupportsShouldProcess",
            "CLSID",
            "LangDataPath",
            "VoicePath",
        ],
        WINDOWS_SCRIPT_ROOT / "remove_sapi_voice.ps1": [
            "TTS_PLATFORM_DUMMY_ALIAS",
            "HKLM:\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens",
            "HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Speech\\Voices\\Tokens",
            "Test-IsAdministrator",
            "SupportsShouldProcess",
        ],
        WINDOWS_SCRIPT_ROOT / "check_sapi_voice.ps1": [
            "TTS_PLATFORM_DUMMY_ALIAS",
            "SAPI.SpVoice",
            "SysWOW64\\WindowsPowerShell",
            "RequireInstalled",
            "current_process",
            "wow64_process",
        ],
    }

    errors: list[str] = []
    for path, fragments in required_fragments.items():
        text = path.read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment not in text:
                errors.append(f"{path.relative_to(REPO_ROOT)} must contain {fragment!r}")
    if errors:
        raise SapiBridgeCheckError("SAPI bridge check failed:\n" + "\n".join(errors))

    return {
        "checked_files": len(required_files),
        "dummy_voice_token": "TTS_PLATFORM_DUMMY_ALIAS",
        "dummy_voice_name": "TTS Platform Dummy Voice",
        "machine_scope_registry": True,
        "x64_registry_view": True,
        "x86_registry_view": True,
        "requires_elevated_install": True,
        "textaloud_visibility_spike": True,
        "localhost_integration": False,
    }


if __name__ == "__main__":
    main()
