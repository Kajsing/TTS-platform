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
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "Program Files (x86)"))

    summary = check_module.check_sapi_toolchain(require_build_tools=False)

    assert summary["project_exists"] is True
    assert summary["can_attempt_msvc_build"] is False
    assert "cl" in summary["missing_required"]
    assert "msbuild" in summary["missing_required"]
    assert "sapi.h" in summary["missing_required"]
    assert "sapiddk.h" in summary["missing_required"]
    assert summary["ok"] is True


def test_sapi_toolchain_check_discovers_vs_and_sdk_without_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    check_module = _load_check_module()
    program_files = tmp_path / "Program Files"
    program_files_x86 = tmp_path / "Program Files (x86)"
    install_root = (
        program_files
        / "Microsoft Visual Studio"
        / "2022"
        / "BuildTools"
    )
    msbuild = install_root / "MSBuild" / "Current" / "Bin" / "MSBuild.exe"
    cl = (
        install_root
        / "VC"
        / "Tools"
        / "MSVC"
        / "14.40.0"
        / "bin"
        / "Hostx64"
        / "x64"
        / "cl.exe"
    )
    sdk_um = (
        program_files_x86
        / "Windows Kits"
        / "10"
        / "Include"
        / "10.0.19041.0"
        / "um"
    )
    msbuild.parent.mkdir(parents=True)
    cl.parent.mkdir(parents=True)
    sdk_um.mkdir(parents=True)
    msbuild.write_text("", encoding="utf-8")
    cl.write_text("", encoding="utf-8")
    (sdk_um / "sapi.h").write_text("", encoding="utf-8")
    (sdk_um / "sapiddk.h").write_text("", encoding="utf-8")

    monkeypatch.setattr(check_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(check_module, "DEFAULT_WINDOWS_KITS_INCLUDE", tmp_path / "missing-sdk")
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setenv("ProgramFiles(x86)", str(program_files_x86))

    summary = check_module.check_sapi_toolchain(require_build_tools=False)

    assert summary["can_attempt_msvc_build"] is True
    assert summary["missing_required"] == []
    assert summary["tools"]["msbuild"] == str(msbuild)
    assert summary["tools"]["cl"] == str(cl)
    assert summary["headers"]["sapi_h"] == str(sdk_um / "sapi.h")
    assert summary["headers"]["sapiddk_h"] == str(sdk_um / "sapiddk.h")
    assert summary["headers"]["sphelper_h"] is None
    assert summary["visual_studio"]["installations"] == [str(install_root.resolve())]
    assert summary["windows_sdk"]["versions"] == ["10.0.19041.0"]


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
