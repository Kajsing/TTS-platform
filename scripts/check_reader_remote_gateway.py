from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

try:
    from scripts import check_reader_secure_transport as secure_transport
except ModuleNotFoundError:
    import check_reader_secure_transport as secure_transport

REPO_ROOT = Path(__file__).resolve().parents[1]
for source in (
    REPO_ROOT / "apps" / "tts_service" / "src",
    REPO_ROOT / "packages" / "tts_core" / "src",
    REPO_ROOT / "packages" / "reader_core" / "src",
    REPO_ROOT / "packages" / "document_import" / "src",
    REPO_ROOT / "packages" / "speech_rules" / "src",
):
    sys.path.insert(0, str(source))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise the pinned Reader remote gateway without changing Windows Firewall."
    )
    parser.add_argument("--dotnet-executable", default="dotnet")
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    args = parser.parse_args()
    if os.name != "nt":
        print(json.dumps({"status": "skipped", "reason": "windows-required"}, indent=2))
        return 0
    result = check_remote_gateway(
        python_executable=sys.executable,
        dotnet_executable=args.dotnet_executable,
        startup_timeout_s=args.startup_timeout,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def create_local_app():
    from tts_service.config import load_config
    from tts_service.main import create_app

    return create_app(
        config=load_config(Path(os.environ["TTS_REMOTE_SMOKE_CONFIG"])),
        repo_root=Path(os.environ["TTS_REMOTE_SMOKE_REPO_ROOT"]),
    )


def create_gateway_app():
    from tts_service.remote_access import RemoteAccessManager
    from tts_service.remote_gateway import create_remote_gateway_app

    manager = RemoteAccessManager(
        reader_home=Path(os.environ["TTS_REMOTE_SMOKE_READER_HOME"]),
        local_base_url=os.environ["TTS_REMOTE_SMOKE_LOCAL_URL"],
        local_token_file=Path(os.environ["TTS_REMOTE_SMOKE_TOKEN_FILE"]),
    )
    return create_remote_gateway_app(manager)


def check_remote_gateway(
    *,
    python_executable: str,
    dotnet_executable: str,
    startup_timeout_s: float,
) -> dict[str, object]:
    secure_transport._build_dotnet_probe(dotnet_executable)
    with tempfile.TemporaryDirectory(prefix="tts-reader-u8-remote-") as temporary:
        root = Path(temporary).resolve()
        layout = secure_transport._write_spike_layout(root)
        generated = secure_transport._run_probe_command(
            dotnet_executable,
            ["generate", str(layout["certificate_directory"])],
        )
        certificate_path = Path(str(generated["certificate_path"]))
        private_key_path = Path(str(generated["private_key_path"]))
        pin = str(generated["spki_pin"])
        local_port = secure_transport._reserve_loopback_port()
        gateway_port = secure_transport._reserve_loopback_port()
        local_url = f"http://127.0.0.1:{local_port}"
        gateway_url = f"https://localhost:{gateway_port}/"
        environment = secure_transport._source_env()
        environment.update(
            {
                "TTS_REMOTE_SMOKE_CONFIG": str(layout["config_path"]),
                "TTS_REMOTE_SMOKE_REPO_ROOT": str(layout["repo_root"]),
                "TTS_REMOTE_SMOKE_READER_HOME": str(layout["reader_home"]),
                "TTS_REMOTE_SMOKE_LOCAL_URL": local_url,
                "TTS_REMOTE_SMOKE_TOKEN_FILE": str(layout["token_path"]),
            }
        )
        local_log = root / "local.log"
        gateway_log = root / "gateway.log"
        with local_log.open("w+", encoding="utf-8") as local_output, gateway_log.open(
            "w+", encoding="utf-8"
        ) as gateway_output:
            local_process = subprocess.Popen(
                _uvicorn_command(
                    python_executable,
                    "scripts.check_reader_remote_gateway:create_local_app",
                    local_port,
                ),
                cwd=REPO_ROOT,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=local_output,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            gateway_process: subprocess.Popen[Any] | None = None
            try:
                _wait_for_http(local_url + "/v1/health", local_process, startup_timeout_s)
                invitations = _create_invitations(
                    layout["reader_home"],
                    gateway_url,
                    pin,
                    certificate_path,
                    private_key_path,
                    count=2,
                )
                gateway_process = subprocess.Popen(
                    _uvicorn_command(
                        python_executable,
                        "scripts.check_reader_remote_gateway:create_gateway_app",
                        gateway_port,
                        certificate_path,
                        private_key_path,
                    ),
                    cwd=REPO_ROOT,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=gateway_output,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                secure_transport._wait_for_tls(
                    host="localhost",
                    port=gateway_port,
                    certificate_path=certificate_path,
                    process=gateway_process,
                    timeout_s=startup_timeout_s,
                )
                required_tls_protocols = secure_transport._required_tls_protocols(
                    host="localhost",
                    port=gateway_port,
                    certificate_path=certificate_path,
                )
                result = _exercise_gateway(
                    gateway_url=gateway_url,
                    pin=pin,
                    certificate_path=certificate_path,
                    invitations=invitations,
                    reader_home=layout["reader_home"],
                    dotnet_executable=dotnet_executable,
                    credential_file=root / "device-credential.txt",
                )
                result["plain_http_rejected"] = secure_transport._plain_http_is_rejected(
                    "localhost", gateway_port
                )
                result["legacy_tls_rejected"] = _legacy_tls_rejected(
                    "localhost", gateway_port, certificate_path
                )
                result["required_tls_protocols"] = required_tls_protocols
                if not result["plain_http_rejected"] or not result["legacy_tls_rejected"]:
                    raise RuntimeError("The remote gateway accepted an unsafe transport.")
                secure_transport._stop_process(gateway_process)
                gateway_process = None
                _wait_for_http(local_url + "/v1/health", local_process, 5.0)
                result["local_reader_healthy_after_gateway_stop"] = True
                result["firewall_changed"] = False
                return {"status": "ok", **result}
            except Exception as error:
                local_output.flush()
                gateway_output.flush()
                details = []
                for name, handle in (("local", local_output), ("gateway", gateway_output)):
                    handle.seek(0)
                    tail = handle.read()[-4000:].strip()
                    if tail:
                        details.append(f"{name} log:\n{tail}")
                suffix = "\n" + "\n".join(details) if details else ""
                raise RuntimeError(f"{error}{suffix}") from error
            finally:
                if gateway_process is not None:
                    secure_transport._stop_process(gateway_process)
                secure_transport._stop_process(local_process)


def _create_invitations(
    reader_home: Path,
    endpoint: str,
    pin: str,
    certificate_path: Path,
    private_key_path: Path,
    *,
    count: int,
) -> list[dict[str, object]]:
    from tts_service.remote_access import (
        RemoteAccessProfile,
        RemoteCredentialStore,
    )

    profile_id = str(uuid4())
    profile = RemoteAccessProfile(
        version=1,
        profile_id=profile_id,
        enabled=True,
        bind_host="10.250.0.1",
        port=7790,
        server_name=None,
        endpoint=endpoint,
        certificate_path=str(certificate_path),
        private_key_path=str(private_key_path),
        server_spki_pin=pin,
        firewall_mode="wireguard",
        firewall_remote_address="10.250.0.2/32",
        firewall_interface_alias="Remote-Smoke",
        firewall_profile="Public",
        firewall_rule_name=f"TTSPlatform.Reader.Remote.{profile_id}",
        gateway_program=str(Path(sys.executable).resolve()),
        created_at="2026-08-19T00:00:00Z",
        updated_at="2026-08-19T00:00:00Z",
    )
    store = RemoteCredentialStore(reader_home / "remote-access" / "devices.db")
    return [store.create_invitation(profile) for _ in range(count)]


def _exercise_gateway(
    *,
    gateway_url: str,
    pin: str,
    certificate_path: Path,
    invitations: list[dict[str, object]],
    reader_home: Path,
    dotnet_executable: str,
    credential_file: Path,
) -> dict[str, object]:
    context = ssl.create_default_context(cafile=str(certificate_path))
    invitation_file = credential_file.with_suffix(".invitation.json")
    invitation_file.write_text(
        json.dumps(invitations[0]),
        encoding="utf-8",
    )
    first = secure_transport._run_probe_command(
        dotnet_executable,
        ["pair", str(invitation_file), "Remote smoke one"],
    )
    if first.get("status") != "ok":
        raise RuntimeError("The actual .NET remote pairing client did not pair.")
    with httpx.Client(base_url=gateway_url, verify=context, timeout=20.0) as client:
        second = _pair(client, invitations[1], "Remote smoke two")
        reused = client.post(
            "/v1/remote/pair",
            json=_pairing_payload(invitations[0], "Replay"),
        )
        if reused.status_code != 401:
            raise RuntimeError("A consumed pairing invitation was accepted.")
        first_credential = str(first["credential"])
        second_credential = str(second["credential"])
        if first_credential == second_credential:
            raise RuntimeError("Two devices received the same credential.")

        second_credential = _rotate_credential(client, second_credential)
        conflict = _prove_stale_conflict(client, first_credential, second_credential)
        lease = _prove_content_lease(
            client,
            gateway_url,
            context,
            first_credential,
        )
        origin_denied = client.get(
            "/v1/health",
            headers={
                "Authorization": f"Bearer {first_credential}",
                "Origin": "https://malicious.example",
            },
        )
        admin_denied = client.get(
            "/v1/reader/remote/status",
            headers={"Authorization": f"Bearer {first_credential}"},
        )
        if origin_denied.status_code != 403 or admin_denied.status_code != 404:
            raise RuntimeError("The gateway did not enforce its origin/admin boundary.")

    credential_file.write_text(first_credential + "\n", encoding="utf-8")
    wrong_pin = secure_transport._probe_wrong_pin_transports(
        dotnet_executable,
        base_url=gateway_url,
        pin="sha256/" + ("A" * 43) + "=",
        token_file=credential_file,
    )
    probe = secure_transport._run_probe_command(
        dotnet_executable,
        ["probe", gateway_url, pin, str(credential_file)],
    )

    from tts_service.remote_access import RemoteCredentialStore

    store = RemoteCredentialStore(reader_home / "remote-access" / "devices.db")
    store.revoke_device(str(first["device"]["id"]))
    with httpx.Client(base_url=gateway_url, verify=context, timeout=10.0) as client:
        revoked = client.get(
            "/v1/health",
            headers={"Authorization": f"Bearer {first_credential}"},
        )
    if revoked.status_code != 401:
        raise RuntimeError("A revoked remote credential remained usable.")
    return {
        "paired_devices_are_distinct": True,
        "pairing_is_single_use": True,
        "credential_rotation_is_two_phase": True,
        "stale_edit_conflict": conflict,
        "content_lease_enforced": lease,
        "browser_origin_denied": True,
        "remote_admin_denied": True,
        "https_wrong_pin_rejected": wrong_pin["https_wrong_pin_rejected"],
        "wss_wrong_pin_rejected": wrong_pin["wss_wrong_pin_rejected"],
        "https_reader_document_created": probe["https_reader_document_created"],
        "wss_reader_completed": probe["wss_reader_completed"],
        "tls_protocol": probe["tls_protocol"],
        "revocation_enforced": True,
    }


def _pair(
    client: httpx.Client,
    invitation: dict[str, object],
    device_name: str,
) -> dict[str, Any]:
    response = client.post(
        "/v1/remote/pair",
        json=_pairing_payload(invitation, device_name),
    )
    response.raise_for_status()
    return response.json()


def _rotate_credential(client: httpx.Client, credential: str) -> str:
    headers = {"Authorization": f"Bearer {credential}"}
    started = client.post("/v1/remote/device/rotation", headers=headers, json={})
    started.raise_for_status()
    pending = str(started.json()["pending_credential"])
    rotation_id = str(started.json()["rotation_id"])
    if client.get("/v1/health", headers={"Authorization": f"Bearer {pending}"}).status_code != 401:
        raise RuntimeError("A pending credential was active before confirmation.")
    if client.get("/v1/health", headers=headers).status_code != 200:
        raise RuntimeError("The old credential stopped before rotation confirmation.")
    confirmed = client.post(
        "/v1/remote/device/rotation/confirm",
        headers=headers,
        json={"rotation_id": rotation_id, "pending_credential": pending},
    )
    confirmed.raise_for_status()
    if client.get("/v1/health", headers=headers).status_code != 401:
        raise RuntimeError("The old credential remained active after confirmation.")
    if client.get(
        "/v1/health", headers={"Authorization": f"Bearer {pending}"}
    ).status_code != 200:
        raise RuntimeError("The confirmed credential did not become active.")
    return pending


def _pairing_payload(
    invitation: dict[str, object],
    device_name: str,
) -> dict[str, object]:
    return {
        "contract_version": invitation["contract_version"],
        "ticket_id": invitation["ticket_id"],
        "ticket_secret": invitation["ticket_secret"],
        "device_name": device_name,
    }


def _prove_stale_conflict(
    client: httpx.Client,
    first_credential: str,
    second_credential: str,
) -> bool:
    first_headers = {"Authorization": f"Bearer {first_credential}"}
    second_headers = {"Authorization": f"Bearer {second_credential}"}
    created = client.post(
        "/v1/reader/documents",
        headers=first_headers,
        json={
            "title": "Remote conflict smoke",
            "source_type": "plain_text",
            "text": "Two clients saw this version.",
            "allow_duplicate": True,
        },
    )
    created.raise_for_status()
    document = created.json()
    document_id = document["id"]
    row_version = document["row_version"]
    first_update = client.patch(
        f"/v1/reader/documents/{document_id}",
        headers=first_headers,
        json={"expected_row_version": row_version, "title": "First client won"},
    )
    first_update.raise_for_status()
    stale = client.patch(
        f"/v1/reader/documents/{document_id}",
        headers=second_headers,
        json={"expected_row_version": row_version, "title": "Stale overwrite"},
    )
    return stale.status_code == 409


def _prove_content_lease(
    client: httpx.Client,
    gateway_url: str,
    context: ssl.SSLContext,
    credential: str,
) -> bool:
    from websockets.sync.client import connect

    headers = {"Authorization": f"Bearer {credential}"}
    created = client.post(
        "/v1/reader/documents",
        headers=headers,
        json={
            "title": "Remote lease smoke",
            "source_type": "plain_text",
            "text": "Locked while playback owns a content lease.",
            "allow_duplicate": True,
        },
    )
    created.raise_for_status()
    document = created.json()
    websocket_url = gateway_url.replace("https://", "wss://", 1) + "v1/reader/stream"
    with connect(
        websocket_url,
        ssl=context,
        additional_headers=headers,
        open_timeout=10.0,
        max_size=2 * 1024 * 1024,
    ) as websocket:
        websocket.send(
            json.dumps(
                {
                    "type": "start",
                    "payload": {
                        "document_id": document["id"],
                        "cursor": {"block_ordinal": 0, "character_offset": 0},
                    },
                }
            )
        )
        started = json.loads(websocket.recv())
        if started.get("type") != "started":
            raise RuntimeError("Remote content-lease stream did not start.")
        locked = client.post(
            f"/v1/reader/documents/{document['id']}/append",
            headers=headers,
            json={"expected_row_version": document["row_version"], "text": "Wait."},
        )
        websocket.send(json.dumps({"type": "cancel", "stream_id": started["stream_id"]}))
    for _ in range(20):
        allowed = client.post(
            f"/v1/reader/documents/{document['id']}/append",
            headers=headers,
            json={"expected_row_version": document["row_version"], "text": "Now."},
        )
        if allowed.status_code == 200:
            break
        time.sleep(0.05)
    return (
        locked.status_code == 409
        and locked.json()["error"]["type"] == "reader_document_locked"
        and allowed.status_code == 200
    )


def _legacy_tls_rejected(host: str, port: int, certificate_path: Path) -> bool:
    try:
        context = ssl.create_default_context(cafile=str(certificate_path))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            context.minimum_version = ssl.TLSVersion.TLSv1
            context.maximum_version = ssl.TLSVersion.TLSv1_1
        with socket.create_connection((host, port), timeout=2.0) as connection:
            with context.wrap_socket(connection, server_hostname=host):
                return False
    except (OSError, ssl.SSLError):
        return True


def _wait_for_http(url: str, process: subprocess.Popen[Any], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"The local Reader exited with code {process.returncode}.")
        try:
            if httpx.get(url, timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError as error:
            last_error = error
        time.sleep(0.1)
    raise RuntimeError(f"The local Reader did not become ready: {last_error}")


def _uvicorn_command(
    python_executable: str,
    factory: str,
    port: int,
    certificate_path: Path | None = None,
    private_key_path: Path | None = None,
) -> list[str]:
    command = [
        python_executable,
        "-m",
        "uvicorn",
        factory,
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
        "--no-server-header",
    ]
    if certificate_path is not None and private_key_path is not None:
        command.extend(
            [
                "--ssl-certfile",
                str(certificate_path),
                "--ssl-keyfile",
                str(private_key_path),
                "--ssl-ciphers",
                secure_transport.TLS12_CIPHERS,
            ]
        )
    return command


if __name__ == "__main__":
    raise SystemExit(main())
