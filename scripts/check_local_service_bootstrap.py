from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"
DEFAULT_STARTUP_TIMEOUT_S = 30.0
DEFAULT_COMMAND_TIMEOUT_S = 60.0


class LocalServiceBootstrapError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_local_service_bootstrap")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--startup-timeout-s", type=float, default=DEFAULT_STARTUP_TIMEOUT_S)
    parser.add_argument("--command-timeout-s", type=float, default=DEFAULT_COMMAND_TIMEOUT_S)
    parser.add_argument("--stream-text-repeat", type=int, default=20)
    parser.add_argument("--min-stream-text-chunks", type=int, default=2)
    args = parser.parse_args(argv)

    try:
        summary = check_local_service_bootstrap(
            python_executable=args.python_executable,
            startup_timeout_s=args.startup_timeout_s,
            command_timeout_s=args.command_timeout_s,
            stream_text_repeat=args.stream_text_repeat,
            min_stream_text_chunks=args.min_stream_text_chunks,
        )
    except LocalServiceBootstrapError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_local_service_bootstrap(
    *,
    python_executable: str,
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
    command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
    stream_text_repeat: int = 20,
    min_stream_text_chunks: int = 2,
) -> dict[str, object]:
    if stream_text_repeat <= 0:
        raise LocalServiceBootstrapError("--stream-text-repeat must be positive.")
    if min_stream_text_chunks <= 0:
        raise LocalServiceBootstrapError("--min-stream-text-chunks must be positive.")

    with tempfile.TemporaryDirectory(prefix="tts-platform-local-service-") as temp_dir:
        temp_repo_root = Path(temp_dir) / "repo"
        _seed_temp_repo(temp_repo_root)

        env = _source_env()
        setup_payload = _run_json_command(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "setup-local",
                "--repo-root",
                str(temp_repo_root),
            ],
            env=env,
            timeout_s=command_timeout_s,
        )
        token_file = Path(str(setup_payload.get("token_file", "")))
        if not token_file.is_file():
            raise LocalServiceBootstrapError("setup-local did not create a token file.")

        port = _reserve_loopback_port()
        base_url = f"http://127.0.0.1:{port}"
        service_process = subprocess.Popen(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "serve",
                "--repo-root",
                str(temp_repo_root),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            env=env,
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
                env=env,
                timeout_s=command_timeout_s,
            )
        finally:
            _stop_process(service_process)

    return {
        "base_url": base_url,
        "setup": _summarize_setup(setup_payload),
        "smoke": _summarize_smoke(smoke_payload),
    }


def _seed_temp_repo(repo_root: Path) -> None:
    for relative_path in ("config/config.example.toml", "models/MANIFEST.json"):
        source = REPO_ROOT / relative_path
        destination = repo_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _source_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("TTS_PLATFORM")
    }
    python_path_entries = [str(SERVICE_SRC), str(CORE_SRC)]
    existing_python_path = env.get("PYTHONPATH")
    if existing_python_path:
        python_path_entries.append(existing_python_path)
    env["PYTHONPATH"] = os.pathsep.join(python_path_entries)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _run_json_command(
    command: list[str],
    *,
    env: dict[str, str],
    timeout_s: float,
) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout_s,
        )
    except subprocess.CalledProcessError as exc:
        raise LocalServiceBootstrapError(
            _format_command_failure(command, stdout=exc.stdout, stderr=exc.stderr)
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise LocalServiceBootstrapError(
            _format_command_failure(command, stdout=exc.stdout, stderr=exc.stderr)
            + f"\nCommand timed out after {timeout_s:.1f}s."
        ) from exc

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LocalServiceBootstrapError(
            _format_command_failure(
                command,
                stdout=completed.stdout,
                stderr=completed.stderr,
                prefix="Command did not emit JSON.",
            )
        ) from exc
    if not isinstance(payload, dict):
        raise LocalServiceBootstrapError("Command JSON output must be an object.")
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
            raise LocalServiceBootstrapError(
                "Service exited before it became healthy.\n"
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

    raise LocalServiceBootstrapError(
        f"Timed out waiting for local service health at {base_url}: {last_error}"
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


def _summarize_setup(payload: dict[str, object]) -> dict[str, object]:
    manifest = payload.get("manifest")
    manifest_default_voice = False
    if isinstance(manifest, dict):
        manifest_default_voice = bool(manifest.get("default_voice_in_manifest"))
    service = payload.get("service")
    configured_base_url = None
    if isinstance(service, dict):
        configured_base_url = service.get("base_url")
    return {
        "config_created": bool(payload.get("config_created")),
        "token_created": bool(payload.get("token_created")),
        "auth_enabled": bool(payload.get("auth_enabled")),
        "default_voice": payload.get("default_voice"),
        "configured_base_url": configured_base_url,
        "manifest_default_voice": manifest_default_voice,
    }


def _summarize_smoke(payload: dict[str, object]) -> dict[str, object]:
    stream = payload.get("stream", {})
    input_payload = payload.get("input", {})
    job = payload.get("job", {})
    return {
        "health": payload.get("health"),
        "voices": payload.get("voices"),
        "input": input_payload,
        "http": _audio_summary(payload.get("http", {})),
        "stream": {
            **_audio_summary(stream),
            "frames": _dict_get(stream, "frames"),
            "marks": _dict_get(stream, "marks"),
            "text_chunk_count": _dict_get(stream, "text_chunk_count"),
        },
        "job": {
            **_audio_summary(job),
            "status": _dict_get(job, "status"),
        },
    }


def _audio_summary(raw_payload: object) -> dict[str, object]:
    if not isinstance(raw_payload, dict):
        return {}
    return {
        "audio_duration_ms": raw_payload.get("audio_duration_ms"),
        "bytes": raw_payload.get("bytes"),
        "sample_rate_hz": raw_payload.get("sample_rate_hz"),
    }


def _dict_get(raw_payload: object, key: str) -> object:
    if not isinstance(raw_payload, dict):
        return None
    return raw_payload.get(key)


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


if __name__ == "__main__":
    main()
