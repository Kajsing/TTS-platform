from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"

for path in (SERVICE_SRC, CORE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tts_core.audio import inspect_wav  # noqa: E402

DEFAULT_DEMO_ROOT = REPO_ROOT / "dist" / "real-demo"
DEFAULT_MODEL_ID = "vits-piper-en_US-lessac-medium"
DEFAULT_TEXT = (
    "Hello. This is the local TTS platform, running an English Lessac voice "
    "through sherpa onnx. It is ready for reading long web articles from the "
    "Chrome extension."
)


class RealVoiceDemoError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="demo_real_voice")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--demo-root", default=str(DEFAULT_DEMO_ROOT))
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--out", default=None)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--startup-timeout-s", type=float, default=120.0)
    parser.add_argument("--command-timeout-s", type=float, default=600.0)
    parser.add_argument("--stream-text-repeat", type=int, default=20)
    parser.add_argument("--min-stream-text-chunks", type=int, default=2)
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--force-install", action="store_true")
    args = parser.parse_args(argv)

    try:
        summary = run_real_voice_demo(
            python_executable=args.python_executable,
            demo_root=Path(args.demo_root),
            model_id=args.model_id,
            out_path=Path(args.out) if args.out else None,
            text=args.text,
            port=args.port,
            startup_timeout_s=args.startup_timeout_s,
            command_timeout_s=args.command_timeout_s,
            stream_text_repeat=args.stream_text_repeat,
            min_stream_text_chunks=args.min_stream_text_chunks,
            skip_smoke=args.skip_smoke,
            force_install=args.force_install,
        )
    except RealVoiceDemoError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def run_real_voice_demo(
    *,
    python_executable: str,
    demo_root: Path,
    model_id: str,
    out_path: Path | None,
    text: str,
    port: int,
    startup_timeout_s: float,
    command_timeout_s: float,
    stream_text_repeat: int,
    min_stream_text_chunks: int,
    skip_smoke: bool,
    force_install: bool,
) -> dict[str, object]:
    if not model_id.strip():
        raise RealVoiceDemoError("--model-id must not be empty.")
    if not text.strip():
        raise RealVoiceDemoError("--text must not be empty.")
    if startup_timeout_s <= 0:
        raise RealVoiceDemoError("--startup-timeout-s must be positive.")
    if command_timeout_s <= 0:
        raise RealVoiceDemoError("--command-timeout-s must be positive.")
    if stream_text_repeat <= 0:
        raise RealVoiceDemoError("--stream-text-repeat must be positive.")
    if min_stream_text_chunks <= 0:
        raise RealVoiceDemoError("--min-stream-text-chunks must be positive.")

    resolved_demo_root = demo_root.expanduser().resolve()
    resolved_out_path = (
        out_path.expanduser().resolve()
        if out_path is not None
        else resolved_demo_root / "lessac-demo.wav"
    )
    env = _source_env()

    seed_summary = _seed_demo_root(resolved_demo_root)
    setup_payload = _run_json_command(
        [
            python_executable,
            "-m",
            "tts_service.cli",
            "setup-local",
            "--repo-root",
            str(resolved_demo_root),
            "--config-path",
            "config/config.toml",
            "--example-config-path",
            "config/config.example.toml",
            "--manifest-path",
            "models/MANIFEST.json",
        ],
        env=env,
        timeout_s=command_timeout_s,
    )
    token_file = Path(str(setup_payload.get("token_file", "")))
    if not token_file.is_file():
        raise RealVoiceDemoError("setup-local did not create a token file.")

    before_check = _run_model_check(
        python_executable=python_executable,
        demo_root=resolved_demo_root,
        model_id=model_id,
        env=env,
        timeout_s=command_timeout_s,
    )
    install_payload: dict[str, object] | None = None
    if force_install or _model_install_needed(before_check):
        install_payload = _install_model(
            python_executable=python_executable,
            demo_root=resolved_demo_root,
            model_id=model_id,
            env=env,
            timeout_s=command_timeout_s,
            overwrite=force_install,
        )

    model_check = _run_model_check(
        python_executable=python_executable,
        demo_root=resolved_demo_root,
        model_id=model_id,
        env=env,
        timeout_s=command_timeout_s,
    )
    if model_check.get("ready") is not True:
        raise RealVoiceDemoError(
            "Real voice is not ready after setup/install:\n"
            + json.dumps(model_check, indent=2, sort_keys=True)
        )

    resolved_port = port if port > 0 else _reserve_loopback_port()
    base_url = f"http://127.0.0.1:{resolved_port}"
    service_process = _start_service(
        python_executable=python_executable,
        demo_root=resolved_demo_root,
        port=resolved_port,
        env=env,
    )
    try:
        health = _wait_for_health(
            base_url=base_url,
            process=service_process,
            timeout_s=startup_timeout_s,
        )
        smoke_payload = None
        if not skip_smoke:
            smoke_payload = _run_smoke(
                python_executable=python_executable,
                base_url=base_url,
                token_file=token_file,
                model_id=model_id,
                stream_text_repeat=stream_text_repeat,
                min_stream_text_chunks=min_stream_text_chunks,
                env=env,
                timeout_s=command_timeout_s,
            )
        wav_summary = _write_demo_wav(
            base_url=base_url,
            token_file=token_file,
            model_id=model_id,
            text=text,
            out_path=resolved_out_path,
        )
    finally:
        _stop_process_tree(service_process)

    return {
        "demo_root": str(resolved_demo_root),
        "model_id": model_id,
        "seed": seed_summary,
        "setup": _summarize_setup(setup_payload),
        "install": _summarize_install(install_payload),
        "model_check": {
            "ready": model_check.get("ready"),
            "default_voice": _dict_get(model_check, "config", "default_voice"),
            "sherpa_onnx_installed": _dict_get(
                model_check, "runtime", "sherpa_onnx_installed"
            ),
            "numpy_installed": _dict_get(model_check, "runtime", "numpy_installed"),
            "assets_ready": _dict_get(model_check, "backend", "assets_ready"),
        },
        "service": {
            "base_url": base_url,
            "health": {
                "status": health.get("status"),
                "backend_ready": _dict_get(health, "checks", "backend_ready"),
                "default_voice_loaded": _dict_get(
                    health, "checks", "default_voice_loaded"
                ),
                "default_voice": health.get("default_voice"),
            },
            "stderr_log": str(resolved_demo_root / "service.err.log"),
            "stdout_log": str(resolved_demo_root / "service.out.log"),
        },
        "smoke": _summarize_smoke(smoke_payload),
        "wav": wav_summary,
    }


