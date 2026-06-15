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
        SAPI_ROOT / "src" / "TtsPlatformSapiEngine.h",
        SAPI_ROOT / "src" / "TtsPlatformSapiEngine.cpp",
        SAPI_ROOT / "src" / "dllmain.cpp",
        SAPI_ROOT / "src" / "TtsPlatformSapiBridge.def",
        SAPI_ROOT / "TtsPlatformSapiBridge.vcxproj",
        WINDOWS_SCRIPT_ROOT / "build_sapi_bridge.ps1",
        WINDOWS_SCRIPT_ROOT / "install_sapi_native_voice.ps1",
        WINDOWS_SCRIPT_ROOT / "remove_sapi_native_voice.ps1",
        WINDOWS_SCRIPT_ROOT / "check_sapi_native_voice.ps1",
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
        SAPI_ROOT / "src" / "TtsPlatformSapiEngine.h": [
            "#include <sapiddk.h>",
            "public ISpTTSEngine",
            "public ISpObjectWithToken",
            "STDMETHODIMP Speak",
            "STDMETHODIMP GetOutputFormat",
            "TtsPlatformClassFactory",
        ],
        SAPI_ROOT / "src" / "TtsPlatformSapiEngine.cpp": [
            "CLSID_TtsPlatformSapiEngine",
            "MakeTonePcm",
            "CollectText",
            "ReadToken",
            "LogBridgeEvent",
            "sapi-bridge.log",
            "SplitTextForService",
            "kMaxServiceTextChars",
            "MakeSilenceBytes",
            "TryWriteServiceAudio",
            "IsAbortRequested",
            "WinHttpOpen",
            "WinHttpSendRequest",
            "DecodeWavPcm16",
            "site->Write",
            "SPDFID_WaveFormatEx",
            "WAVE_FORMAT_PCM",
            "E_INVALIDARG",
        ],
        SAPI_ROOT / "src" / "dllmain.cpp": [
            "DllGetClassObject",
            "DllCanUnloadNow",
            "DllRegisterServer",
            "CLSID_TtsPlatformSapiEngine",
        ],
        SAPI_ROOT / "src" / "TtsPlatformSapiBridge.def": [
            "DllGetClassObject",
            "DllCanUnloadNow",
        ],
        SAPI_ROOT / "TtsPlatformSapiBridge.vcxproj": [
            "DynamicLibrary",
            "Win32",
            "x64",
            "sapi.lib",
            "winhttp.lib",
            "TtsPlatformSapiEngine.cpp",
            "$(MSBuildProjectDirectory)\\build\\$(Platform)\\$(Configuration)",
        ],
        WINDOWS_SCRIPT_ROOT / "build_sapi_bridge.ps1": [
            "TtsPlatformSapiBridge.vcxproj",
            "MSBuild",
            "vswhere",
            "Win32",
            "x64",
            "RequireBuildTools",
        ],
        WINDOWS_SCRIPT_ROOT / "install_sapi_native_voice.ps1": [
            "TTS_PLATFORM_NATIVE_DUMMY",
            "TTS Platform Native Dummy Voice",
            "{7F241B98-6F49-4A18-9A40-98764D039A1B}",
            "InprocServer32",
            "ThreadingModel",
            "DllPath is required",
            "elevated PowerShell prompt",
        ],
        WINDOWS_SCRIPT_ROOT / "remove_sapi_native_voice.ps1": [
            "TTS_PLATFORM_NATIVE_DUMMY",
            "TTS Platform Native Dummy Voice",
            "{7F241B98-6F49-4A18-9A40-98764D039A1B}",
            "Remove native SAPI COM class",
            "elevated PowerShell prompt",
        ],
        WINDOWS_SCRIPT_ROOT / "check_sapi_native_voice.ps1": [
            "TTS_PLATFORM_NATIVE_DUMMY",
            "TTS Platform Native Dummy Voice",
            "InprocServer32",
            "registered_dll_exists",
            "RequireInstalled",
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
        "native_skeleton": True,
        "dummy_pcm_speak": True,
        "native_build_script": True,
        "native_registration_scripts": True,
        "localhost_integration": True,
        "localhost_integration_verified_in_textaloud": False,
    }


if __name__ == "__main__":
    main()
