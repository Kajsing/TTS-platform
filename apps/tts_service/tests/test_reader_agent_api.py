from __future__ import annotations

import logging
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient
from reader_core import ReaderLibrary
from reader_core.agent_access import ChapterDelivery
from tts_service.config import AppConfig
from tts_service.main import create_app

AGENT = "/v1/reader/agent"
ADMIN = "/v1/reader/agent-access/grants"


@pytest.fixture
def agent_api(tmp_path):
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"warmup_on_start": False},
                "reader": {"home_path": str(tmp_path / "reader"), "exports": {"formats": ["wav"]}},
            }
        ),
        repo_root=tmp_path,
    )
    client = TestClient(app, client=("127.0.0.1", 45678))
    owner = {"Authorization": "Bearer " + app.state.container.auth.token}
    folder = client.post("/v1/reader/folders", headers=owner, json={"name": "Agent inbox"}).json()
    provision = client.post(ADMIN, headers=owner, json={"folder_id": folder["id"]})
    assert provision.status_code == 201, provision.text
    secret = provision.json()["credential"]
    agent = {"Authorization": "Bearer " + secret}
    yield client, app, owner, agent, provision.json()["grant"]
    client.close()


def create(client, agent, text="Original text.\n\nNext paragraph."):
    result = client.post(AGENT + "/articles", headers=agent, json={"title": "Story", "text": text})
    assert result.status_code == 201, result.text
    return result.json()


def chapter(**changes):
    return asdict(
        ChapterDelivery(
            **(
                {
                    "story_key": "story:1",
                    "chapter_key": "chapter:2",
                    "retry_key": "retry:1",
                    "source_url": "https://example.com/chapter2",
                    "title": "New chapter",
                    "text": "Chapter text.",
                }
                | changes
            )
        )
    ) | {"expected_row_version": 1}


def test_owner_setup_agent_crud_and_normal_reader_access(agent_api):
    client, _, owner, agent, grant = agent_api
    status = client.get(ADMIN, headers=owner)
    assert status.status_code == 200 and "credential" not in status.text
    workspace = client.get(AGENT + "/workspace", headers=agent)
    assert workspace.json()["folder_id"] == grant["folder_id"]
    article = create(client, agent)
    identifier = article["id"]
    assert article["folder_id"] == grant["folder_id"]
    normal = client.get(f"/v1/reader/documents/{identifier}", headers=owner)
    assert normal.status_code == 200 and normal.json()["title"] == "Story"
    renamed = client.patch(
        AGENT + f"/articles/{identifier}",
        headers=agent,
        json={
            "title": "Renamed story",
            "expected_row_version": 1,
        },
    )
    assert renamed.status_code == 200
    replaced = client.patch(
        AGENT + f"/articles/{identifier}/text",
        headers=agent,
        json={
            "old_text": "Original",
            "new_text": "Improved",
            "expected_row_version": 2,
        },
    )
    assert replaced.status_code == 200, replaced.text
    appended = client.post(
        AGENT + f"/articles/{identifier}/append",
        headers=agent,
        json={
            "text": "Appended content.",
            "expected_row_version": 3,
        },
    )
    assert appended.status_code == 200
    found = client.get(AGENT + "/articles", headers=agent, params={"query": "Improved"})
    assert [item["id"] for item in found.json()["items"]] == [identifier]
    page = client.get(AGENT + f"/articles/{identifier}", headers=agent, params={"limit": 4}).json()
    assert page["text"] == "Impr" and page["next_offset"] == 4
    rest = client.get(
        AGENT + f"/articles/{identifier}",
        headers=agent,
        params={
            "offset": 4,
            "expected_row_version": 4,
        },
    )
    assert (page["text"] + rest.json()["text"]).endswith("Appended content.")
    revoked = client.delete(ADMIN + "/" + grant["id"], headers=owner)
    assert revoked.status_code == 200
    assert client.get(AGENT + "/workspace", headers=agent).status_code == 403


