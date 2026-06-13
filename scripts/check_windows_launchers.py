from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
BUNDLE_ROOT = "tts-platform"
DEFAULT_COMMAND_TIMEOUT_S = 90.0


class WindowsLauncherCheckError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_windows_launchers")
    parser.add_argument("--bundle", default=None)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--command-timeout-s", type=float, default=DEFAULT_COMMAND_TIMEOUT_S)
    args = parser.parse_args(argv)

    try:
        if args.bundle:
            summary = check_windows_launchers(
                bundle_path=Path(args.bundle),
                python_executable=args.python_executable,
                command_timeout_s=args.command_timeout_s,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="tts-platform-launcher-check-") as temp_dir:
                bundle_path = Path(temp_dir) / "tts-platform-local-reader.zip"
                package_windows_bundle.package_windows_bundle(out_path=bundle_path)
                summary = check_windows_launchers(
                    bundle_path=bundle_path,
                    python_executable=args.python_executable,
                    command_timeout_s=args.command_timeout_s,
                )
    except WindowsLauncherCheckError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_windows_launchers(
    *,
    bundle_path: Path,
    python_executable: str,
    command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
) -> dict[str, object]:
    if command_timeout_s <= 0:
        raise WindowsLauncherCheckError("--command-timeout-s must be positive.")

    resolved_bundle_path = bundle_path.expanduser().resolve()
    if not resolved_bundle_path.is_file():
        raise WindowsLauncherCheckError(f"Bundle does not exist: {resolved_bundle_path}")

    launcher_results: list[dict[str, object]] = []
    skipped: list[str] = []

    powershell_executable = _find_powershell_executable()
    if powershell_executable:
        launcher_results.append(
            _check_launcher_setup_only(
                bundle_path=resolved_bundle_path,
                launcher_name="powershell",
                command_builder=lambda bundle_root: [
                    powershell_executable,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(bundle_root / "scripts" / "windows" / "run_service.ps1"),
                    "-SetupOnly",
                ],
                python_executable=python_executable,
                timeout_s=command_timeout_s,
            )
        )
    else:
        skipped.append("powershell")

    cmd_executable = _find_cmd_executable()
    if cmd_executable:
        launcher_results.append(
            _check_launcher_setup_only(
                bundle_path=resolved_bundle_path,
                launcher_name="cmd",
                command_builder=lambda bundle_root: [
                    cmd_executable,
                    "/c",
                    str(bundle_root / "scripts" / "windows" / "run_service.cmd"),
                    "-SetupOnly",
                ],
                python_executable=python_executable,
                timeout_s=command_timeout_s,
            )
        )
    else:
        skipped.append("cmd")

    if os.name == "nt" and skipped:
        raise WindowsLauncherCheckError(
            "Missing required Windows launcher executables: " + ", ".join(skipped)
        )
    if not launcher_results:
        skipped.append("windows-host")

    return {
        "bundle_path": str(resolved_bundle_path),
        "launchers": launcher_results,
        "skipped": skipped,
    }


def _check_launcher_setup_only(
    *,
    bundle_path: Path,
    launcher_name: str,
    command_builder,
    python_executable: str,
    timeout_s: float,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"tts-platform-{launcher_name}-") as temp_dir:
        extract_root = Path(temp_dir)
        _extract_bundle(bundle_path=bundle_path, extract_root=extract_root)
        bundle_root = extract_root / BUNDLE_ROOT
        command = command_builder(bundle_root)
        payload = _run_launcher_command(
            command=command,
            bundle_root=bundle_root,
            python_executable=python_executable,
            timeout_s=timeout_s,
        )
        check_windows_bundle_bootstrap._assert_setup_payload(
            setup_payload=payload,
            bundle_root=bundle_root,
        )

    return {
        "name": launcher_name,
        "setup_only": True,
        "config_created": payload.get("config_created"),
        "token_created": payload.get("token_created"),
        "base_url": _dict_get(payload.get("service"), "base_url"),
        "default_voice": payload.get("default_voice"),
        "manifest_default_voice": _dict_get(
            payload.get("manifest"),
            "default_voice_in_manifest",
        ),
    }


def _extract_bundle(*, bundle_path: Path, extract_root: Path) -> None:
    with zipfile.ZipFile(bundle_path) as archive:
        names = set(archive.namelist())
        check_windows_bundle_bootstrap._assert_safe_archive_members(
            archive=archive,
            out_dir=extract_root,
        )
        check_windows_bundle_bootstrap._assert_bundle_contents(names=names)
        archive.extractall(extract_root)


def _run_launcher_command(
    *,
    command: list[str],
    bundle_root: Path,
    python_executable: str,
    timeout_s: float,
) -> dict[str, object]:
    env = dict(os.environ)
    env["TTS_PLATFORM_PYTHON"] = python_executable
    try:
        completed = subprocess.run(
            command,
            cwd=bundle_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.CalledProcessError as exc:
        raise WindowsLauncherCheckError(
            "Launcher setup-only command failed:\n"
            + _format_command_failure(
                command=command,
                stdout=exc.stdout,
                stderr=exc.stderr,
            )
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise WindowsLauncherCheckError(
            f"Launcher setup-only command timed out after {timeout_s:.1f}s: "
            + " ".join(command)
        ) from exc

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WindowsLauncherCheckError(
            "Launcher setup-only command did not return JSON:\n"
            + _format_command_failure(
                command=command,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        ) from exc
    if not isinstance(payload, dict):
        raise WindowsLauncherCheckError("Launcher setup-only payload must be a JSON object.")
    return payload


def _find_powershell_executable() -> str | None:
    return (
        shutil.which("powershell.exe")
        or shutil.which("powershell")
        or shutil.which("pwsh.exe")
        or shutil.which("pwsh")
    )


def _find_cmd_executable() -> str | None:
    return shutil.which("cmd.exe") or shutil.which("cmd")


def _format_command_failure(*, command: list[str], stdout: str | None, stderr: str | None) -> str:
    return "\n".join(
        [
            "command: " + " ".join(command),
            "stdout:",
            (stdout or "").strip(),
            "stderr:",
            (stderr or "").strip(),
        ]
    )


def _dict_get(value: object, key: str) -> object:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _load_script_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package_windows_bundle = _load_script_module(
    "tts_platform_package_windows_bundle_for_launchers",
    SCRIPT_DIR / "package_windows_bundle.py",
)
check_windows_bundle_bootstrap = _load_script_module(
    "tts_platform_check_windows_bundle_bootstrap_for_launchers",
    SCRIPT_DIR / "check_windows_bundle_bootstrap.py",
)


if __name__ == "__main__":
    main()
