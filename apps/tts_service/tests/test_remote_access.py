from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from tts_service.config import AppConfig
from tts_service.main import create_app
from tts_service.remote_access import (
    RemoteAccessError,
    RemoteAccessManager,
    RemoteAccessProfile,
    RemoteCredentialStore,
    _validate_certificate_material,
    _validate_firewall_policy,
)
from tts_service.remote_gateway import (
    _DeviceLeaseSet,
    classify_remote_route,
    create_remote_gateway_app,
    is_remote_route_allowed,
)

TEST_RESOURCE_ID = "11111111-1111-4111-8111-111111111111"


def _profile(tmp_path: Path) -> RemoteAccessProfile:
    return RemoteAccessProfile(
        version=1,
        profile_id="profile-1",
        enabled=True,
        bind_host="10.42.0.1",
        port=7790,
        server_name=None,
        endpoint="https://10.42.0.1:7790/",
        certificate_path=str(tmp_path / "server-cert.pem"),
        private_key_path=str(tmp_path / "server-key.pem"),
        server_spki_pin="sha256/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        firewall_mode="wireguard",
        firewall_remote_address="10.42.0.2/32",
        firewall_interface_alias="WireGuard",
        firewall_profile="Public",
        firewall_rule_name="TTSPlatform.Reader.Remote.profile-1",
        gateway_program=str(tmp_path / "python.exe"),
        created_at="2026-08-19T18:00:00Z",
        updated_at="2026-08-19T18:00:00Z",
    )


def _manager(tmp_path: Path) -> RemoteAccessManager:
    tmp_path.mkdir(parents=True, exist_ok=True)
    token_file = tmp_path / "token.txt"
    token_file.write_text("local-token\n", encoding="utf-8")
    return RemoteAccessManager(
        reader_home=tmp_path / "reader",
        local_base_url="http://127.0.0.1:7777",
        local_token_file=token_file,
    )


