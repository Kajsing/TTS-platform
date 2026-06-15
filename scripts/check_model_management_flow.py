from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"
MODEL_ID = "local-flow-voice"
DEFAULT_STARTUP_TIMEOUT_S = 30.0
DEFAULT_COMMAND_TIMEOUT_S = 60.0


class ModelManagementFlowError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_model_management_flow")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--startup-timeout-s", type=float, default=DEFAULT_STARTUP_TIMEOUT_S)
    parser.add_argument("--command-timeout-s", type=float, default=DEFAULT_COMMAND_TIMEOUT_S)
    parser.add_argument("--stream-text-repeat", type=int, default=2)
    args = parser.parse_args(argv)

    try:
        summary = check_model_management_flow(
            python_executable=args.python_executable,
            startup_timeout_s=args.startup_timeout_s,
            command_timeout_s=args.command_timeout_s,
            stream_text_repeat=args.stream_text_repeat,
        )
    except ModelManagementFlowError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_model_management_flow(
    *,
    python_executable: str,
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
    command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
    stream_text_repeat: int = 2,
) -> dict[str, object]:
    if stream_text_repeat <= 0:
        raise ModelManagementFlowError("--stream-text-repeat must be positive.")

    with tempfile.TemporaryDirectory(prefix="tts-platform-model-flow-") as temp_dir:
        temp_root = Path(temp_dir)
        repo_root = temp_root / "repo"
        catalog_root = temp_root / "catalog_server"
        catalog_path = catalog_root / "catalog.json"
        env = _source_env()
        _seed_temp_repo(repo_root)
        artifact = _write_local_model_artifact(catalog_root / "artifacts" / f"{MODEL_ID}.zip")
        _write_catalog(
            catalog_path=catalog_path,
            artifact=artifact,
            artifact_url=f"artifacts/{MODEL_ID}.zip",
        )
        default_catalog_artifact = _write_local_model_artifact(
            repo_root / "models" / "artifacts" / f"{MODEL_ID}.zip"
        )
        _write_catalog(
            catalog_path=repo_root / "models" / "catalog.json",
            artifact=default_catalog_artifact,
            artifact_url=f"artifacts/{MODEL_ID}.zip",
        )

        setup_payload = _run_json_command(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "setup-local",
                "--repo-root",
                str(repo_root),
            ],
            env=env,
            timeout_s=command_timeout_s,
        )
        token_file = Path(str(setup_payload.get("token_file", "")))
        if not token_file.is_file():
            raise ModelManagementFlowError("setup-local did not create a token file.")

        default_catalog_payload = _run_json_command(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "catalog-list",
            ],
            cwd=repo_root,
            env=env,
            timeout_s=command_timeout_s,
        )
        _assert_catalog_summary_metadata(
            default_catalog_payload,
            expected_artifact_bytes=int(default_catalog_artifact["bytes"]),
        )

        with _serve_catalog_root(catalog_root) as catalog_url:
            catalog_payload = _run_json_command(
                [
                    python_executable,
                    "-m",
                    "tts_service.cli",
                    "catalog-list",
                    "--catalog",
                    catalog_url,
                ],
                env=env,
                timeout_s=command_timeout_s,
            )
            _assert_catalog_summary_metadata(
                catalog_payload,
                expected_artifact_bytes=int(artifact["bytes"]),
            )
            install_payload = _run_json_command(
                [
                    python_executable,
                    "-m",
                    "tts_service.cli",
                    "model-install",
                    MODEL_ID,
                    "--catalog",
                    catalog_url,
                    "--models-root",
                    str(repo_root / "models" / "voices"),
                    "--manifest-path",
                    str(repo_root / "models" / "MANIFEST.json"),
                    "--config-path",
                    str(repo_root / "config" / "config.toml"),
                    "--activate",
                ],
                env=env,
                timeout_s=command_timeout_s,
            )
            _assert_install_artifact_metadata(
                install_payload,
                expected_artifact_bytes=int(artifact["bytes"]),
            )
        _assert_installed_repo_state(repo_root=repo_root)
        model_list_payload = _run_json_command(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "model-list",
                "--repo-root",
                str(repo_root),
                "--manifest-path",
                str(repo_root / "models" / "MANIFEST.json"),
                "--config-path",
                str(repo_root / "config" / "config.toml"),
            ],
            env=env,
            timeout_s=command_timeout_s,
        )
        model_check_payload = _run_json_command(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "model-check",
                MODEL_ID,
                "--repo-root",
                str(repo_root),
                "--manifest-path",
                str(repo_root / "models" / "MANIFEST.json"),
                "--config-path",
                str(repo_root / "config" / "config.toml"),
            ],
            env=env,
            timeout_s=command_timeout_s,
        )

        port = _reserve_loopback_port()
        base_url = f"http://127.0.0.1:{port}"
        service_process = _start_service(
            python_executable=python_executable,
            repo_root=repo_root,
            env=env,
            port=port,
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
                    "--voice",
                    MODEL_ID,
                    "--stream-text-repeat",
                    str(stream_text_repeat),
                ],
                env=env,
                timeout_s=command_timeout_s,
            )
        finally:
            _stop_process(service_process)

        remove_payload = _run_json_command(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "model-remove",
                MODEL_ID,
                "--models-root",
                str(repo_root / "models" / "voices"),
                "--manifest-path",
                str(repo_root / "models" / "MANIFEST.json"),
                "--config-path",
                str(repo_root / "config" / "config.toml"),
            ],
            env=env,
            timeout_s=command_timeout_s,
        )
        _assert_removed_repo_state(repo_root=repo_root)

    return {
        "model_id": MODEL_ID,
        "default_catalog": _summarize_default_catalog(default_catalog_payload),
        "catalog": _summarize_catalog(catalog_payload),
        "install": _summarize_install(install_payload),
        "model_list": _summarize_model_list(model_list_payload),
        "model_check": _summarize_model_check(model_check_payload),
        "service": _summarize_smoke(smoke_payload),
        "remove": _summarize_remove(remove_payload),
    }


