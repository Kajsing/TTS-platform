from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

REMOTE_PROFILE_VERSION = 1
REMOTE_CONTRACT_VERSION = 1
PAIRING_LIFETIME = timedelta(minutes=10)
ROTATION_LIFETIME = timedelta(minutes=10)
MAX_TICKET_FAILURES = 5
REMOTE_TLS12_CIPHERS = (
    "ECDHE-ECDSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-CHACHA20-POLY1305"
)
_ALLOWED_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)


class RemoteAccessError(RuntimeError):
    """A safe, operator-facing remote access failure."""


@dataclass(frozen=True, slots=True)
class RemoteAccessProfile:
    version: int
    profile_id: str
    enabled: bool
    bind_host: str
    port: int
    server_name: str | None
    endpoint: str
    certificate_path: str
    private_key_path: str
    server_spki_pin: str
    firewall_mode: str
    firewall_remote_address: str
    firewall_interface_alias: str | None
    firewall_profile: str
    firewall_rule_name: str
    gateway_program: str
    created_at: str
    updated_at: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> RemoteAccessProfile:
        try:
            profile = cls(
                version=int(value["version"]),
                profile_id=str(value["profile_id"]),
                enabled=bool(value["enabled"]),
                bind_host=str(value["bind_host"]),
                port=int(value["port"]),
                server_name=(
                    str(value["server_name"]) if value.get("server_name") is not None else None
                ),
                endpoint=str(value["endpoint"]),
                certificate_path=str(value["certificate_path"]),
                private_key_path=str(value["private_key_path"]),
                server_spki_pin=str(value["server_spki_pin"]),
                firewall_mode=str(value["firewall_mode"]),
                firewall_remote_address=str(value["firewall_remote_address"]),
                firewall_interface_alias=(
                    str(value["firewall_interface_alias"])
                    if value.get("firewall_interface_alias") is not None
                    else None
                ),
                firewall_profile=str(value["firewall_profile"]),
                firewall_rule_name=str(value["firewall_rule_name"]),
                gateway_program=str(value["gateway_program"]),
                created_at=str(value["created_at"]),
                updated_at=str(value["updated_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteAccessError("Remote access profile is invalid.") from exc
        if profile.version != REMOTE_PROFILE_VERSION:
            raise RemoteAccessError("Remote access profile version is unsupported.")
        try:
            UUID(profile.profile_id)
        except ValueError as exc:
            raise RemoteAccessError("Remote access profile id is invalid.") from exc
        _validate_private_bind(profile.bind_host, profile.port)
        if _normalize_server_name(profile.server_name) != profile.server_name:
            raise RemoteAccessError("Remote access server name is invalid.")
        parsed = urlsplit(profile.endpoint)
        try:
            endpoint_port = parsed.port
        except ValueError as exc:
            raise RemoteAccessError("Remote access endpoint must be an HTTPS origin.") from exc
        expected_host = profile.server_name or profile.bind_host
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.hostname != expected_host
            or endpoint_port != profile.port
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise RemoteAccessError("Remote access endpoint must be an HTTPS origin.")
        if not profile.server_spki_pin.startswith("sha256/"):
            raise RemoteAccessError("Remote access server pin is invalid.")
        _validate_firewall_policy(
            mode=profile.firewall_mode,
            remote_address=profile.firewall_remote_address,
            interface_alias=profile.firewall_interface_alias,
            network_profile=profile.firewall_profile,
        )
        if profile.firewall_rule_name != f"TTSPlatform.Reader.Remote.{profile.profile_id}":
            raise RemoteAccessError("Remote access firewall rule name is invalid.")
        if not Path(profile.gateway_program).is_absolute():
            raise RemoteAccessError("Remote access gateway program path is invalid.")
        if not Path(profile.certificate_path).is_absolute() or not Path(
            profile.private_key_path
        ).is_absolute():
            raise RemoteAccessError("Remote access identity paths are invalid.")
        return profile

    def public_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "profile_id": self.profile_id,
            "enabled": self.enabled,
            "bind_host": self.bind_host,
            "port": self.port,
            "server_name": self.server_name,
            "endpoint": self.endpoint,
            "server_spki_pin": self.server_spki_pin,
            "firewall_mode": self.firewall_mode,
            "firewall_remote_address": self.firewall_remote_address,
            "firewall_interface_alias": self.firewall_interface_alias,
            "firewall_profile": self.firewall_profile,
            "firewall_rule_name": self.firewall_rule_name,
            "gateway_program": self.gateway_program,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class RemoteDevice:
    id: str
    display_name: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None
    generation: int

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


class RemoteCredentialStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS remote_pairing_tickets (
                    id TEXT PRIMARY KEY,
                    secret_sha256 BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    failed_attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS remote_devices (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    credential_sha256 BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    revoked_at TEXT,
                    generation INTEGER NOT NULL DEFAULT 1,
                    pending_credential_sha256 BLOB,
                    pending_generation INTEGER,
                    pending_expires_at TEXT,
                    pending_rotation_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_remote_devices_active
                    ON remote_devices(revoked_at, id);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(remote_devices)").fetchall()
            }
            if "pending_rotation_id" not in columns:
                connection.execute(
                    "ALTER TABLE remote_devices ADD COLUMN pending_rotation_id TEXT"
                )
        _secure_private_file(database_path)

    def assert_ready(self) -> None:
        if not self.database_path.is_file():
            raise RemoteAccessError("Remote device store is missing.")
        try:
            with self._connect() as connection:
                integrity = connection.execute("PRAGMA quick_check").fetchone()
                tables = {
                    str(row["name"])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
        except sqlite3.DatabaseError as exc:
            raise RemoteAccessError("Remote device store is invalid.") from exc
        if integrity is None or str(integrity[0]).lower() != "ok" or not {
            "remote_pairing_tickets",
            "remote_devices",
        }.issubset(tables):
            raise RemoteAccessError("Remote device store is invalid.")

    def create_invitation(self, profile: RemoteAccessProfile) -> dict[str, object]:
        now = _utc_now()
        ticket_id = str(uuid4())
        secret = secrets.token_urlsafe(32)
        expires_at = now + PAIRING_LIFETIME
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO remote_pairing_tickets(
                    id, secret_sha256, created_at, expires_at, consumed_at, failed_attempts
                ) VALUES (?, ?, ?, ?, NULL, 0)
                """,
                (
                    ticket_id,
                    _sha256(secret),
                    _timestamp(now),
                    _timestamp(expires_at),
                ),
            )
        return {
            "contract_version": REMOTE_CONTRACT_VERSION,
            "endpoint": profile.endpoint,
            "server_spki_pin": profile.server_spki_pin,
            "ticket_id": ticket_id,
            "ticket_secret": secret,
            "expires_at": _timestamp(expires_at),
        }

    def consume_invitation(
        self,
        ticket_id: str,
        ticket_secret: str,
        display_name: str,
    ) -> tuple[RemoteDevice, str]:
        normalized_name = _normalize_device_name(display_name)
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM remote_pairing_tickets WHERE id = ?",
                (ticket_id,),
            ).fetchone()
            if row is None:
                raise RemoteAccessError("Pairing invitation is invalid or expired.")
            if row["consumed_at"] is not None or _parse_timestamp(row["expires_at"]) <= now:
                raise RemoteAccessError("Pairing invitation is invalid or expired.")
            if int(row["failed_attempts"]) >= MAX_TICKET_FAILURES:
                raise RemoteAccessError("Pairing invitation is locked after too many failures.")
            if not secrets.compare_digest(bytes(row["secret_sha256"]), _sha256(ticket_secret)):
                connection.execute(
                    """
                    UPDATE remote_pairing_tickets
                    SET failed_attempts = failed_attempts + 1
                    WHERE id = ?
                    """,
                    (ticket_id,),
                )
                raise RemoteAccessError("Pairing invitation is invalid or expired.")

            device_id = str(uuid4())
            credential = _new_credential(device_id)
            created_at = _timestamp(now)
            connection.execute(
                "UPDATE remote_pairing_tickets SET consumed_at = ? WHERE id = ?",
                (created_at, ticket_id),
            )
            connection.execute(
                """
                INSERT INTO remote_devices(
                    id, display_name, credential_sha256, created_at, generation
                ) VALUES (?, ?, ?, ?, 1)
                """,
                (device_id, normalized_name, _credential_hash(credential), created_at),
            )
        return (
            RemoteDevice(
                id=device_id,
                display_name=normalized_name,
                created_at=created_at,
                last_used_at=None,
                revoked_at=None,
                generation=1,
            ),
            credential,
        )

    def authenticate(self, credential: str, *, touch: bool = True) -> RemoteDevice:
        device_id = _credential_device_id(credential)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM remote_devices WHERE id = ?",
                (device_id,),
            ).fetchone()
            if (
                row is None
                or row["revoked_at"] is not None
                or not secrets.compare_digest(
                    bytes(row["credential_sha256"]),
                    _credential_hash(credential),
                )
            ):
                raise RemoteAccessError("Remote device credential is invalid or revoked.")
            last_used_at = row["last_used_at"]
            if touch:
                now = _timestamp(_utc_now())
                connection.execute(
                    "UPDATE remote_devices SET last_used_at = ? WHERE id = ?",
                    (now, device_id),
                )
                last_used_at = now
            return _device_from_row(row, last_used_at=last_used_at)

    def is_active(self, device_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT revoked_at FROM remote_devices WHERE id = ?",
                (device_id,),
            ).fetchone()
            return row is not None and row["revoked_at"] is None

    def list_devices(self) -> tuple[RemoteDevice, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM remote_devices ORDER BY created_at, id"
            ).fetchall()
            return tuple(_device_from_row(row) for row in rows)

    def revoke_device(self, device_id: str) -> RemoteDevice:
        now = _timestamp(_utc_now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM remote_devices WHERE id = ?",
                (device_id,),
            ).fetchone()
            if row is None:
                raise RemoteAccessError("Remote device was not found.")
            connection.execute(
                """
                UPDATE remote_devices
                SET revoked_at = ?, pending_credential_sha256 = NULL,
                    pending_generation = NULL, pending_expires_at = NULL,
                    pending_rotation_id = NULL
                WHERE id = ?
                """,
                (now, device_id),
            )
            return _device_from_row(row, revoked_at=now)

    def revoke_all(self) -> None:
        now = _timestamp(_utc_now())
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE remote_devices
                SET revoked_at = COALESCE(revoked_at, ?),
                    pending_credential_sha256 = NULL,
                    pending_generation = NULL,
                    pending_expires_at = NULL,
                    pending_rotation_id = NULL
                """,
                (now,),
            )
            connection.execute(
                "UPDATE remote_pairing_tickets SET consumed_at = COALESCE(consumed_at, ?)",
                (now,),
            )

    def begin_rotation(self, device_id: str) -> tuple[str, str]:
        now = _utc_now()
        rotation_id = str(uuid4())
        pending_generation: int
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM remote_devices WHERE id = ? AND revoked_at IS NULL",
                (device_id,),
            ).fetchone()
            if row is None:
                raise RemoteAccessError("Remote device credential is invalid or revoked.")
            pending_generation = int(row["generation"]) + 1
            credential = _new_credential(device_id)
            connection.execute(
                """
                UPDATE remote_devices
                SET pending_credential_sha256 = ?, pending_generation = ?,
                    pending_expires_at = ?, pending_rotation_id = ?
                WHERE id = ?
                """,
                (
                    _credential_hash(credential),
                    pending_generation,
                    _timestamp(now + ROTATION_LIFETIME),
                    rotation_id,
                    device_id,
                ),
            )
        return rotation_id, credential

    def confirm_rotation(
        self,
        device_id: str,
        rotation_id: str,
        pending_credential: str,
    ) -> RemoteDevice:
        if _credential_device_id(pending_credential) != device_id:
            raise RemoteAccessError("Pending remote credential is invalid.")
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM remote_devices WHERE id = ? AND revoked_at IS NULL",
                (device_id,),
            ).fetchone()
            if (
                row is None
                or row["pending_credential_sha256"] is None
                or row["pending_generation"] is None
                or row["pending_expires_at"] is None
                or row["pending_rotation_id"] is None
                or not secrets.compare_digest(str(row["pending_rotation_id"]), rotation_id)
                or _parse_timestamp(row["pending_expires_at"]) <= now
                or not secrets.compare_digest(
                    bytes(row["pending_credential_sha256"]),
                    _credential_hash(pending_credential),
                )
            ):
                raise RemoteAccessError("Pending remote credential is invalid or expired.")
            generation = int(row["pending_generation"])
            connection.execute(
                """
                UPDATE remote_devices
                SET credential_sha256 = pending_credential_sha256,
                    generation = pending_generation,
                    pending_credential_sha256 = NULL,
                    pending_generation = NULL,
                    pending_expires_at = NULL,
                    pending_rotation_id = NULL
                WHERE id = ?
                """,
                (device_id,),
            )
            return _device_from_row(row, generation=generation)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()


class RemoteAccessManager:
    def __init__(
        self,
        *,
        reader_home: Path,
        local_base_url: str,
        local_token_file: Path,
        firewall_script_path: Path | None = None,
        log_level: str = "warning",
    ) -> None:
        self.root = reader_home / "remote-access"
        self.profile_path = self.root / "profile.json"
        self.certificate_path = self.root / "server-cert.pem"
        self.private_key_path = self.root / "server-key.pem"
        self.local_base_url = local_base_url.rstrip("/")
        self.local_token_file = local_token_file
        self.firewall_script_path = firewall_script_path
        self.log_level = log_level
        self._lock = threading.RLock()
        self._store: RemoteCredentialStore | None = None
        self._server: Any | None = None
        self._thread: threading.Thread | None = None
        self._startup_error: str | None = None

    @property
    def store(self) -> RemoteCredentialStore:
        with self._lock:
            if self._store is None:
                self._store = RemoteCredentialStore(self.root / "devices.db")
            return self._store

    def load_profile(self) -> RemoteAccessProfile | None:
        if not self.profile_path.is_file():
            return None
        try:
            payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RemoteAccessError("Remote access profile could not be read.") from exc
        if not isinstance(payload, dict):
            raise RemoteAccessError("Remote access profile is invalid.")
        return RemoteAccessProfile.from_mapping(payload)

    def status_payload(self) -> dict[str, object]:
        try:
            profile = self.load_profile()
            profile_error = None
        except RemoteAccessError as exc:
            profile = None
            profile_error = str(exc)
        with self._lock:
            running = bool(
                self._thread is not None
                and self._thread.is_alive()
                and self._server is not None
                and bool(getattr(self._server, "started", False))
            )
            startup_error = self._startup_error
        return {
            "configured": profile is not None,
            "enabled": bool(profile and profile.enabled),
            "running": running,
            "startup_error": profile_error or startup_error,
            "profile": profile.public_payload() if profile is not None else None,
            "device_count": len(self.store.list_devices()),
            "transport": "owner-managed-wireguard",
            "wireguard_managed_by_reader": False,
            "firewall": self.firewall_status(profile),
        }

    def configure(
        self,
        *,
        bind_host: str,
        port: int,
        server_name: str | None = None,
        firewall_mode: str = "wireguard",
        firewall_remote_address: str = "",
        firewall_interface_alias: str | None = None,
        firewall_profile: str = "Public",
        start: bool = True,
    ) -> RemoteAccessProfile:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RemoteAccessError(
                    "Disable remote access before changing its network profile."
                )
        normalized_host = _validate_private_bind(bind_host, port)
        normalized_name = _normalize_server_name(server_name)
        self.root.mkdir(parents=True, exist_ok=True)
        existing = self.load_profile()
        created_at = existing.created_at if existing is not None else _timestamp(_utc_now())
        profile_id = existing.profile_id if existing is not None else str(uuid4())
        (
            normalized_firewall_mode,
            normalized_remote_address,
            normalized_interface_alias,
            normalized_firewall_profile,
        ) = _validate_firewall_policy(
            mode=firewall_mode,
            remote_address=firewall_remote_address,
            interface_alias=firewall_interface_alias,
            network_profile=firewall_profile,
        )
        _generate_or_update_certificate(
            certificate_path=self.certificate_path,
            private_key_path=self.private_key_path,
            bind_host=normalized_host,
            server_name=normalized_name,
        )
        pin = _certificate_spki_pin(self.certificate_path)
        updated_at = _timestamp(_utc_now())
        endpoint_host = normalized_name or normalized_host
        if ":" in endpoint_host and not endpoint_host.startswith("["):
            endpoint_host = f"[{endpoint_host}]"
        profile = RemoteAccessProfile(
            version=REMOTE_PROFILE_VERSION,
            profile_id=profile_id,
            enabled=False,
            bind_host=normalized_host,
            port=port,
            server_name=normalized_name,
            endpoint=f"https://{endpoint_host}:{port}/",
            certificate_path=str(self.certificate_path),
            private_key_path=str(self.private_key_path),
            server_spki_pin=pin,
            firewall_mode=normalized_firewall_mode,
            firewall_remote_address=normalized_remote_address,
            firewall_interface_alias=normalized_interface_alias,
            firewall_profile=normalized_firewall_profile,
            firewall_rule_name=f"TTSPlatform.Reader.Remote.{profile_id}",
            gateway_program=str(Path(sys.executable).resolve()),
            created_at=created_at,
            updated_at=updated_at,
        )
        _write_private_json(self.profile_path, asdict(profile))
        if start:
            self.assert_firewall_safe(profile)
            profile = replace(profile, enabled=True, updated_at=_timestamp(_utc_now()))
            _write_private_json(self.profile_path, asdict(profile))
            self.start()
        return profile

    def start_if_enabled(self) -> None:
        profile = self.load_profile()
        if profile is not None and profile.enabled:
            try:
                self.start()
            except RemoteAccessError as exc:
                with self._lock:
                    self._startup_error = str(exc)
                raise

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            profile = self.load_profile()
            if profile is None or not profile.enabled:
                raise RemoteAccessError("Remote access is not configured and enabled.")
            if Path(profile.gateway_program).resolve() != Path(sys.executable).resolve():
                raise RemoteAccessError("Remote access gateway program changed unexpectedly.")
            _validate_certificate_material(profile, root=self.root)
            self.store.assert_ready()
            self.assert_firewall_safe(profile)
            certificate = Path(profile.certificate_path)
            private_key = Path(profile.private_key_path)
            _assert_bind_address_available(profile.bind_host)
            from .remote_gateway import create_remote_gateway_app

            try:
                import uvicorn
            except ImportError as exc:  # pragma: no cover - base dependency
                raise RemoteAccessError("Uvicorn is required for remote access.") from exc
            app = create_remote_gateway_app(self)
            config = uvicorn.Config(
                app,
                host=profile.bind_host,
                port=profile.port,
                log_level=self.log_level,
                access_log=False,
                ssl_certfile=str(certificate),
                ssl_keyfile=str(private_key),
                ssl_ciphers=REMOTE_TLS12_CIPHERS,
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(
                target=server.run,
                name="tts-reader-remote-gateway",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            self._startup_error = None
            thread.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if bool(getattr(server, "started", False)):
                return
            if not thread.is_alive():
                break
            time.sleep(0.05)
        with self._lock:
            self._startup_error = "Remote gateway could not bind to the selected address and port."
            server.should_exit = True
        raise RemoteAccessError(self._startup_error)

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
        if server is not None:
            server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)

    def disable(self) -> dict[str, object]:
        self.stop()
        profile = self.load_profile()
        if profile is not None:
            disabled = replace(
                profile,
                enabled=False,
                updated_at=_timestamp(_utc_now()),
            )
            _write_private_json(self.profile_path, asdict(disabled))
        self.store.revoke_all()
        return self.status_payload()

    def local_token(self) -> str:
        try:
            token = self.local_token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RemoteAccessError("Local service token could not be read.") from exc
        if not token:
            raise RemoteAccessError("Local service token is empty.")
        return token

    def firewall_status(self, profile: RemoteAccessProfile | None = None) -> dict[str, object]:
        if profile is None:
            return {"supported": os.name == "nt", "exists": False, "matches": False}
        if os.name != "nt":
            return {
                "supported": False,
                "exists": False,
                "matches": False,
                "message": "Windows Firewall verification is available only on Windows.",
            }
        script = self.firewall_script_path
        if script is None or not script.is_file():
            return {
                "supported": False,
                "exists": False,
                "matches": False,
                "message": "The Reader firewall helper is missing.",
            }
        command = _firewall_command(script, profile, action="Status")
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = json.loads(completed.stdout) if completed.stdout.strip() else {}
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return {
                "supported": True,
                "exists": False,
                "matches": False,
                "message": "Windows Firewall status could not be verified.",
            }
        if completed.returncode != 0 or not isinstance(payload, dict):
            return {
                "supported": True,
                "exists": False,
                "matches": False,
                "message": "Windows Firewall status could not be verified.",
            }
        return {"supported": True, **payload}

    def assert_firewall_safe(self, profile: RemoteAccessProfile) -> None:
        status = self.firewall_status(profile)
        if not status.get("supported"):
            raise RemoteAccessError("Windows Firewall verification is unavailable.")
        if not status.get("exists") or not status.get("matches"):
            raise RemoteAccessError(
                "The exact Reader remote firewall rule is missing or does not match the profile."
            )


def _validate_private_bind(host: str, port: int) -> str:
    normalized = host.strip()
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError as exc:
        raise RemoteAccessError(
            "Remote bind address must be an explicit private IP address."
        ) from exc
    if (
        address.is_unspecified
        or address.is_loopback
        or address.is_multicast
        or address.is_link_local
        or not _is_allowed_private_address(address)
    ):
        raise RemoteAccessError("Remote bind address must be a non-loopback private IP address.")
    if not 1024 <= port <= 65535:
        raise RemoteAccessError("Remote gateway port must be between 1024 and 65535.")
    return address.compressed


def _validate_firewall_policy(
    *,
    mode: str,
    remote_address: str,
    interface_alias: str | None,
    network_profile: str,
) -> tuple[str, str, str | None, str]:
    normalized_mode = mode.strip().lower()
    normalized_profile = network_profile.strip()
    if normalized_profile not in {"Private", "Public", "Domain"}:
        raise RemoteAccessError("Windows Firewall profile must be Private, Public, or Domain.")
    if normalized_mode == "lan":
        if remote_address.strip().lower() != "localsubnet":
            raise RemoteAccessError("LAN remote access must be restricted to LocalSubnet.")
        if normalized_profile != "Private":
            raise RemoteAccessError("LAN remote access requires a Private Windows network.")
        if interface_alias is not None and interface_alias.strip():
            raise RemoteAccessError("LAN remote access does not accept a tunnel interface alias.")
        return "lan", "LocalSubnet", None, "Private"
    if normalized_mode != "wireguard":
        raise RemoteAccessError("Remote firewall mode must be wireguard or lan.")
    alias = (interface_alias or "").strip()
    if not alias or len(alias) > 128 or any(ord(character) < 32 for character in alias):
        raise RemoteAccessError("WireGuard interface alias is invalid.")
    value = remote_address.strip()
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise RemoteAccessError("WireGuard peer address must be an explicit IP or subnet.") from exc
    minimum_prefix = 24 if network.version == 4 else 64
    if network.prefixlen < minimum_prefix or not any(
        network.version == allowed.version and network.subnet_of(allowed)
        for allowed in _ALLOWED_PRIVATE_NETWORKS
    ):
        raise RemoteAccessError("WireGuard peer address must be a private IP or narrow subnet.")
    return "wireguard", network.with_prefixlen, alias, normalized_profile


def _is_allowed_private_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        address.version == allowed.version and address in allowed
        for allowed in _ALLOWED_PRIVATE_NETWORKS
    )


def _firewall_command(
    script: Path,
    profile: RemoteAccessProfile,
    *,
    action: str,
) -> list[str]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Action",
        action,
        "-ProfileId",
        profile.profile_id,
        "-LocalAddress",
        profile.bind_host,
        "-LocalPort",
        str(profile.port),
        "-Mode",
        profile.firewall_mode,
        "-RemoteAddress",
        profile.firewall_remote_address,
        "-NetworkProfile",
        profile.firewall_profile,
        "-Program",
        profile.gateway_program,
    ]
    if profile.firewall_interface_alias:
        command.extend(["-InterfaceAlias", profile.firewall_interface_alias])
    return command


def _normalize_server_name(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().rstrip(".").lower()
    if len(normalized) > 253 or any(
        not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
        for label in normalized.split(".")
    ):
        raise RemoteAccessError("Remote server name is invalid.")
    if any(
        not character.isalnum() and character != "-"
        for character in normalized.replace(".", "")
    ):
        raise RemoteAccessError("Remote server name is invalid.")
    return normalized


def _normalize_device_name(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if (
        not normalized
        or len(normalized) > 80
        or any(ord(character) < 32 for character in normalized)
    ):
        raise RemoteAccessError("Device name must contain 1 to 80 printable characters.")
    return normalized


def _new_credential(device_id: str) -> str:
    return f"rd1.{device_id}.{secrets.token_urlsafe(32)}"


def _credential_device_id(credential: str) -> str:
    parts = credential.strip().split(".", 2)
    if len(parts) != 3 or parts[0] != "rd1" or len(parts[2]) < 40:
        raise RemoteAccessError("Remote device credential is invalid or revoked.")
    try:
        return str(UUID(parts[1]))
    except ValueError as exc:
        raise RemoteAccessError("Remote device credential is invalid or revoked.") from exc


def _sha256(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _credential_hash(credential: str) -> bytes:
    return _sha256(credential)


def _device_from_row(
    row: sqlite3.Row,
    *,
    last_used_at: str | None = None,
    revoked_at: str | None = None,
    generation: int | None = None,
) -> RemoteDevice:
    return RemoteDevice(
        id=str(row["id"]),
        display_name=str(row["display_name"]),
        created_at=str(row["created_at"]),
        last_used_at=(last_used_at if last_used_at is not None else row["last_used_at"]),
        revoked_at=(revoked_at if revoked_at is not None else row["revoked_at"]),
        generation=(generation if generation is not None else int(row["generation"])),
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _secure_private_file(temporary)
    os.replace(temporary, path)
    _secure_private_file(path)


def _generate_or_update_certificate(
    *,
    certificate_path: Path,
    private_key_path: Path,
    bind_host: str,
    server_name: str | None,
) -> None:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError as exc:
        raise RemoteAccessError(
            "Remote access requires the cryptography package. Reinstall TTS Platform."
        ) from exc

    if private_key_path.is_file():
        try:
            key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
        except (OSError, ValueError, TypeError) as exc:
            raise RemoteAccessError("Remote access private key could not be loaded.") from exc
        if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
            raise RemoteAccessError("Remote access private key has an unsupported type.")
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        private_key_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        _secure_private_file(private_key_path)

    now = _utc_now()
    common_name = server_name or bind_host
    san_entries: list[x509.GeneralName] = [x509.IPAddress(ipaddress.ip_address(bind_host))]
    if server_name is not None:
        san_entries.append(x509.DNSName(server_name))
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=397))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    _secure_private_file(certificate_path)


def _certificate_spki_pin(certificate_path: Path) -> str:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    except (ImportError, OSError, ValueError) as exc:
        raise RemoteAccessError("Remote access certificate could not be loaded.") from exc
    spki = certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return "sha256/" + base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")


def _validate_certificate_material(profile: RemoteAccessProfile, *, root: Path) -> None:
    try:
        from cryptography import x509
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID
    except ImportError as exc:
        raise RemoteAccessError(
            "Remote access requires the cryptography package. Reinstall TTS Platform."
        ) from exc

    certificate_path = Path(profile.certificate_path)
    private_key_path = Path(profile.private_key_path)
    expected_certificate_path = (root / "server-cert.pem").resolve()
    expected_private_key_path = (root / "server-key.pem").resolve()
    try:
        if (
            certificate_path.resolve() != expected_certificate_path
            or private_key_path.resolve() != expected_private_key_path
        ):
            raise RemoteAccessError("Remote access identity paths do not match this Reader.")
        certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
        private_key = serialization.load_pem_private_key(
            private_key_path.read_bytes(),
            password=None,
        )
    except RemoteAccessError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise RemoteAccessError(
            "Remote access certificate or private key is missing or invalid."
        ) from exc

    public_key = certificate.public_key()
    if (
        not isinstance(public_key, ec.EllipticCurvePublicKey)
        or public_key.curve.name != "secp256r1"
        or not isinstance(private_key, ec.EllipticCurvePrivateKey)
        or private_key.curve.name != "secp256r1"
    ):
        raise RemoteAccessError("Remote access identity must use an ECDSA P-256 key.")
    if public_key.public_numbers() != private_key.public_key().public_numbers():
        raise RemoteAccessError("Remote access certificate and private key do not match.")
    if certificate.subject != certificate.issuer:
        raise RemoteAccessError("Remote access certificate must be self-signed.")
    try:
        public_key.verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            ec.ECDSA(certificate.signature_hash_algorithm),
        )
    except InvalidSignature as exc:
        raise RemoteAccessError("Remote access certificate signature is invalid.") from exc

    now = _utc_now()
    if certificate.not_valid_before_utc > now or certificate.not_valid_after_utc <= now:
        raise RemoteAccessError("Remote access certificate is not currently valid.")
    try:
        usages = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
        alternatives = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
    except x509.ExtensionNotFound as exc:
        raise RemoteAccessError("Remote access certificate extensions are incomplete.") from exc
    if ExtendedKeyUsageOID.SERVER_AUTH not in usages or constraints.ca:
        raise RemoteAccessError("Remote access certificate is not a server identity.")
    expected_ip = ipaddress.ip_address(profile.bind_host)
    if expected_ip not in alternatives.get_values_for_type(x509.IPAddress):
        raise RemoteAccessError("Remote access certificate does not cover the bind address.")
    if profile.server_name is not None:
        dns_names = {
            name.rstrip(".").lower()
            for name in alternatives.get_values_for_type(x509.DNSName)
        }
        if profile.server_name.rstrip(".").lower() not in dns_names:
            raise RemoteAccessError("Remote access certificate does not cover the server name.")
    if _certificate_spki_pin(certificate_path) != profile.server_spki_pin:
        raise RemoteAccessError("Remote access certificate pin changed unexpectedly.")


def _secure_private_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        raise RemoteAccessError(f"Private file permissions could not be set: {path.name}.") from exc
    if os.name != "nt":
        return
    try:
        identity = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        fields = [field.strip().strip('"') for field in identity.split(",")]
        user_sid = next((field for field in fields if field.startswith("S-1-")), None)
        if user_sid is None:
            raise RemoteAccessError("Current Windows user SID could not be determined.")
        completed = subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{user_sid}:(F)",
                "*S-1-5-18:(F)",
                "*S-1-5-32-544:(F)",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RemoteAccessError(f"Windows ACL could not be secured: {path.name}.") from exc
    if completed.returncode != 0:
        raise RemoteAccessError(f"Windows ACL could not be secured: {path.name}.")


def _assert_bind_address_available(host: str) -> None:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((host, 0))
    except OSError as exc:
        raise RemoteAccessError(
            "Selected remote address is not active on this computer. Start WireGuard first."
        ) from exc
