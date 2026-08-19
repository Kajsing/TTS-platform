from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"
READER_CORE_SRC = REPO_ROOT / "packages" / "reader_core" / "src"
DOCUMENT_IMPORT_SRC = REPO_ROOT / "packages" / "document_import" / "src"
SPEECH_RULES_SRC = REPO_ROOT / "packages" / "speech_rules" / "src"
DOTNET_PROBE_PROJECT = (
    REPO_ROOT
    / "scripts"
    / "windows"
    / "reader_secure_transport_probe"
    / "ReaderSecureTransportProbe.csproj"
)
DOTNET_PROBE_DLL = (
    DOTNET_PROBE_PROJECT.parent
    / "bin"
    / "Release"
    / "net10.0"
    / "ReaderSecureTransportProbe.dll"
)
TLS12_CIPHERS = (
    "ECDHE-ECDSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-CHACHA20-POLY1305"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Prove pinned HTTPS and WSS Reader traffic on Windows without enabling "
            "remote binding."
        )
    )
    parser.add_argument("--require-windows", action="store_true")
    parser.add_argument("--dotnet-executable", default="dotnet")
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    args = parser.parse_args()

    if os.name != "nt":
        if args.require_windows:
            raise SystemExit("The secure Reader transport spike requires Windows.")
        print(json.dumps({"status": "skipped", "reason": "windows-required"}, indent=2))
        return

    dotnet = shutil.which(args.dotnet_executable)
    if dotnet is None:
        raise SystemExit(f"The .NET executable was not found: {args.dotnet_executable}")
    summary = check_reader_secure_transport(
        python_executable=sys.executable,
        dotnet_executable=dotnet,
        startup_timeout_s=args.startup_timeout,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def check_reader_secure_transport(
    *,
    python_executable: str,
    dotnet_executable: str,
    startup_timeout_s: float,
) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("The secure Reader transport spike must run on Windows.")
    if startup_timeout_s <= 0:
        raise ValueError("startup_timeout_s must be positive")

    _build_dotnet_probe(dotnet_executable)
    with tempfile.TemporaryDirectory(prefix="tts-reader-u7-tls-") as temp_name:
        temp_root = Path(temp_name).resolve()
        layout = _write_spike_layout(temp_root)
        generated = _run_probe_command(
            dotnet_executable,
            ["generate", str(layout["certificate_directory"])],
        )
        certificate_path = Path(str(generated["certificate_path"])).resolve()
        private_key_path = Path(str(generated["private_key_path"])).resolve()
        pin = str(generated["spki_pin"])
        port = _reserve_loopback_port()
        base_url = f"https://localhost:{port}/"
        command = _server_command(
            python_executable=python_executable,
            port=port,
            certificate_path=certificate_path,
            private_key_path=private_key_path,
        )
        env = _source_env()
        env["TTS_READER_SPIKE_CONFIG"] = str(layout["config_path"])
        env["TTS_READER_SPIKE_REPO_ROOT"] = str(layout["repo_root"])
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log_path = temp_root / "service.log"
        with log_path.open("w+", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )
            try:
                _wait_for_tls(
                    host="localhost",
                    port=port,
                    certificate_path=certificate_path,
                    process=process,
                    timeout_s=startup_timeout_s,
                )
                wrong_pin = "sha256/" + ("A" * 43) + "="
                wrong_pin_result = _probe_wrong_pin_transports(
                    dotnet_executable,
                    base_url=base_url,
                    pin=wrong_pin,
                    token_file=Path(str(layout["token_path"])),
                )
                tls_protocols = _required_tls_protocols(
                    host="localhost",
                    port=port,
                    certificate_path=certificate_path,
                )
                probe = _run_probe_command(
                    dotnet_executable,
                    ["probe", base_url, pin, str(layout["token_path"])],
                )
                plain_http_rejected = _plain_http_is_rejected("localhost", port)
                if not plain_http_rejected:
                    raise RuntimeError("The TLS listener unexpectedly accepted plain HTTP.")
            except Exception as error:
                log_file.flush()
                log_file.seek(0)
                tail = log_file.read()[-4000:].strip()
                if tail:
                    raise RuntimeError(f"{error}\nSecure transport service log:\n{tail}") from error
                raise
            finally:
                _stop_process(process)

        return {
            "status": "ok",
            "platform": "windows",
            "transport": {
                "bind_host": "127.0.0.1",
                "remote_binding_enabled": False,
                "https": True,
                "wss": True,
                "plain_http_rejected": plain_http_rejected,
                "tls_protocol": probe["tls_protocol"],
                "required_tls_protocols": tls_protocols,
            },
            "certificate": {
                "algorithm": generated["algorithm"],
                "pin_type": "sha256-subject-public-key-info",
                "pin_enforced": True,
                "https_wrong_pin_rejected": wrong_pin_result[
                    "https_wrong_pin_rejected"
                ],
                "wss_wrong_pin_rejected": wrong_pin_result["wss_wrong_pin_rejected"],
                "subject_alternative_names": generated["subject_alternative_names"],
            },
            "reader_http": {
                "capabilities": probe["https_reader_capabilities"],
                "temporary_document_created": probe["https_reader_document_created"],
            },
            "reader_websocket": {
                "started": probe["wss_reader_started"],
                "marks": probe["wss_reader_marks"],
                "audio_bytes": probe["wss_reader_audio_bytes"],
                "completed": probe["wss_reader_completed"],
            },
            "cleanup": {
                "temporary_reader_home_removed": True,
                "temporary_certificate_removed": True,
                "firewall_changed": False,
            },
        }


def create_spike_app():
    from tts_service.config import load_config
    from tts_service.main import create_app

    config_path = Path(os.environ["TTS_READER_SPIKE_CONFIG"]).resolve()
    repo_root = Path(os.environ["TTS_READER_SPIKE_REPO_ROOT"]).resolve()
    return create_app(config=load_config(config_path), repo_root=repo_root)


def _write_spike_layout(temp_root: Path) -> dict[str, Path]:
    repo_root = temp_root / "isolated-repo"
    config_path = repo_root / "config" / "config.toml"
    token_path = repo_root / "config" / "token.txt"
    manifest_path = repo_root / "models" / "MANIFEST.json"
    reader_home = temp_root / "reader-home"
    certificate_directory = temp_root / "certificate"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    reader_home.mkdir(parents=True, exist_ok=True)
    certificate_directory.mkdir(parents=True, exist_ok=True)

    token_path.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
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
    config_path.write_text(
        "\n".join(
            [
                "[server]",
                'host = "127.0.0.1"',
                "port = 7777",
                'log_level = "warning"',
                "",
                "[auth]",
                "enabled = true",
                f"token_file = {json.dumps(str(token_path))}",
                "",
                "[tts]",
                'default_voice = "sherpa-en-debug"',
                "max_chars_per_request = 4000",
                "max_chars_per_stream = 48000",
                "warmup_on_start = false",
                "",
                "[streaming]",
                "enabled = true",
                "audio_frame_ms = 40",
                "prebuffer_ms = 200",
                "",
                "[security]",
                "allowed_origins = []",
                "",
                "[backend]",
                'mode = "stub"',
                'provider = "cpu"',
                "num_threads = 1",
                "",
                "[reader]",
                "enabled = true",
                f"home_path = {json.dumps(str(reader_home))}",
                'database_path = "reader.db"',
                'managed_files_path = "library"',
                "",
                "[reader.exports]",
                "enabled = true",
                f"output_directory = {json.dumps(str(reader_home / 'exports'))}",
                "max_concurrent_exports = 1",
                'formats = ["wav"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "repo_root": repo_root,
        "config_path": config_path,
        "token_path": token_path,
        "reader_home": reader_home,
        "certificate_directory": certificate_directory,
    }


def _source_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "TTS_PLATFORM_TOKEN"
        and not key.startswith("TTS_PLATFORM__")
        and not key.startswith("UVICORN_")
        and key not in {"TTS_READER_SPIKE_CONFIG", "TTS_READER_SPIKE_REPO_ROOT"}
    }
    python_paths = [
        str(REPO_ROOT),
        str(SERVICE_SRC),
        str(CORE_SRC),
        str(READER_CORE_SRC),
        str(DOCUMENT_IMPORT_SRC),
        str(SPEECH_RULES_SRC),
    ]
    existing = env.get("PYTHONPATH")
    if existing:
        python_paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    return env


def _server_command(
    *,
    python_executable: str,
    port: int,
    certificate_path: Path,
    private_key_path: Path,
) -> list[str]:
    return [
        python_executable,
        "-m",
        "uvicorn",
        "scripts.check_reader_secure_transport:create_spike_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ssl-certfile",
        str(certificate_path),
        "--ssl-keyfile",
        str(private_key_path),
        "--ssl-ciphers",
        TLS12_CIPHERS,
        "--log-level",
        "warning",
        "--no-server-header",
    ]


def _build_dotnet_probe(dotnet_executable: str) -> None:
    completed = subprocess.run(
        [
            dotnet_executable,
            "build",
            str(DOTNET_PROBE_PROJECT),
            "--configuration",
            "Release",
            "--nologo",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not DOTNET_PROBE_DLL.is_file():
        output = f"{completed.stdout}\n{completed.stderr}".strip()
        raise RuntimeError(f"The .NET secure transport probe did not build.\n{output}")


def _run_probe_command(dotnet_executable: str, arguments: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        [dotnet_executable, str(DOTNET_PROBE_DLL), *arguments],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        output = f"{completed.stdout}\n{completed.stderr}".strip()
        raise RuntimeError(f"The .NET secure transport probe failed.\n{output}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("The .NET secure transport probe returned invalid JSON.")
    return payload


def _probe_wrong_pin_transports(
    dotnet_executable: str,
    *,
    base_url: str,
    pin: str,
    token_file: Path,
) -> dict[str, Any]:
    payload = _run_probe_command(
        dotnet_executable,
        ["reject-pin", base_url, pin, str(token_file)],
    )
    if not payload.get("https_wrong_pin_rejected") or not payload.get(
        "wss_wrong_pin_rejected"
    ):
        raise RuntimeError("The .NET probe accepted an incorrect certificate pin.")
    return payload


def _required_tls_protocols(
    *, host: str, port: int, certificate_path: Path
) -> list[str]:
    protocols: list[str] = []
    for version, expected in (
        (ssl.TLSVersion.TLSv1_2, "TLSv1.2"),
        (ssl.TLSVersion.TLSv1_3, "TLSv1.3"),
    ):
        context = ssl.create_default_context(cafile=str(certificate_path))
        context.minimum_version = version
        context.maximum_version = version
        with socket.create_connection((host, port), timeout=3.0) as connection:
            with context.wrap_socket(connection, server_hostname=host) as secured:
                negotiated = secured.version()
        if negotiated != expected:
            raise RuntimeError(f"The server did not negotiate required {expected}.")
        protocols.append(negotiated)
    return protocols


def _wait_for_tls(
    *,
    host: str,
    port: int,
    certificate_path: Path,
    process: subprocess.Popen[Any],
    timeout_s: float,
) -> None:
    context = ssl.create_default_context(cafile=str(certificate_path))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    deadline = time.monotonic() + timeout_s
    last_error: OSError | ssl.SSLError | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"The secure transport service exited with code {process.returncode}."
            )
        try:
            with socket.create_connection((host, port), timeout=1.0) as raw_socket:
                with context.wrap_socket(raw_socket, server_hostname=host):
                    return
        except (OSError, ssl.SSLError) as error:
            last_error = error
            time.sleep(0.1)
    raise RuntimeError(f"The secure transport service did not become ready: {last_error}")


def _plain_http_is_rejected(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0) as connection:
            connection.sendall(b"GET /v1/health HTTP/1.1\r\nHost: localhost\r\n\r\n")
            response = connection.recv(64)
    except OSError:
        return True
    return not response.startswith(b"HTTP/")


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


def _stop_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


if __name__ == "__main__":
    main()