def _seed_demo_root(demo_root: Path) -> dict[str, object]:
    copied: list[str] = []
    for relative_path in (
        Path("config/config.example.toml"),
        Path("models/catalog.json"),
        Path("models/MANIFEST.json"),
    ):
        source = REPO_ROOT / relative_path
        target = demo_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source, target)
            copied.append(relative_path.as_posix())
    return {
        "created_root": demo_root.exists(),
        "copied_files": copied,
        "config_example": str(demo_root / "config" / "config.example.toml"),
        "catalog": str(demo_root / "models" / "catalog.json"),
        "manifest": str(demo_root / "models" / "MANIFEST.json"),
    }


def _run_model_check(
    *,
    python_executable: str,
    demo_root: Path,
    model_id: str,
    env: dict[str, str],
    timeout_s: float,
) -> dict[str, object]:
    return _run_json_command(
        [
            python_executable,
            "-m",
            "tts_service.cli",
            "model-check",
            model_id,
            "--repo-root",
            str(demo_root),
            "--manifest-path",
            "models/MANIFEST.json",
            "--config-path",
            "config/config.toml",
        ],
        env=env,
        timeout_s=timeout_s,
    )


def _install_model(
    *,
    python_executable: str,
    demo_root: Path,
    model_id: str,
    env: dict[str, str],
    timeout_s: float,
    overwrite: bool,
) -> dict[str, object]:
    command = [
        python_executable,
        "-m",
        "tts_service.cli",
        "model-install",
        model_id,
        "--catalog",
        str(demo_root / "models" / "catalog.json"),
        "--models-root",
        str(demo_root / "models" / "voices"),
        "--manifest-path",
        str(demo_root / "models" / "MANIFEST.json"),
        "--config-path",
        str(demo_root / "config" / "config.toml"),
        "--activate",
    ]
    if overwrite:
        command.append("--overwrite")
    return _run_json_command(command, env=env, timeout_s=timeout_s)


def _model_install_needed(model_check: dict[str, object]) -> bool:
    if model_check.get("ready") is True:
        return False
    return (
        _dict_get(model_check, "manifest", "voice_found") is not True
        or _dict_get(model_check, "backend", "configured") is not True
        or _dict_get(model_check, "backend", "assets_ready") is not True
    )