def test_local_manager_construction_does_not_create_remote_state(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    assert not manager.root.exists()
    assert manager.load_profile() is None


def test_pairing_creates_distinct_revocable_device_credentials(tmp_path: Path) -> None:
    store = RemoteCredentialStore(tmp_path / "remote.db")
    profile = _profile(tmp_path)

    first_invitation = store.create_invitation(profile)
    first, first_credential = store.consume_invitation(
        str(first_invitation["ticket_id"]),
        str(first_invitation["ticket_secret"]),
        "Laptop",
    )
    second_invitation = store.create_invitation(profile)
    second, second_credential = store.consume_invitation(
        str(second_invitation["ticket_id"]),
        str(second_invitation["ticket_secret"]),
        "Desktop",
    )

    assert first.id != second.id
    assert first_credential != second_credential
    assert store.authenticate(first_credential).display_name == "Laptop"
    assert store.authenticate(second_credential).display_name == "Desktop"
    store.revoke_device(first.id)
    with pytest.raises(RemoteAccessError, match="invalid or revoked"):
        store.authenticate(first_credential)
    assert store.authenticate(second_credential).id == second.id


def test_pairing_ticket_is_single_use_and_never_persisted_in_plaintext(tmp_path: Path) -> None:
    database_path = tmp_path / "remote.db"
    store = RemoteCredentialStore(database_path)
    invitation = store.create_invitation(_profile(tmp_path))
    secret = str(invitation["ticket_secret"])

    store.consume_invitation(
        str(invitation["ticket_id"]),
        secret,
        "Laptop",
    )

    with pytest.raises(RemoteAccessError, match="invalid or expired"):
        store.consume_invitation(
            str(invitation["ticket_id"]),
            secret,
            "Duplicate",
        )
    assert secret.encode("utf-8") not in database_path.read_bytes()


def test_device_store_releases_database_handles_after_each_operation(tmp_path: Path) -> None:
    database_path = tmp_path / "remote.db"
    store = RemoteCredentialStore(database_path)
    store.create_invitation(_profile(tmp_path))
    assert store.list_devices() == ()

    moved_path = tmp_path / "remote-moved.db"
    database_path.replace(moved_path)
    moved_path.replace(database_path)


def test_device_store_migrates_pre_rotation_id_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "remote.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE remote_devices (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                credential_sha256 BLOB NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                revoked_at TEXT,
                generation INTEGER NOT NULL DEFAULT 1,
                pending_credential_sha256 BLOB,
                pending_generation INTEGER,
                pending_expires_at TEXT
            )
            """
        )

    RemoteCredentialStore(database_path)

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(remote_devices)")}
    assert "pending_rotation_id" in columns


def test_device_rotation_is_two_phase(tmp_path: Path) -> None:
    store = RemoteCredentialStore(tmp_path / "remote.db")
    invitation = store.create_invitation(_profile(tmp_path))
    device, old_credential = store.consume_invitation(
        str(invitation["ticket_id"]),
        str(invitation["ticket_secret"]),
        "Laptop",
    )

    rotation_id, pending_credential = store.begin_rotation(device.id)

    assert store.authenticate(old_credential).generation == 1
    with pytest.raises(RemoteAccessError, match="invalid or revoked"):
        store.authenticate(pending_credential)
    with pytest.raises(RemoteAccessError, match="invalid or expired"):
        store.confirm_rotation(device.id, str(uuid4()), pending_credential)
    confirmed = store.confirm_rotation(device.id, rotation_id, pending_credential)
    assert confirmed.generation == 2
    assert store.authenticate(pending_credential).generation == 2
    with pytest.raises(RemoteAccessError, match="invalid or revoked"):
        store.authenticate(old_credential)


def test_profile_generation_reuses_identity_pin_and_stays_disabled_from_local_defaults(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)

    first = manager.configure(
        bind_host="10.42.0.1",
        port=7790,
        firewall_remote_address="10.42.0.2/32",
        firewall_interface_alias="WireGuard",
        start=False,
    )
    second = manager.configure(
        bind_host="10.42.0.2",
        port=7791,
        firewall_remote_address="10.42.0.3/32",
        firewall_interface_alias="WireGuard",
        start=False,
    )

    assert first.server_spki_pin == second.server_spki_pin
    assert second.endpoint == "https://10.42.0.2:7791/"
    profile_json = manager.profile_path.read_text(encoding="utf-8")
    assert "local-token" not in profile_json
    assert "ticket_secret" not in profile_json
    assert manager.status_payload()["running"] is False


def test_remote_identity_matches_its_key_pin_and_bind_address(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    first = manager.configure(
        bind_host="10.42.0.1",
        port=7790,
        firewall_remote_address="10.42.0.2/32",
        firewall_interface_alias="WireGuard",
        start=False,
    )

    _validate_certificate_material(first, root=manager.root)
    second = manager.configure(
        bind_host="10.42.0.2",
        port=7790,
        firewall_remote_address="10.42.0.3/32",
        firewall_interface_alias="WireGuard",
        start=False,
    )

    stale_bind = replace(first, server_spki_pin=second.server_spki_pin)
    with pytest.raises(RemoteAccessError, match="bind address"):
        _validate_certificate_material(stale_bind, root=manager.root)


def test_remote_identity_rejects_a_mismatched_private_key(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    profile = manager.configure(
        bind_host="10.42.0.1",
        port=7790,
        firewall_remote_address="10.42.0.2/32",
        firewall_interface_alias="WireGuard",
        start=False,
    )
    foreign = _manager(tmp_path / "foreign")
    foreign.configure(
        bind_host="10.43.0.1",
        port=7790,
        firewall_remote_address="10.43.0.2/32",
        firewall_interface_alias="WireGuard",
        start=False,
    )
    manager.private_key_path.write_bytes(foreign.private_key_path.read_bytes())

    with pytest.raises(RemoteAccessError, match="do not match"):
        _validate_certificate_material(profile, root=manager.root)


def test_gateway_start_rejects_a_wrong_certificate_san_before_firewall_use(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    stale = manager.configure(
        bind_host="10.42.0.1",
        port=7790,
        firewall_remote_address="10.42.0.2/32",
        firewall_interface_alias="WireGuard",
        start=False,
    )
    current = manager.configure(
        bind_host="10.42.0.2",
        port=7790,
        firewall_remote_address="10.42.0.3/32",
        firewall_interface_alias="WireGuard",
        start=False,
    )
    tampered = replace(stale, enabled=True, server_spki_pin=current.server_spki_pin)
    monkeypatch.setattr(manager, "load_profile", lambda: tampered)
    monkeypatch.setattr(
        manager,
        "assert_firewall_safe",
        lambda _profile: pytest.fail("firewall check ran before certificate validation"),
    )

    with pytest.raises(RemoteAccessError, match="bind address"):
        manager.start_if_enabled()
    assert "bind address" in str(manager.status_payload()["startup_error"])


def test_gateway_start_rejects_a_missing_device_store_before_firewall_use(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    profile = replace(
        manager.configure(
            bind_host="10.42.0.1",
            port=7790,
            firewall_remote_address="10.42.0.2/32",
            firewall_interface_alias="WireGuard",
            start=False,
        ),
        enabled=True,
    )
    manager.store.database_path.unlink()
    monkeypatch.setattr(manager, "load_profile", lambda: profile)
    monkeypatch.setattr(
        manager,
        "assert_firewall_safe",
        lambda _profile: pytest.fail("firewall check ran before device-store validation"),
    )

    with pytest.raises(RemoteAccessError, match="device store is missing"):
        manager.start_if_enabled()


@pytest.mark.parametrize(
    "remote_address",
    ["10.0.0.1/1", "10.0.0.1/23", "172.16.0.1/8", "fc00::1/63", "8.8.8.8/32"],
)
def test_wireguard_firewall_policy_rejects_public_or_broad_peer_networks(
    remote_address: str,
) -> None:
    with pytest.raises(RemoteAccessError, match="private IP or narrow subnet"):
        _validate_firewall_policy(
            mode="wireguard",
            remote_address=remote_address,
            interface_alias="WireGuard",
            network_profile="Public",
        )


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "0.0.0.0", "::", "8.8.8.8", "localhost"],
)
def test_profile_rejects_loopback_wildcard_public_and_hostname_binds(
    tmp_path: Path,
    host: str,
) -> None:
    with pytest.raises(RemoteAccessError):
        _manager(tmp_path).configure(
            bind_host=host,
            port=7790,
            firewall_remote_address="10.42.0.2/32",
            firewall_interface_alias="WireGuard",
            start=False,
        )


def test_gateway_pairing_requires_no_local_token_but_all_data_routes_require_device_auth(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    profile = _profile(tmp_path)
    invitation = manager.store.create_invitation(profile)
    client = TestClient(create_remote_gateway_app(manager))

    unauthenticated = client.get("/v1/health")
    paired = client.post(
        "/v1/remote/pair",
        json={
            "contract_version": 1,
            "ticket_id": invitation["ticket_id"],
            "ticket_secret": invitation["ticket_secret"],
            "device_name": "Laptop",
        },
    )

    assert unauthenticated.status_code == 401
    assert paired.status_code == 201
    assert paired.json()["credential"].startswith("rd1.")
    assert client.get(
        "/v1/reader/remote/status",
        headers={"Authorization": f"Bearer {paired.json()['credential']}"},
    ).status_code == 404


def test_pairing_payload_rejects_unexpected_invitation_fields_without_consuming_ticket(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    invitation = manager.store.create_invitation(_profile(tmp_path))
    client = TestClient(create_remote_gateway_app(manager))

    rejected = client.post(
        "/v1/remote/pair",
        json={**invitation, "device_name": "Laptop"},
    )
    accepted = client.post(
        "/v1/remote/pair",
        json={
            "contract_version": invitation["contract_version"],
            "ticket_id": invitation["ticket_id"],
            "ticket_secret": invitation["ticket_secret"],
            "device_name": "Laptop",
        },
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 201


def test_gateway_rejects_browser_origins_even_with_a_valid_device(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    invitation = manager.store.create_invitation(_profile(tmp_path))
    _, credential = manager.store.consume_invitation(
        str(invitation["ticket_id"]),
        str(invitation["ticket_secret"]),
        "Laptop",
    )
    client = TestClient(create_remote_gateway_app(manager))

    response = client.get(
        "/v1/health",
        headers={
            "Authorization": f"Bearer {credential}",
            "Origin": "https://malicious.example",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["type"] == "remote_browser_origin_denied"


def test_remote_route_policy_is_positive_and_keeps_admin_paths_denied() -> None:
    assert is_remote_route_allowed("GET", "/v1/reader/documents")
    assert is_remote_route_allowed(
        "PATCH", f"/v1/reader/documents/{TEST_RESOURCE_ID}/content"
    )
    assert is_remote_route_allowed(
        "POST", f"/v1/reader/folders/{TEST_RESOURCE_ID}/privacy-lock/unlock"
    )
    assert not is_remote_route_allowed(
        "PUT", f"/v1/reader/folders/{TEST_RESOURCE_ID}/privacy-lock"
    )
    assert not is_remote_route_allowed("POST", "/v1/reader/browser-captures")
    assert not is_remote_route_allowed("GET", "/v1/reader/diagnostics")
    assert not is_remote_route_allowed("GET", "/v1/reader/remote/status")
    assert not is_remote_route_allowed("POST", "/v1/auth/rotate")
    assert not is_remote_route_allowed("GET", "/v1/reader/new-future-admin-route")
    assert not is_remote_route_allowed("GET", "/v1/reader/documents/..")
    assert not is_remote_route_allowed("GET", "/v1/reader/documents/document-1")


def test_every_registered_service_route_has_an_explicit_remote_decision(tmp_path: Path) -> None:
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"warmup_on_start": False},
                "reader": {"home_path": str(tmp_path / "reader")},
            }
        ),
        repo_root=tmp_path,
    )
    decisions: list[tuple[str, str, str | None]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/v1"):
            continue
        methods = getattr(route, "methods", None) or {"WEBSOCKET"}
        decisions.extend(
            (method, path, classify_remote_route(method, path)) for method in methods
        )

    assert decisions
    assert [item for item in decisions if item[2] is None] == []
    assert ("POST", "/v1/auth/rotate", "deny") in decisions
    assert ("WEBSOCKET", "/v1/reader/stream", "allow") in decisions


def test_gateway_rejects_credentials_in_query_strings(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    invitation = manager.store.create_invitation(_profile(tmp_path))
    _, credential = manager.store.consume_invitation(
        str(invitation["ticket_id"]),
        str(invitation["ticket_secret"]),
        "Laptop",
    )
    response = TestClient(create_remote_gateway_app(manager)).get(
        "/v1/health?token=do-not-put-secrets-here",
        headers={"Authorization": f"Bearer {credential}"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "remote_query_credential_denied"


def test_gateway_rejects_percent_encoded_resource_paths_before_proxying(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    invitation = manager.store.create_invitation(_profile(tmp_path))
    _, credential = manager.store.consume_invitation(
        str(invitation["ticket_id"]),
        str(invitation["ticket_secret"]),
        "Laptop",
    )

    response = TestClient(create_remote_gateway_app(manager)).get(
        f"/v1/reader/documents/%31{TEST_RESOURCE_ID[1:]}",
        headers={"Authorization": f"Bearer {credential}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["type"] == "remote_route_denied"


def test_failed_pairing_and_authentication_are_limited_by_client_ip(tmp_path: Path) -> None:
    client = TestClient(create_remote_gateway_app(_manager(tmp_path)))

    pairing = [
        client.post(
            "/v1/remote/pair",
            json={
                "contract_version": 1,
                "ticket_id": "missing",
                "ticket_secret": "x" * 43,
                "device_name": "Laptop",
            },
        )
        for _ in range(6)
    ]
    assert [response.status_code for response in pairing[:5]] == [401] * 5
    assert pairing[5].status_code == 429

    client = TestClient(create_remote_gateway_app(_manager(tmp_path / "auth")))
    authentication = [
        client.get("/v1/health", headers={"Authorization": "Bearer invalid"})
        for _ in range(6)
    ]
    assert [response.status_code for response in authentication[:5]] == [401] * 5
    assert authentication[5].status_code == 429


def test_device_stream_and_upload_leases_are_single_owner() -> None:
    leases = _DeviceLeaseSet()

    assert leases.try_acquire("device-1")
    assert not leases.try_acquire("device-1")
    assert leases.try_acquire("device-2")
    leases.release("device-1")
    assert leases.try_acquire("device-1")

    bounded = _DeviceLeaseSet(limit=2)
    assert bounded.try_acquire("device-1")
    assert bounded.try_acquire("device-2")
    assert not bounded.try_acquire("device-3")


def test_export_creation_has_a_separate_per_device_limit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    invitation = manager.store.create_invitation(_profile(tmp_path))
    _, credential = manager.store.consume_invitation(
        str(invitation["ticket_id"]),
        str(invitation["ticket_secret"]),
        "Laptop",
    )

    async def fake_proxy(*_args, **_kwargs):
        return JSONResponse({"ok": True})

    monkeypatch.setattr("tts_service.remote_gateway._proxy_http", fake_proxy)
    client = TestClient(create_remote_gateway_app(manager))
    responses = [
        client.post(
            "/v1/reader/exports",
            headers={"Authorization": f"Bearer {credential}"},
            json={"document_ids": ["document-1"]},
        )
        for _ in range(7)
    ]

    assert [response.status_code for response in responses[:6]] == [200] * 6
    assert responses[6].status_code == 429
    assert responses[6].json()["error"]["type"] == "remote_export_rate_limited"


def test_local_admin_routes_require_the_existing_local_token(tmp_path: Path, monkeypatch) -> None:
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"warmup_on_start": False},
                "reader": {"home_path": str(tmp_path / "reader")},
                "security": {
                    "allowed_origins": ["chrome-extension://trusted-extension"]
                },
            }
        ),
        repo_root=tmp_path,
    )
    manager = app.state.container.remote_access
    assert manager is not None
    profile = _profile(tmp_path)
    monkeypatch.setattr(manager, "load_profile", lambda: profile)
    client = TestClient(app, client=("127.0.0.1", 50000))
    headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}

    denied = client.get("/v1/reader/remote/status")
    invitation = client.post("/v1/reader/remote/invitations", headers=headers, json={})
    devices = client.get("/v1/reader/remote/devices", headers=headers)

    assert denied.status_code == 401
    assert invitation.status_code == 201
    assert "ticket_secret" in invitation.json()
    assert devices.status_code == 200
    assert devices.json() == {"devices": []}


def test_remote_admin_routes_reject_browser_origins_and_non_loopback_clients(
    tmp_path: Path,
) -> None:
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"warmup_on_start": False},
                "reader": {"home_path": str(tmp_path / "reader")},
                "security": {
                    "allowed_origins": ["chrome-extension://trusted-extension"]
                },
            }
        ),
        repo_root=tmp_path,
    )
    headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    browser = TestClient(app, client=("127.0.0.1", 50000)).get(
        "/v1/reader/remote/status",
        headers={**headers, "Origin": "chrome-extension://trusted-extension"},
    )
    non_loopback = TestClient(app, client=("10.42.0.2", 50000)).get(
        "/v1/reader/remote/status",
        headers=headers,
    )

    assert browser.status_code == 403
    assert non_loopback.status_code == 403
    assert browser.json()["error"]["type"] == "reader_remote_admin_local_only"


def test_remote_profile_json_has_no_credentials(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.configure(
        bind_host="10.42.0.1",
        port=7790,
        firewall_remote_address="10.42.0.2/32",
        firewall_interface_alias="WireGuard",
        start=False,
    )

    payload = json.loads(manager.profile_path.read_text(encoding="utf-8"))

    assert set(payload).isdisjoint({"credential", "ticket_secret", "local_token"})