def _seed_temp_repo(repo_root: Path) -> None:
    config_source = REPO_ROOT / "config" / "config.example.toml"
    config_destination = repo_root / "config" / "config.example.toml"
    config_destination.parent.mkdir(parents=True, exist_ok=True)
    config_destination.write_bytes(config_source.read_bytes())
    _write_seed_manifest(repo_root / "models" / "MANIFEST.json")


def _write_seed_manifest(manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "voices": [
                    {
                        "id": "sherpa-en-debug",
                        "name": "Sherpa English Debug",
                        "engine": "sherpa_onnx",
                        "language": "en",
                        "sample_rate_hz": 24000,
                        "license": "development-only",
                        "source": "models/voices/sherpa-en-debug",
                        "quality_tier": "development",
                        "latency_tier": "unknown",
                        "tags": ["stub", "debug"],
                        "capabilities": {
                            "supports_pitch": False,
                            "supports_streaming": False,
                            "supports_multi_speaker": False,
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_local_model_artifact(artifact_path: Path) -> dict[str, object]:
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(artifact_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("model.onnx", "local flow fake model")
        archive.writestr("tokens.txt", "a\nb\nc\n")
        archive.writestr("README.txt", "Local model-management flow test artifact.\n")
    artifact_bytes = artifact_path.read_bytes()
    return {
        "path": artifact_path,
        "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "bytes": len(artifact_bytes),
    }


def _write_catalog(
    *,
    catalog_path: Path,
    artifact: dict[str, object],
    artifact_url: str | None = None,
) -> None:
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": MODEL_ID,
                        "name": "Local Flow Voice",
                        "language": "en",
                        "engine": "sherpa_onnx",
                        "sample_rate_hz": 24000,
                        "license": "test-only",
                        "license_url": "https://example.test/license",
                        "source_url": "https://example.test/source",
                        "upstream_url": "https://example.test/upstream",
                        "quality_tier": "development",
                        "latency_tier": "local",
                        "artifact_url": artifact_url or str(artifact["path"]),
                        "artifact_sha256": artifact["sha256"],
                        "artifact_size_bytes": artifact["bytes"],
                        "tags": ["local-flow", "test"],
                        "capabilities": {
                            "supports_pitch": False,
                            "supports_streaming": True,
                            "supports_multi_speaker": False,
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@contextmanager
def _serve_catalog_root(catalog_root: Path) -> Iterator[str]:
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

    handler = partial(QuietHandler, directory=str(catalog_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        yield f"http://127.0.0.1:{port}/catalog.json"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
    cwd: Path = REPO_ROOT,
    env: dict[str, str],
    timeout_s: float,
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
        raise ModelManagementFlowError(
            _format_command_failure(command, stdout=exc.stdout, stderr=exc.stderr)
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ModelManagementFlowError(
            _format_command_failure(command, stdout=exc.stdout, stderr=exc.stderr)
            + f"\nCommand timed out after {timeout_s:.1f}s."
        ) from exc

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ModelManagementFlowError(
            _format_command_failure(
                command,
                stdout=completed.stdout,
                stderr=completed.stderr,
                prefix="Command did not emit JSON.",
            )
        ) from exc
    if not isinstance(payload, dict):
        raise ModelManagementFlowError("Command JSON output must be an object.")
    return payload


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_service(
    *,
    python_executable: str,
    repo_root: Path,
    env: dict[str, str],
    port: int,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            python_executable,
            "-m",
            "tts_service.cli",
            "serve",
            "--repo-root",
            str(repo_root),
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
            raise ModelManagementFlowError(
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
    raise ModelManagementFlowError(
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


def _assert_installed_repo_state(*, repo_root: Path) -> None:
    model_dir = repo_root / "models" / "voices" / MODEL_ID
    if not (model_dir / "model.onnx").is_file() or not (model_dir / "tokens.txt").is_file():
        raise ModelManagementFlowError("Installed model files are missing.")
    config_text = (repo_root / "config" / "config.toml").read_text(encoding="utf-8")
    if f'default_voice = "{MODEL_ID}"' not in config_text:
        raise ModelManagementFlowError("model-install --activate did not update config.")
    manifest_payload = json.loads(
        (repo_root / "models" / "MANIFEST.json").read_text(encoding="utf-8")
    )
    voice_ids = [
        voice.get("id")
        for voice in manifest_payload.get("voices", [])
        if isinstance(voice, dict)
    ]
    if MODEL_ID not in voice_ids:
        raise ModelManagementFlowError("Installed model is missing from manifest.")


def _assert_removed_repo_state(*, repo_root: Path) -> None:
    if (repo_root / "models" / "voices" / MODEL_ID).exists():
        raise ModelManagementFlowError("model-remove did not delete the model directory.")
    manifest_payload = json.loads(
        (repo_root / "models" / "MANIFEST.json").read_text(encoding="utf-8")
    )
    voice_ids = [
        voice.get("id")
        for voice in manifest_payload.get("voices", [])
        if isinstance(voice, dict)
    ]
    if MODEL_ID in voice_ids:
        raise ModelManagementFlowError("model-remove did not delete the manifest entry.")


def _assert_catalog_summary_metadata(
    payload: dict[str, object],
    *,
    expected_artifact_bytes: int,
) -> None:
    summaries = payload.get("model_summaries")
    if not isinstance(summaries, list) or not summaries:
        raise ModelManagementFlowError("catalog-list did not report model summaries.")
    summary = next(
        (
            candidate
            for candidate in summaries
            if isinstance(candidate, dict) and candidate.get("id") == MODEL_ID
        ),
        None,
    )
    if summary is None:
        raise ModelManagementFlowError("catalog-list did not summarize the flow model.")
    expected_fields = {
        "artifact_size_bytes": expected_artifact_bytes,
        "artifact_size_mib": round(expected_artifact_bytes / (1024 * 1024), 1),
        "license_url": "https://example.test/license",
        "source_url": "https://example.test/source",
        "upstream_url": "https://example.test/upstream",
        "tags": ["local-flow", "test"],
        "capabilities": {
            "supports_pitch": False,
            "supports_streaming": True,
            "supports_multi_speaker": False,
        },
    }
    for field, expected_value in expected_fields.items():
        if summary.get(field) != expected_value:
            raise ModelManagementFlowError(
                f"catalog-list summary field {field!r} was not preserved."
            )


def _assert_install_artifact_metadata(
    payload: dict[str, object],
    *,
    expected_artifact_bytes: int,
) -> None:
    expected_fields = {
        "artifact_bytes": expected_artifact_bytes,
        "artifact_size_mib": round(expected_artifact_bytes / (1024 * 1024), 1),
        "catalog_artifact_size_bytes": expected_artifact_bytes,
        "catalog_artifact_size_matches": True,
    }
    for field, expected_value in expected_fields.items():
        if payload.get(field) != expected_value:
            raise ModelManagementFlowError(
                f"model-install result field {field!r} was not preserved."
            )


def _summarize_catalog(payload: dict[str, object]) -> dict[str, object]:
    catalog = payload.get("catalog", {})
    source = str(_dict_get(catalog, "source") or "")
    return {
        "source": "local_http" if source.startswith("http://127.0.0.1:") else "other",
        "model_count": _dict_get(catalog, "model_count"),
        "installable_count": _dict_get(catalog, "installable_count"),
        "checksum_count": _dict_get(catalog, "checksum_count"),
        "warnings": payload.get("warnings"),
    }


def _summarize_default_catalog(payload: dict[str, object]) -> dict[str, object]:
    catalog = payload.get("catalog", {})
    return {
        "source": _dict_get(catalog, "source"),
        "model_count": _dict_get(catalog, "model_count"),
        "installable_count": _dict_get(catalog, "installable_count"),
        "checksum_count": _dict_get(catalog, "checksum_count"),
        "next_steps": payload.get("next_steps"),
    }


def _summarize_install(payload: dict[str, object]) -> dict[str, object]:
    return {
        "installed_model": payload.get("installed_model"),
        "activated_model": payload.get("activated_model"),
        "artifact_bytes": payload.get("artifact_bytes"),
        "catalog_artifact_size_matches": payload.get("catalog_artifact_size_matches"),
        "files_installed": payload.get("files_installed"),
        "checksum_verified": payload.get("checksum_verified"),
        "install_steps": [
            step.get("step")
            for step in payload.get("install_steps", [])
            if isinstance(step, dict)
        ],
    }


def _summarize_model_list(payload: dict[str, object]) -> dict[str, object]:
    models = [
        model
        for model in payload.get("models", [])
        if isinstance(model, dict)
    ]
    default_model = next(
        (model for model in models if model.get("is_default") is True),
        None,
    )
    manifest = payload.get("manifest", {})
    catalog = payload.get("catalog", {})
    runtime = payload.get("runtime", {})
    return {
        "default_voice": payload.get("default_voice"),
        "manifest_voice_count": _dict_get(manifest, "voice_count"),
        "default_voice_in_manifest": _dict_get(
            manifest,
            "default_voice_in_manifest",
        ),
        "model_ids": [model.get("id") for model in models],
        "default_model_id": _dict_get(default_model, "id"),
        "default_model_has_backend_config": _dict_get(
            default_model,
            "has_backend_config",
        ),
        "default_catalog_exists": _dict_get(catalog, "exists"),
        "real_mode_enabled": _dict_get(runtime, "real_mode_enabled"),
        "sherpa_onnx_installed": _dict_get(runtime, "sherpa_onnx_installed"),
        "numpy_installed": _dict_get(runtime, "numpy_installed"),
        "next_steps": payload.get("next_steps"),
    }


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


def _summarize_model_check(payload: dict[str, object]) -> dict[str, object]:
    manifest = payload.get("manifest", {})
    backend = payload.get("backend", {})
    runtime = payload.get("runtime", {})
    catalog = payload.get("catalog", {})
    return {
        "ready": payload.get("ready"),
        "model_id": payload.get("model_id"),
        "voice_found": _dict_get(manifest, "voice_found"),
        "backend_configured": _dict_get(backend, "configured"),
        "assets_ready": _dict_get(backend, "assets_ready"),
        "real_mode_enabled": _dict_get(runtime, "real_mode_enabled"),
        "sherpa_onnx_installed": _dict_get(runtime, "sherpa_onnx_installed"),
        "numpy_installed": _dict_get(runtime, "numpy_installed"),
        "default_catalog_exists": _dict_get(catalog, "exists"),
        "next_steps": payload.get("next_steps"),
    }


def _summarize_remove(payload: dict[str, object]) -> dict[str, object]:
    return {
        "model_id": payload.get("model_id"),
        "removed_files": payload.get("removed_files"),
        "removed_manifest_entry": payload.get("removed_manifest_entry"),
        "active_default_voice": payload.get("active_default_voice"),
        "warning": payload.get("warning"),
        "next_steps": payload.get("next_steps"),
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
