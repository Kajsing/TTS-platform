from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tts_service.config import AppConfig
from tts_service.main import create_app

AGENT = "/v1/reader/agent"
ADMIN = "/v1/reader/agent-access/grants"
PAYLOAD = {"title": "Story part", "text": "Original body.", "retry_key": "part:one"}


@pytest.fixture
def creation_api(tmp_path):
    config = AppConfig.from_mapping(
        {
            "tts": {"warmup_on_start": False},
            "reader": {"home_path": str(tmp_path / "reader"), "exports": {"formats": ["wav"]}},
        }
    )
    app = create_app(config=config, repo_root=tmp_path)
    with TestClient(app, client=("127.0.0.1", 45678)) as client:
        owner = {"Authorization": "Bearer " + app.state.container.auth.token}
        folder = client.post("/v1/reader/folders", headers=owner, json={"name": "Inbox"}).json()
        provision = client.post(ADMIN, headers=owner, json={"folder_id": folder["id"]})
        assert provision.status_code == 201, provision.text
        agent = {"Authorization": "Bearer " + provision.json()["credential"]}
        yield client, app, owner, agent, provision.json()["grant"], config


def _create(client, agent, payload=None):
    result = client.post(
        AGENT + "/articles", headers=agent, json=PAYLOAD if payload is None else payload
    )
    assert result.status_code == 201, result.text
    return result.json()


def test_creation_identity_survives_service_reconstruction_and_payload_changes_conflict(
    creation_api, tmp_path
):
    client, _, _, agent, _, config = creation_api
    article = _create(client, agent)
    assert _create(client, agent)["id"] == article["id"]
    # A new service/container must recover the identity from persistent storage.
    restarted = create_app(config=config, repo_root=tmp_path)
    with TestClient(restarted, client=("127.0.0.1", 45679)) as second:
        assert _create(second, agent)["id"] == article["id"]
        for changes in ({"text": "Different body."}, {"title": "Different title"}):
            conflict = second.post(AGENT + "/articles", headers=agent, json=PAYLOAD | changes)
            assert conflict.status_code == 409
            assert conflict.json()["error"]["type"] == "reader_agent_conflict"
        listed = second.get(AGENT + "/articles", headers=agent)
        assert [item["id"] for item in listed.json()["items"]] == [article["id"]]


@pytest.mark.parametrize("new_body", ["Edited body.", ""])
def test_creation_replay_returns_current_metadata_without_restoring_owner_edits(
    creation_api, new_body
):
    client, app, _, agent, _, _ = creation_api
    article = _create(client, agent)
    identifier = article["id"]
    rename = client.patch(
        AGENT + f"/articles/{identifier}",
        headers=agent,
        json={"title": "Owner title", "expected_row_version": 1},
    )
    assert rename.status_code == 200
    removal = client.patch(
        AGENT + f"/articles/{identifier}/text",
        headers=agent,
        json={"old_text": "Original body.", "new_text": new_body, "expected_row_version": 2},
    )
    assert removal.status_code == 200
    # Idempotent replay is metadata-only, including while the user is reading.
    leases = app.state.container.reader.service.content_leases
    with leases.lease(identifier, "reading"):
        replay = _create(client, agent)
        assert leases.is_locked(identifier)
    assert replay["id"] == identifier and replay["row_version"] == 3
    assert replay["title"] == "Owner title"
    text = client.get(AGENT + f"/articles/{identifier}", headers=agent).json()["text"]
    assert text == new_body


@pytest.mark.parametrize("change", ["move", "delete", "revoke"])
def test_creation_replay_denies_removed_scope_without_recreating_article(creation_api, change):
    client, app, owner, agent, grant, _ = creation_api
    article = _create(client, agent)
    identifier = article["id"]
    if change == "move":
        changed = client.post(
            "/v1/reader/folders/move-documents",
            headers=owner,
            json={
                "documents": [{"document_id": identifier, "expected_row_version": 1}],
                "target_folder_id": None,
            },
        )
    elif change == "delete":
        changed = client.delete(
            f"/v1/reader/documents/{identifier}",
            headers=owner,
            params={"expected_row_version": 1},
        )
    else:
        changed = client.delete(ADMIN + "/" + grant["id"], headers=owner)
    assert changed.status_code == 200, changed.text
    response = client.post(AGENT + "/articles", headers=agent, json=PAYLOAD)
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "reader_agent_unauthorized"
    # The original remains the sole document; retry cannot create a replacement.
    repository = app.state.container.reader.service.repository
    with repository._connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reader_documents").fetchone()[0] == 1


def test_creation_keys_are_folder_scoped_and_recheck_create_permission(creation_api):
    client, app, owner, agent, grant, _ = creation_api
    first = _create(client, agent)
    folder = client.post("/v1/reader/folders", headers=owner, json={"name": "Other"}).json()
    provision = client.post(ADMIN, headers=owner, json={"folder_id": folder["id"]}).json()
    other_agent = {"Authorization": "Bearer " + provision["credential"]}
    other = _create(client, other_agent)
    assert first["id"] != other["id"]
    assert first["folder_id"] == grant["folder_id"] and other["folder_id"] == folder["id"]
    assert _create(client, agent)["id"] == first["id"]
    assert _create(client, other_agent)["id"] == other["id"]
    agents = app.state.container.reader.service.agents
    _, limited_secret = agents.store.provision(
        grant["folder_id"], "Read only", operations=("read",)
    )
    denied = client.post(
        AGENT + "/articles", headers={"Authorization": "Bearer " + limited_secret}, json=PAYLOAD
    )
    assert denied.status_code == 403


@pytest.mark.parametrize("retry_key", ["", " ", "x" * 201, "bad\x00key", True, 2])
def test_invalid_creation_keys_fail_without_creating_articles(creation_api, retry_key):
    client, _, _, agent, _, _ = creation_api
    response = client.post(
        AGENT + "/articles", headers=agent, json=PAYLOAD | {"retry_key": retry_key}
    )
    assert response.status_code == 400
    assert client.get(AGENT + "/articles", headers=agent).json()["items"] == []


def test_ordinary_creation_without_identity_still_creates_separate_articles(creation_api):
    client, _, _, agent, _, _ = creation_api
    ordinary = {key: value for key, value in PAYLOAD.items() if key != "retry_key"}
    assert _create(client, agent, ordinary)["id"] != _create(client, agent, ordinary)["id"]
