from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SAPI_PROJECT = REPO_ROOT / "apps" / "sapi_bridge" / "TtsPlatformSapiBridge.vcxproj"
DEFAULT_WINDOWS_KITS_INCLUDE = Path("C:/Program Files (x86)/Windows Kits/10/Include")
VS_BUILDTOOLS_PACKAGE_ID = "Microsoft.VisualStudio.2022.BuildTools"
VS_COMPONENTS = [
    "Microsoft.VisualStudio.Workload.VCTools",
    "Microsoft.VisualStudio.Component.Windows10SDK.19041",
]


class SapiToolchainCheckError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_sapi_toolchain")
    parser.add_argument("--require-build-tools", action="store_true")
    args = parser.parse_args(argv)

    summary = check_sapi_toolchain(require_build_tools=args.require_build_tools)
    print(json.dumps(summary, indent=2, sort_keys=True))


def check_sapi_toolchain(*, require_build_tools: bool = False) -> dict[str, object]:
    visual_studio = _find_visual_studio()
    windows_sdk = _find_windows_sdk()
    tools = {
        "cl": _which("cl") or _find_vs_tool(visual_studio, "cl.exe"),
        "msbuild": _which("msbuild") or _find_msbuild(visual_studio),
        "cmake": _which("cmake"),
        "ninja": _which("ninja"),
        "midl": _which("midl"),
        "dotnet": _which("dotnet"),
        "vswhere": visual_studio["vswhere"],
        "winget": _which("winget"),
    }
    headers = {
        "sapi_h": _find_windows_header("sapi.h", windows_sdk),
        "sapiddk_h": _find_windows_header("sapiddk.h", windows_sdk),
        "sphelper_h": _find_windows_header("sphelper.h", windows_sdk),
    }
    project_exists = SAPI_PROJECT.is_file()
    can_attempt_msvc_build = bool(
        tools["cl"] and tools["msbuild"] and headers["sapi_h"] and headers["sapiddk_h"]
    )
    missing_required = [
        name
        for name, value in {
            "cl": tools["cl"],
            "msbuild": tools["msbuild"],
            "sapi.h": headers["sapi_h"],
            "sapiddk.h": headers["sapiddk_h"],
            "TtsPlatformSapiBridge.vcxproj": str(SAPI_PROJECT) if project_exists else None,
        }.items()
        if not value
    ]

    summary: dict[str, object] = {
        "project": str(SAPI_PROJECT),
        "project_exists": project_exists,
        "tools": tools,
        "headers": headers,
        "visual_studio": visual_studio,
        "windows_sdk": windows_sdk,
        "can_attempt_msvc_build": can_attempt_msvc_build,
        "missing_required": missing_required,
        "install_guidance": _install_guidance(tools),
        "next_steps": _next_steps(missing_required),
    }
    if require_build_tools and (missing_required or not can_attempt_msvc_build):
        summary["ok"] = False
        print(json.dumps(summary, indent=2, sort_keys=True))
        raise SystemExit("SAPI native build toolchain is incomplete.")
    summary["ok"] = True
    return summary


def _which(name: str) -> str | None:
    resolved = shutil.which(name)
    if resolved:
        return str(Path(resolved))
    return None


def _find_windows_header(name: str, windows_sdk: dict[str, object]) -> str | None:
    include_env = os.environ.get("INCLUDE", "")
    for raw_part in include_env.split(os.pathsep):
        if not raw_part:
            continue
        candidate = Path(raw_part) / name
        if candidate.is_file():
            return str(candidate)

    include_roots = [Path(root) for root in windows_sdk["include_roots"]]
    if DEFAULT_WINDOWS_KITS_INCLUDE not in include_roots:
        include_roots.append(DEFAULT_WINDOWS_KITS_INCLUDE)
    for include_root in include_roots:
        if include_root.is_dir():
            candidates = sorted(include_root.glob(f"*/um/{name}"), reverse=True)
            if candidates:
                return str(candidates[0])
    return None