def _start_service(
    *,
    python_executable: str,
    demo_root: Path,
    port: int,
    env: dict[str, str],
) -> subprocess.Popen:
    stdout_path = demo_root / "service.out.log"
    stderr_path = demo_root / "service.err.log"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_file = stdout_path.open("w", encoding="utf-8")
    stderr_file = stderr_path.open("w", encoding="utf-8")
    try:
        return subprocess.Popen(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "serve",
                "--repo-root",
                str(demo_root),
                "--config-path",
                "config/config.toml",
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )
    finally:
        stdout_file.close()
        stderr_file.close()


def _wait_for_health(
    *,
    base_url: str,
    process: subprocess.Popen,
    timeout_s: float,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    last_error: str | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RealVoiceDemoError(
                f"Service exited before becoming ready with code {process.returncode}."
            )
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(f"{base_url}/v1/health")
                response.raise_for_status()
                payload = response.json()
            if isinstance(payload, dict) and payload.get("status") == "ok":
                return payload
            last_error = f"health was not ok: {payload!r}"
        except (httpx.HTTPError, OSError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RealVoiceDemoError(f"Timed out waiting for service health: {last_error}")


def _run_smoke(
    *,
    python_executable: str,
    base_url: str,
    token_file: Path,
    model_id: str,
    stream_text_repeat: int,
    min_stream_text_chunks: int,
    env: dict[str, str],
    timeout_s: float,
) -> dict[str, object]:
    return _run_json_command(
        [
            python_executable,
            str(REPO_ROOT / "scripts" / "smoke_service.py"),
            "--base-url",
            base_url,
            "--token-file",
            str(token_file),
            "--voice",
            model_id,
            "--stream-text-repeat",
            str(stream_text_repeat),
            "--min-stream-text-chunks",
            str(min_stream_text_chunks),
        ],
        env=env,
        timeout_s=timeout_s,
    )


def _write_demo_wav(
    *,
    base_url: str,
    token_file: Path,
    model_id: str,
    text: str,
    out_path: Path,
) -> dict[str, object]:
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise RealVoiceDemoError("Token file is empty.")
    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            f"{base_url}/v1/tts",
            json={"text": text, "voice": model_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        audio_bytes = response.content
    stats = inspect_wav(audio_bytes)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio_bytes)
    return {
        "path": str(out_path),
        "bytes": len(audio_bytes),
        "duration_ms": stats.duration_ms,
        "sample_rate_hz": stats.sample_rate_hz,
        "channels": stats.channels,
    }


def _run_json_command(
    command: list[str],
    *,
    env: dict[str, str],
    timeout_s: float,
) -> dict[str, object]:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    if completed.returncode != 0:
        raise RealVoiceDemoError(
            "Command failed:\n"
            + " ".join(command)
            + f"\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RealVoiceDemoError(
            "Command did not return JSON:\n"
            + " ".join(command)
            + f"\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        ) from exc
    if not isinstance(payload, dict):
        raise RealVoiceDemoError("Command returned JSON that is not an object.")
    return payload


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _stop_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _source_env() -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(SERVICE_SRC), str(CORE_SRC)]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _summarize_setup(payload: dict[str, object]) -> dict[str, object]:
    return {
        "config_created": payload.get("config_created"),
        "token_created": payload.get("token_created"),
        "default_voice": payload.get("default_voice"),
        "runtime": payload.get("runtime"),
        "next_steps": payload.get("next_steps"),
    }


def _summarize_install(payload: dict[str, object] | None) -> dict[str, object]:
    if payload is None:
        return {"performed": False}
    return {
        "performed": True,
        "installed_model": payload.get("installed_model"),
        "activated_model": payload.get("activated_model"),
        "checksum_verified": payload.get("checksum_verified"),
        "files_installed": payload.get("files_installed"),
    }


def _summarize_smoke(payload: dict[str, object] | None) -> dict[str, object] | None:
    if payload is None:
        return None
    return {
        "health": payload.get("health"),
        "http": payload.get("http"),
        "stream": payload.get("stream"),
        "job": payload.get("job"),
        "voice": payload.get("voice"),
    }


def _dict_get(payload: dict[str, object], *keys: str) -> object:
    current: object = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


if __name__ == "__main__":
    main()
