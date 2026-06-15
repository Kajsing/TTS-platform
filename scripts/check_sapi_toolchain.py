from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SAPI_PROJECT = REPO_ROOT / "apps" / "sapi_bridge" / "TtsPlatformSapiBridge.vcxproj"
DEFAULT_WINDOWS_KITS_INCLUDE = Path("C:/Program Files (x86)/Windows Kits/10/Include")


class SapiToolchainCheckError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_sapi_toolchain")
    parser.add_argument("--require-build-tools", action="store_true")
    args = parser.parse_args(argv)

    summary = check_sapi_toolchain(require_build_tools=args.require_build_tools)
    print(json.dumps(summary, indent=2, sort_keys=True))


def check_sapi_toolchain(*, require_build_tools: bool = False) -> dict[str, object]:
    tools = {
        "cl": _which("cl"),
        "msbuild": _which("msbuild"),
        "cmake": _which("cmake"),
        "ninja": _which("ninja"),
        "midl": _which("midl"),
        "dotnet": _which("dotnet"),
    }
    headers = {
        "sapi_h": _find_windows_header("sapi.h"),
        "sphelper_h": _find_windows_header("sphelper.h"),
    }
    project_exists = SAPI_PROJECT.is_file()
    can_attempt_msvc_build = bool(
        tools["cl"] and tools["msbuild"] and headers["sapi_h"] and headers["sphelper_h"]
    )
    missing_required = [
        name
        for name, value in {
            "cl": tools["cl"],
            "msbuild": tools["msbuild"],
            "sapi.h": headers["sapi_h"],
            "sphelper.h": headers["sphelper_h"],
            "TtsPlatformSapiBridge.vcxproj": str(SAPI_PROJECT) if project_exists else None,
        }.items()
        if not value
    ]

    summary: dict[str, object] = {
        "project": str(SAPI_PROJECT),
        "project_exists": project_exists,
        "tools": tools,
        "headers": headers,
        "can_attempt_msvc_build": can_attempt_msvc_build,
        "missing_required": missing_required,
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


def _find_windows_header(name: str) -> str | None:
    include_env = os.environ.get("INCLUDE", "")
    for raw_part in include_env.split(os.pathsep):
        if not raw_part:
            continue
        candidate = Path(raw_part) / name
        if candidate.is_file():
            return str(candidate)

    if DEFAULT_WINDOWS_KITS_INCLUDE.is_dir():
        candidates = sorted(DEFAULT_WINDOWS_KITS_INCLUDE.glob(f"*/um/{name}"), reverse=True)
        if candidates:
            return str(candidates[0])
    return None


def _next_steps(missing_required: list[str]) -> list[str]:
    if not missing_required:
        return [
            "Open a Visual Studio Developer PowerShell",
            "Build apps/sapi_bridge/TtsPlatformSapiBridge.vcxproj for Win32 and x64",
        ]
    return [
        "Install Visual Studio Build Tools with Desktop development with C++",
        "Include the Windows 10 or 11 SDK so sapi.h and sphelper.h are available",
        "Open a Visual Studio Developer PowerShell before building the SAPI bridge",
    ]


if __name__ == "__main__":
    main()