def test_agent_token_cannot_use_owner_reader_tts_or_admin_routes(agent_api):
    client, _, owner, agent, _ = agent_api
    for method, path in (
        ("GET", ADMIN),
        ("POST", ADMIN),
        ("DELETE", ADMIN + "/not-a-grant"),
        ("GET", "/v1/reader/documents"),
        ("POST", "/v1/reader/documents"),
        ("GET", "/v1/reader/diagnostics"),
        ("POST", "/v1/tts"),
        ("POST", "/v1/auth/rotate"),
        ("POST", "/v1/reader/remote/setup"),
    ):
        response = client.request(method, path, headers=agent, content="invalid json")
        assert response.status_code == 401, (path, response.text)
    # Conversely the broad owner token does not masquerade as a folder grant.
    assert client.get(AGENT + "/workspace", headers=owner).status_code == 403
    assert client.post(AGENT + "/articles", content="invalid json").status_code == 403


def test_native_loopback_and_auth_required_even_for_admin(agent_api):
    client, app, owner, agent, _ = agent_api
    for origin in ("https://example.com", "null", ""):
        assert (
            client.get(AGENT + "/workspace", headers=agent | {"Origin": origin}).status_code == 403
        )
        assert client.get(ADMIN, headers=owner | {"Origin": origin}).status_code == 403
    remote = TestClient(app, client=("192.0.2.30", 45678))
    assert remote.get(ADMIN, headers=owner).status_code == 403
    assert remote.get(AGENT + "/workspace", headers=agent).status_code == 403


def test_isolated_agent_rate_budget_and_preparse_body_limit(agent_api):
    client, app, owner, agent, _ = agent_api
    too_large = client.post(AGENT + "/articles", headers=agent, content="x" * (2 * 1024 * 1024 + 1))
    assert too_large.status_code == 413
    app.state.reader_agent_limiter.requests_per_minute = 1
    blocked = client.get(AGENT + "/workspace", headers=agent)
    assert blocked.status_code == 429
    assert client.get("/v1/reader/capabilities", headers=owner).status_code == 200


def test_scope_excludes_other_folders_direct_ids_search_and_pagination(agent_api):
    client, app, _, agent, _ = agent_api
    service = app.state.container.reader.service
    hidden = ReaderLibrary(service.repository).create_plain_text_document(
        title="Hidden",
        text="Secret needle",
    )
    first = create(client, agent)
    second = create(client, agent, "Another visible document.")
    page = client.get(AGENT + "/articles", headers=agent, params={"limit": 1}).json()
    other = client.get(
        AGENT + "/articles",
        headers=agent,
        params={
            "limit": 1,
            "cursor": page["next_cursor"],
        },
    ).json()
    assert {page["items"][0]["id"], other["items"][0]["id"]} == {first["id"], second["id"]}
    assert (
        client.get(AGENT + "/articles", headers=agent, params={"query": "Secret"}).json()["items"]
        == []
    )
    for method, suffix, payload in (
        ("GET", "", None),
        ("GET", "/chapters", None),
        ("POST", "/chapters", chapter()),
        ("PATCH", "", {"title": "No", "expected_row_version": 1}),
        ("POST", "/append", {"text": "No", "expected_row_version": 1}),
    ):
        response = client.request(
            method, AGENT + f"/articles/{hidden.id}" + suffix, headers=agent, json=payload
        )
        assert response.status_code == 403