def _find_windows_sdk() -> dict[str, object]:
    roots = [
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Windows Kits"
        / "10"
        / "Include",
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Windows Kits"
        / "10"
        / "Include",
    ]
    include_roots = [str(root) for root in roots if root.is_dir()]
    versions: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        versions.extend(path.name for path in root.iterdir() if path.is_dir())
    return {
        "include_roots": include_roots,
        "versions": sorted(set(versions), reverse=True),
    }


def _find_visual_studio() -> dict[str, object]:
    vswhere = _find_vswhere()
    installations = _vswhere_installations(vswhere) if vswhere else []
    installations.extend(_discover_vs_installations())
    unique_installations = _dedupe_existing_paths(installations)
    return {
        "vswhere": vswhere,
        "installations": unique_installations,
        "developer_shells": _developer_shells(unique_installations),
    }


def _find_vswhere() -> str | None:
    from_path = _which("vswhere")
    if from_path:
        return from_path
    installer_root = (
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Microsoft Visual Studio"
        / "Installer"
        / "vswhere.exe"
    )
    if installer_root.is_file():
        return str(installer_root)
    return None


def _vswhere_installations(vswhere: str) -> list[str]:
    try:
        result = subprocess.run(
            [
                vswhere,
                "-products",
                "*",
                "-requires",
                "Microsoft.Component.MSBuild",
                "-format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return [
        item["installationPath"]
        for item in payload
        if isinstance(item, dict) and item.get("installationPath")
    ]


def _discover_vs_installations() -> list[str]:
    roots = [
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft Visual Studio",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Microsoft Visual Studio",
    ]
    patterns = [
        root / "*" / "*" / "MSBuild" / "Current" / "Bin" / "MSBuild.exe"
        for root in roots
    ]
    installs: list[str] = []
    for pattern in patterns:
        for msbuild in glob.glob(str(pattern)):
            installs.append(str(Path(msbuild).parents[3]))
    return installs


def _find_msbuild(visual_studio: dict[str, object]) -> str | None:
    for install in visual_studio["installations"]:
        candidate = Path(install) / "MSBuild" / "Current" / "Bin" / "MSBuild.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def _find_vs_tool(visual_studio: dict[str, object], tool_name: str) -> str | None:
    for install in visual_studio["installations"]:
        tools_root = Path(install) / "VC" / "Tools" / "MSVC"
        if not tools_root.is_dir():
            continue
        candidates = sorted(
            tools_root.glob(f"*/bin/Hostx64/x64/{tool_name}"),
            reverse=True,
        )
        if candidates:
            return str(candidates[0])
    return None


def _developer_shells(installations: list[str]) -> list[str]:
    shells: list[str] = []
    for install in installations:
        candidate = (
            Path(install)
            / "Common7"
            / "Tools"
            / "Launch-VsDevShell.ps1"
        )
        if candidate.is_file():
            shells.append(str(candidate))
    return shells


def _dedupe_existing_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(str(path.resolve()))
    return deduped


def _install_guidance(tools: dict[str, str | None]) -> dict[str, object]:
    command = (
        f"winget install --id {VS_BUILDTOOLS_PACKAGE_ID} --exact --source winget "
        '--override "--wait --passive '
        f"--add {' --add '.join(VS_COMPONENTS)} "
        '--includeRecommended"'
    )
    return {
        "winget_available": bool(tools["winget"]),
        "visual_studio_build_tools_package": VS_BUILDTOOLS_PACKAGE_ID,
        "required_components": VS_COMPONENTS,
        "winget_command": command,
        "manual_installer_note": (
            "Install Visual Studio Build Tools 2022 with Desktop development "
            "with C++ and a Windows 10 or 11 SDK."
        ),
    }


def _next_steps(missing_required: list[str]) -> list[str]:
    if not missing_required:
        return [
            "Open a Visual Studio Developer PowerShell",
            "Build apps/sapi_bridge/TtsPlatformSapiBridge.vcxproj for Win32 and x64",
        ]
    return [
        "Install Visual Studio Build Tools with Desktop development with C++",
        "Include the Windows 10 or 11 SDK so sapi.h and sapiddk.h are available",
        "Open a Visual Studio Developer PowerShell before building the SAPI bridge",
    ]


if __name__ == "__main__":
    main()
