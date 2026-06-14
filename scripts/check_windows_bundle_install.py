from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from types import ModuleType

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
BUNDLE_ROOT = "tts-platform"
DEFAULT_STARTUP_TIMEOUT_S = 30.0
DEFAULT_COMMAND_TIMEOUT_S = 180.0


class WindowsBundleInstallError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_windows_bundle_install")
    parser.add_argument("--bundle", default=None)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--startup-timeout-s", type=float, default=DEFAULT_STARTUP_TIMEOUT_S)
    parser.add_argument("--command-timeout-s", type=float, default=DEFAULT_COMMAND_TIMEOUT_S)
    parser.add_argument("--stream-text-repeat", type=int, default=2)
    parser.add_argument(
        "--install-real-runtime",
        action="store_true",
        help=(
            "Ask the extracted Windows installer to install the optional .[real] "
            "runtime dependencies before setup."
        ),
    )
    parser.add_argument(
        "--no-dependencies",
        action="store_true",
        help=(
            "Ask the extracted Windows installer to skip dependency installation. "
            "Use only for pre-provisioned test environments."
        ),
    )
    args = parser.parse_args(argv)

    try:
        if args.bundle:
            summary = check_windows_bundle_install(
                bundle_path=Path(args.bundle),
                python_executable=args.python_executable,
                startup_timeout_s=args.startup_timeout_s,
                command_timeout_s=args.command_timeout_s,
                stream_text_repeat=args.stream_text_repeat,
                install_real_runtime=args.install_real_runtime,
                install_dependencies=not args.no_dependencies,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="tts-platform-bundle-install-") as temp_dir:
                bundle_path = Path(temp_dir) / "tts-platform-local-reader.zip"
                package_windows_bundle.package_windows_bundle(out_path=bundle_path)
                summary = check_windows_bundle_install(
                    bundle_path=bundle_path,
                    python_executable=args.python_executable,
                    startup_timeout_s=args.startup_timeout_s,
                    command_timeout_s=args.command_timeout_s,
                    stream_text_repeat=args.stream_text_repeat,
                    install_real_runtime=args.install_real_runtime,
                    install_dependencies=not args.no_dependencies,
                )
    except WindowsBundleInstallError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_windows_bundle_install(
    *,
    bundle_path: Path,
    python_executable: str,
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
    command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
    stream_text_repeat: int = 2,
    install_real_runtime: bool = False,
    install_dependencies: bool = True,
) -> dict[str, object]:
    if stream_text_repeat <= 0:
        raise WindowsBundleInstallError("--stream-text-repeat must be positive.")

    resolved_bundle_path = bundle_path.expanduser().resolve()
    if not resolved_bundle_path.is_file():
        raise WindowsBundleInstallError(f"Bundle does not exist: {resolved_bundle_path}")

    with tempfile.TemporaryDirectory(prefix="tts-platform-bundle-install-extract-") as temp_dir:
        extract_root = Path(temp_dir)
        _extract_bundle(bundle_path=resolved_bundle_path, extract_root=extract_root)
        bundle_root = extract_root / BUNDLE_ROOT
        venv_dir = bundle_root / ".venv"
        installer_payload = _run_windows_install_script(
            python_executable=python_executable,
            bundle_root=bundle_root,
            timeout_s=command_timeout_s,
            install_real_runtime=install_real_runtime,
            install_dependencies=install_dependencies,
        )
        if installer_payload is None:
            _create_venv(
                python_executable=python_executable,
                venv_dir=venv_dir,
                timeout_s=command_timeout_s,
            )
        venv_python = _venv_python(venv_dir)
        tts_entrypoint = _venv_tts_entrypoint(venv_dir)
        if installer_payload is None:
            _install_build_tooling(
                venv_python=venv_python,
                bundle_root=bundle_root,
                timeout_s=command_timeout_s,
            )
            _install_bundle_package(
                venv_python=venv_python,
                bundle_root=bundle_root,
                timeout_s=command_timeout_s,
                install_dependencies=install_dependencies,
            )
            if install_real_runtime:
                _install_real_runtime(
                    venv_python=venv_python,
                    bundle_root=bundle_root,
                    timeout_s=command_timeout_s,
                )
        if not tts_entrypoint.is_file():
            raise WindowsBundleInstallError(
                f"Installed tts entrypoint is missing: {tts_entrypoint}"
            )

        if installer_payload is None:
            setup_payload = _run_json_command(
                [
                    str(tts_entrypoint),
                    "setup-local",
                    "--repo-root",
                    str(bundle_root),
                ],
                cwd=bundle_root,
                timeout_s=command_timeout_s,
            )
        else:
            setup_payload = _dict_payload(installer_payload.get("setup"), label="installer setup")
        token_file = Path(str(setup_payload.get("token_file", "")))
        if not token_file.is_file():
            raise WindowsBundleInstallError("Installed setup-local did not create a token file.")
        _assert_setup_next_steps(setup_payload)

        port = _reserve_loopback_port()
        base_url = f"http://127.0.0.1:{port}"
        service_process = subprocess.Popen(
            [
                str(tts_entrypoint),
                "serve",
                "--repo-root",
                str(bundle_root),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=bundle_root,
            env=_venv_env(venv_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_for_health(
                base_url=base_url,
                process=service_process,
                timeout_s=startup_timeout_s,
            )
            smoke_payload = _run_json_command(
                [
                    str(venv_python),
                    "scripts/smoke_service.py",
                    "--base-url",
                    base_url,
                    "--token-file",
                    str(token_file),
                    "--stream-text-repeat",
                    str(stream_text_repeat),
                    "--min-stream-text-chunks",
                    "1",
                ],
                cwd=bundle_root,
                timeout_s=command_timeout_s,
                env=_venv_env(venv_dir),
            )
        finally:
            _stop_process(service_process)

    return {
        "bundle_path": str(resolved_bundle_path),
        "venv": {
            "created": _installer_bool(installer_payload, "venv_created", fallback=True),
            "system_site_packages": True,
            "build_tooling_installed": _installer_bool(
                installer_payload,
                "build_tooling_installed",
                fallback=True,
            ),
            "dependencies_installed": _installer_bool(
                installer_payload,
                "dependencies_installed",
                fallback=install_dependencies,
            ),
            "editable_install": True,
            "real_runtime_installed": _installer_bool(
                installer_payload,
                "real_runtime_installed",
                fallback=install_real_runtime,
            ),
            "installer_script": installer_payload is not None,
            "entrypoint": _display_venv_path(tts_entrypoint),
        },
        "setup": {
            "config_created": setup_payload.get("config_created"),
            "token_created": setup_payload.get("token_created"),
            "default_voice": setup_payload.get("default_voice"),
            "manifest_default_voice": _dict_get(
                setup_payload.get("manifest"),
                "default_voice_in_manifest",
            ),
            "catalog_single_installable_model": _dict_get(
                setup_payload.get("catalog"),
                "single_installable_model_id",
            ),
            "next_steps": _string_list(setup_payload.get("next_steps")),
        },
        "service": _summarize_smoke(smoke_payload),
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


def _run_windows_install_script(
    *,
    python_executable: str,
    bundle_root: Path,
    timeout_s: float,
    install_real_runtime: bool,
    install_dependencies: bool,
) -> dict[str, object] | None:
    installer_path = bundle_root / "scripts" / "windows" / "install_local.ps1"
    if not installer_path.is_file():
        return None
    powershell_executable = _find_powershell_executable()
    if not powershell_executable:
        return None

    env = dict(os.environ)
    env["TTS_PLATFORM_PYTHON"] = python_executable
    env["PYTHONUNBUFFERED"] = "1"
    command = [
        powershell_executable,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(installer_path),
    ]
    if install_real_runtime:
        command.append("-InstallRealRuntime")
    if not install_dependencies:
        command.append("-NoDependencies")
    return _run_json_command(
        command,
        cwd=bundle_root,
        timeout_s=timeout_s,
        env=env,
    )


def _create_venv(*, python_executable: str, venv_dir: Path, timeout_s: float) -> None:
    _run_command(
        [
            python_executable,
            "-m",
            "venv",
            "--system-site-packages",
            str(venv_dir),
        ],
        cwd=venv_dir.parent,
        timeout_s=timeout_s,
    )


def _install_bundle_package(
    *,
    venv_python: Path,
    bundle_root: Path,
    timeout_s: float,
    install_dependencies: bool,
) -> None:
    command = [
        str(venv_python),
        "-m",
        "pip",
        "install",
        "--no-build-isolation",
    ]
    if not install_dependencies:
        command.append("--no-deps")
    command.extend(["-e", "."])
    _run_command(
        command,
        cwd=bundle_root,
        timeout_s=timeout_s,
        env=_venv_env(bundle_root / ".venv"),
    )


def _install_real_runtime(*, venv_python: Path, bundle_root: Path, timeout_s: float) -> None:
    _run_command(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            "-e",
            ".[real]",
        ],
        cwd=bundle_root,
        timeout_s=timeout_s,
        env=_venv_env(bundle_root / ".venv"),
    )


def _install_build_tooling(*, venv_python: Path, bundle_root: Path, timeout_s: float) -> None:
    _run_command(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "setuptools>=69",
            "wheel",
        ],
        cwd=bundle_root,
        timeout_s=timeout_s,
        env=_venv_env(bundle_root / ".venv"),
    )


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_s: float,
    env: dict[str, str] | None = None,
) -> None:
    try:
        subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout_s,
        )
    except subprocess.CalledProcessError as exc:
        raise WindowsBundleInstallError(
            _format_command_failure(command, stdout=exc.stdout, stderr=exc.stderr)
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise WindowsBundleInstallError(
            _format_command_failure(command, stdout=exc.stdout, stderr=exc.stderr)
            + f"\nCommand timed out after {timeout_s:.1f}s."
        ) from exc


def _find_powershell_executable() -> str | None:
    return (
        shutil.which("powershell.exe")
        or shutil.which("powershell")
        or shutil.which("pwsh.exe")
        or shutil.which("pwsh")
    )


def _run_json_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_s: float,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout_s,
        )
    except subprocess.CalledProcessError as exc:
        raise WindowsBundleInstallError(
            _format_command_failure(command, stdout=exc.stdout, stderr=exc.stderr)
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise WindowsBundleInstallError(
            _format_command_failure(command, stdout=exc.stdout, stderr=exc.stderr)
            + f"\nCommand timed out after {timeout_s:.1f}s."
        ) from exc

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WindowsBundleInstallError(
            _format_command_failure(
                command,
                stdout=completed.stdout,
                stderr=completed.stderr,
                prefix="Command did not emit JSON.",
            )
        ) from exc
    if not isinstance(payload, dict):
        raise WindowsBundleInstallError("Command JSON output must be an object.")
    return payload


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(
    *,
    base_url: str,
    process: subprocess.Popen[str],
    timeout_s: float,
) -> None:
    deadline = time.perf_counter() + timeout_s
    last_error = "service did not answer yet"
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise WindowsBundleInstallError(
                "Installed service exited before it became healthy.\n"
                + _format_process_output(stdout=stdout, stderr=stderr)
            )
        try:
            response = httpx.get(f"{base_url}/v1/health", timeout=1.0)
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, dict) and payload.get("status") == "ok":
                    return
                last_error = f"unexpected health payload: {payload!r}"
            else:
                last_error = f"HTTP {response.status_code}: {response.text}"
        except (httpx.HTTPError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise WindowsBundleInstallError(
        f"Timed out waiting for installed service health at {base_url}: {last_error}"
    )


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        process.communicate(timeout=1)
        return
    process.terminate()
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_tts_entrypoint(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "tts.exe"
    return venv_dir / "bin" / "tts"


def _venv_env(venv_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(venv_dir)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _summarize_smoke(payload: dict[str, object]) -> dict[str, object]:
    stream = payload.get("stream", {})
    return {
        "health": payload.get("health"),
        "voice": payload.get("voice"),
        "voices": payload.get("voices"),
        "http_bytes": _dict_get(payload.get("http", {}), "bytes"),
        "stream_frames": _dict_get(stream, "frames"),
        "job_status": _dict_get(payload.get("job", {}), "status"),
    }


def _dict_get(raw_payload: object, key: str) -> object:
    if not isinstance(raw_payload, dict):
        return None
    return raw_payload.get(key)


def _dict_payload(raw_payload: object, *, label: str) -> dict[str, object]:
    if not isinstance(raw_payload, dict):
        raise WindowsBundleInstallError(f"{label} payload must be a JSON object.")
    return raw_payload


def _assert_setup_next_steps(setup_payload: dict[str, object]) -> None:
    next_steps = _string_list(setup_payload.get("next_steps"))
    if "tts serve" not in next_steps:
        raise WindowsBundleInstallError(
            "Installed setup-local next steps do not include tts serve."
        )
    if "tts model-check" not in next_steps:
        raise WindowsBundleInstallError(
            "Installed setup-local next steps do not include tts model-check."
        )
    catalog = setup_payload.get("catalog")
    if not isinstance(catalog, dict) or catalog.get("exists") is not True:
        raise WindowsBundleInstallError(
            "Installed setup-local did not report the default catalog."
        )
    single_installable_model_id = str(
        catalog.get("single_installable_model_id") or ""
    ).strip()
    if not single_installable_model_id:
        raise WindowsBundleInstallError(
            "Installed setup-local default catalog did not expose one installable model."
        )
    expected_install_step = (
        f"tts model-install {single_installable_model_id} --activate"
    )
    if not next_steps or next_steps[0] != expected_install_step:
        raise WindowsBundleInstallError(
            "Installed setup-local did not put the default catalog install step first."
        )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _installer_bool(
    installer_payload: dict[str, object] | None,
    key: str,
    *,
    fallback: bool,
) -> bool:
    if installer_payload is None:
        return fallback
    return bool(installer_payload.get(key))


def _display_venv_path(path: Path) -> str:
    parts = path.parts
    if ".venv" in parts:
        index = parts.index(".venv")
        return str(Path(*parts[index:]))
    return path.name


def _format_command_failure(
    command: list[str],
    *,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
    prefix: str = "Command failed.",
) -> str:
    return (
        f"{prefix}\n"
        f"Command: {_display_command(command)}\n"
        f"{_format_process_output(stdout=stdout, stderr=stderr)}"
    )


def _format_process_output(
    *,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
) -> str:
    return "\n".join(
        [
            f"stdout: {_decode_output(stdout).strip()}",
            f"stderr: {_decode_output(stderr).strip()}",
        ]
    )


def _decode_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output


def _display_command(command: list[str]) -> str:
    return " ".join(command)


def _load_script_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package_windows_bundle = _load_script_module(
    "tts_platform_package_windows_bundle_for_install_check",
    SCRIPT_DIR / "package_windows_bundle.py",
)
check_windows_bundle_bootstrap = _load_script_module(
    "tts_platform_check_windows_bundle_bootstrap_for_install_check",
    SCRIPT_DIR / "check_windows_bundle_bootstrap.py",
)


if __name__ == "__main__":
    main()
