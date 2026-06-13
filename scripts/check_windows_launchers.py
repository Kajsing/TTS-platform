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
DEFAULT_STARTUP_TIMEOUT_S = 30.0
DEFAULT_STREAM_TEXT_REPEAT = 20
DEFAULT_MIN_STREAM_TEXT_CHUNKS = 2


class WindowsLauncherCheckError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_windows_launchers")
    parser.add_argument("--bundle", default=None)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--startup-timeout-s", type=float, default=DEFAULT_STARTUP_TIMEOUT_S)
    parser.add_argument("--command-timeout-s", type=float, default=DEFAULT_COMMAND_TIMEOUT_S)
    parser.add_argument("--stream-text-repeat", type=int, default=DEFAULT_STREAM_TEXT_REPEAT)
    parser.add_argument(
        "--min-stream-text-chunks",
        type=int,
        default=DEFAULT_MIN_STREAM_TEXT_CHUNKS,
    )
    args = parser.parse_args(argv)

    try:
        if args.bundle:
            summary = check_windows_launchers(
                bundle_path=Path(args.bundle),
                python_executable=args.python_executable,
                startup_timeout_s=args.startup_timeout_s,
                command_timeout_s=args.command_timeout_s,
                stream_text_repeat=args.stream_text_repeat,
                min_stream_text_chunks=args.min_stream_text_chunks,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="tts-platform-launcher-check-") as temp_dir:
                bundle_path = Path(temp_dir) / "tts-platform-local-reader.zip"
                package_windows_bundle.package_windows_bundle(out_path=bundle_path)
                summary = check_windows_launchers(
                    bundle_path=bundle_path,
                    python_executable=args.python_executable,
                    startup_timeout_s=args.startup_timeout_s,
                    command_timeout_s=args.command_timeout_s,
                    stream_text_repeat=args.stream_text_repeat,
                    min_stream_text_chunks=args.min_stream_text_chunks,
                )
    except WindowsLauncherCheckError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_windows_launchers(
    *,
    bundle_path: Path,
    python_executable: str,
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
    command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
    stream_text_repeat: int = DEFAULT_STREAM_TEXT_REPEAT,
    min_stream_text_chunks: int = DEFAULT_MIN_STREAM_TEXT_CHUNKS,
) -> dict[str, object]:
    if startup_timeout_s <= 0:
        raise WindowsLauncherCheckError("--startup-timeout-s must be positive.")
    if command_timeout_s <= 0:
        raise WindowsLauncherCheckError("--command-timeout-s must be positive.")
    if stream_text_repeat <= 0:
        raise WindowsLauncherCheckError("--stream-text-repeat must be positive.")
    if min_stream_text_chunks <= 0:
        raise WindowsLauncherCheckError("--min-stream-text-chunks must be positive.")

    resolved_bundle_path = bundle_path.expanduser().resolve()
    if not resolved_bundle_path.is_file():
        raise WindowsLauncherCheckError(f"Bundle does not exist: {resolved_bundle_path}")

    launcher_results: list[dict[str, object]] = []
    service_results: list[dict[str, object]] = []
    skipped: list[str] = []

    powershell_executable = _find_powershell_executable()
    if powershell_executable:
        def powershell_command_builder(bundle_root: Path) -> list[str]:
            return [
                powershell_executable,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(bundle_root / "scripts" / "windows" / "run_service.ps1"),
            ]

        def powershell_setup_command_builder(bundle_root: Path) -> list[str]:
            return powershell_command_builder(bundle_root) + ["-SetupOnly"]

        launcher_results.append(
            _check_launcher_setup_only(
                bundle_path=resolved_bundle_path,
                launcher_name="powershell",
                command_builder=powershell_setup_command_builder,
                python_executable=python_executable,
                timeout_s=command_timeout_s,
            )
        )
        if os.name == "nt":
            service_results.append(
                _check_launcher_service(
                    bundle_path=resolved_bundle_path,
                    launcher_name="powershell",
                    command_builder=powershell_command_builder,
                    python_executable=python_executable,
                    startup_timeout_s=startup_timeout_s,
                    command_timeout_s=command_timeout_s,
                    stream_text_repeat=stream_text_repeat,
                    min_stream_text_chunks=min_stream_text_chunks,
                )
            )
    else:
        skipped.append("powershell")

    cmd_executable = _find_cmd_executable()
    if cmd_executable:
        def cmd_command_builder(bundle_root: Path) -> list[str]:
            return [
                cmd_executable,
                "/c",
                str(bundle_root / "scripts" / "windows" / "run_service.cmd"),
            ]

        def cmd_setup_command_builder(bundle_root: Path) -> list[str]:
            return cmd_command_builder(bundle_root) + ["-SetupOnly"]

        launcher_results.append(
            _check_launcher_setup_only(
                bundle_path=resolved_bundle_path,
                launcher_name="cmd",
                command_builder=cmd_setup_command_builder,
                python_executable=python_executable,
                timeout_s=command_timeout_s,
            )
        )
        if os.name == "nt":
            service_results.append(
                _check_launcher_service(
                    bundle_path=resolved_bundle_path,
                    launcher_name="cmd",
                    command_builder=cmd_command_builder,
                    python_executable=python_executable,
                    startup_timeout_s=startup_timeout_s,
                    command_timeout_s=command_timeout_s,
                    stream_text_repeat=stream_text_repeat,
                    min_stream_text_chunks=min_stream_text_chunks,
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
    if os.name != "nt":
        skipped.append("foreground-service-smoke-windows-host")

    return {
        "bundle_path": str(resolved_bundle_path),
        "launchers": launcher_results,
        "service_smoke": service_results,
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
        "catalog_single_installable_model": _dict_get(
            payload.get("catalog"),
            "single_installable_model_id",
        ),
        "next_steps": _string_list(payload.get("next_steps")),
    }


def _check_launcher_service(
    *,
    bundle_path: Path,
    launcher_name: str,
    command_builder,
    python_executable: str,
    startup_timeout_s: float,
    command_timeout_s: float,
    stream_text_repeat: int,
    min_stream_text_chunks: int,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"tts-platform-{launcher_name}-service-") as temp_dir:
        extract_root = Path(temp_dir)
        _extract_bundle(bundle_path=bundle_path, extract_root=extract_root)
        bundle_root = extract_root / BUNDLE_ROOT
        port = check_local_service_bootstrap._reserve_loopback_port()
        base_url = f"http://127.0.0.1:{port}"
        command = command_builder(bundle_root) + [
            "-HostOverride",
            "127.0.0.1",
            "-Port",
            str(port),
        ]
        env = _launcher_env(python_executable=python_executable)
        process = _start_launcher_process(command=command, bundle_root=bundle_root, env=env)
        try:
            try:
                check_local_service_bootstrap._wait_for_health(
                    base_url=base_url,
                    process=process,
                    timeout_s=startup_timeout_s,
                )
                token_file = bundle_root / "config" / "token.txt"
                if not token_file.is_file():
                    raise WindowsLauncherCheckError(
                        f"{launcher_name} launcher did not create config/token.txt."
                    )
                smoke_payload = check_local_service_bootstrap._run_json_command(
                    [
                        python_executable,
                        "scripts/smoke_service.py",
                        "--base-url",
                        base_url,
                        "--token-file",
                        str(token_file),
                        "--stream-text-repeat",
                        str(stream_text_repeat),
                        "--min-stream-text-chunks",
                        str(min_stream_text_chunks),
                    ],
                    env=check_local_service_bootstrap._source_env(),
                    timeout_s=command_timeout_s,
                )
            except check_local_service_bootstrap.LocalServiceBootstrapError as exc:
                raise WindowsLauncherCheckError(
                    f"{launcher_name} launcher service smoke failed: {exc}"
                ) from exc
        finally:
            _stop_launcher_process(process)

    return {
        "name": launcher_name,
        "foreground_service": True,
        "base_url": base_url,
        "smoke": check_local_service_bootstrap._summarize_smoke(smoke_payload),
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
    env = _launcher_env(python_executable=python_executable)
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


def _launcher_env(*, python_executable: str) -> dict[str, str]:
    env = dict(os.environ)
    env["TTS_PLATFORM_PYTHON"] = python_executable
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _start_launcher_process(
    *,
    command: list[str],
    bundle_root: Path,
    env: dict[str, str],
) -> subprocess.Popen[str]:
    try:
        return subprocess.Popen(
            command,
            cwd=bundle_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise WindowsLauncherCheckError(
            "Could not start launcher service command: " + " ".join(command)
        ) from exc


def _stop_launcher_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        process.communicate(timeout=1)
        return
    if os.name == "nt" and shutil.which("taskkill"):
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
        return
    check_local_service_bootstrap._stop_process(process)


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


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


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
check_local_service_bootstrap = _load_script_module(
    "tts_platform_check_local_service_bootstrap_for_launchers",
    SCRIPT_DIR / "check_local_service_bootstrap.py",
)


if __name__ == "__main__":
    main()