def test_playback_lease_busy_without_stopping_and_stale_desktop_save(agent_api):
    client, app, owner, agent, _ = agent_api
    article = create(client, agent)
    identifier = article["id"]
    service = app.state.container.reader.service
    with service.content_leases.lease(identifier, "desktop-stream"):
        for path, payload in (
            ("append", {"text": "Cannot write", "expected_row_version": 1}),
            ("chapters", chapter()),
        ):
            response = client.post(
                AGENT + f"/articles/{identifier}/{path}", headers=agent, json=payload
            )
            assert response.status_code == 409
            assert response.json()["error"]["type"] == "reader_document_locked"
        assert service.content_leases.is_locked(identifier)
        assert client.get(AGENT + f"/articles/{identifier}", headers=agent).status_code == 200
    imported = client.post(
        AGENT + f"/articles/{identifier}/chapters", headers=agent, json=chapter()
    )
    assert imported.status_code == 200 and imported.json()["outcome"] == "imported"
    retry = client.post(AGENT + f"/articles/{identifier}/chapters", headers=agent, json=chapter())
    assert retry.json()["outcome"] == "already_imported"
    conflict = client.post(
        AGENT + f"/articles/{identifier}/chapters", headers=agent, json=chapter(text="Changed")
    )
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["type"] == "reader_agent_conflict"
    )
    block = service.repository.list_blocks(identifier)[0]
    stale_desktop = client.patch(
        f"/v1/reader/documents/{identifier}/content",
        headers=owner,
        json={
            "block_id": block.id,
            "start_offset": 0,
            "end_offset": 3,
            "replacement_text": "Local unsaved work",
            "expected_row_version": 1,
        },
    )
    assert stale_desktop.status_code == 409, stale_desktop.text
    assert stale_desktop.json()["error"]["type"] == "reader_revision_conflict"
    assert (
        "Local unsaved work"
        not in client.get(AGENT + f"/articles/{identifier}", headers=agent).json()["text"]
    )


def test_new_contract_rejects_extra_fields_and_string_revisions(agent_api):
    client, _, _, agent, _ = agent_api
    escaped = client.post(
        AGENT + "/articles",
        headers=agent,
        json={
            "title": "No",
            "text": "No",
            "folder_id": "root",
        },
    )
    assert escaped.status_code == 400
    article = create(client, agent)
    wrong_revision = client.post(
        AGENT + f"/articles/{article['id']}/append",
        headers=agent,
        json={
            "text": "No",
            "expected_row_version": "1",
        },
    )
    assert wrong_revision.status_code == 400


def test_agent_http_diagnostics_do_not_include_secrets_text_or_source_urls(
    agent_api, caplog, monkeypatch
):
    client, app, _, agent, _ = agent_api
    logger = app.state.container.observability.logger
    monkeypatch.setattr(logger, "propagate", True)
    with caplog.at_level(logging.INFO, logger=logger.name):
        article = create(client, agent, text="PrivateBodyNeedle")
        client.get(AGENT + f"/articles/{article['id']}", headers=agent)
        client.get(AGENT + "/" + agent["Authorization"].removeprefix("Bearer "), headers=agent)
        client.get(AGENT + "/workspace", headers=agent | {"X-Request-Id": "PrivateBodyNeedle"})
        client.post(AGENT + f"/articles/{article['id']}/chapters", headers=agent, json=chapter())
    logs = "\n".join(record.message for record in caplog.records if record.name == logger.name)
    assert "http_request" in logs
    assert "PrivateBodyNeedle" not in logs
    assert "rdr_agent_" not in logs
    assert "example.com" not in logs
    assert article["id"] not in logs


@pytest.mark.parametrize("config", [{"reader": {"enabled": False}}, {"auth": {"enabled": False}}])
def test_agent_access_is_unavailable_without_reader_or_owner_auth(tmp_path, config):
    config = {"tts": {"warmup_on_start": False}} | config
    config.setdefault("reader", {})["home_path"] = str(tmp_path / "reader")
    app = create_app(config=AppConfig.from_mapping(config), repo_root=tmp_path)
    client = TestClient(app, client=("127.0.0.1", 45678))
    owner = {"Authorization": "Bearer " + (app.state.container.auth.token or "")}
    response = client.get(ADMIN, headers=owner)
    assert response.status_code == 503, response.text
