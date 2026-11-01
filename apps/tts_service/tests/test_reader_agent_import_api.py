from __future__ import annotations

import uuid
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient
from reader_core import FolderDocumentVersion, ReaderFolder, ReaderValidationError
from reader_core.agent_access import ChapterDelivery
from reader_core.models import utc_now
from tts_service.config import AppConfig
from tts_service.main import create_app

AGENT = "/v1/reader/agent"
ADMIN = "/v1/reader/agent-access/grants"


def chapter(number, **changes):
    return asdict(
        ChapterDelivery(
            **(
                {
                    "story_key": "story",
                    "chapter_key": str(number),
                    "retry_key": f"retry-{number}",
                    "source_url": f"https://example.com/{number}",
                    "title": f"Chapter {number}",
                    "text": "abcdefgh",
                    "order_index": number,
                }
                | changes
            )
        )
    )


def preparation(**changes):
    return {
        "title": "T",
        "intro": "",
        "retry_key": "plan-1",
        "max_characters": 22,
        "chapters": [chapter(1), chapter(2), chapter(3)],
    } | changes


@pytest.fixture
def import_api(tmp_path):
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
    folder = client.post("/v1/reader/folders", headers=owner, json={"name": "Imports"}).json()
    provision = client.post(ADMIN, headers=owner, json={"folder_id": folder["id"]}).json()
    agent = {"Authorization": "Bearer " + provision["credential"]}
    yield client, app, owner, agent, provision["grant"]
    client.close()


def prepare(client, agent, **changes):
    response = client.post(AGENT + "/import-plans", headers=agent, json=preparation(**changes))
    assert response.status_code == 200, response.text
    return response.json()


def deliver(client, agent, plan, number, **changes):
    return client.post(
        AGENT + f"/import-plans/{plan['plan_id']}/chapters",
        headers=agent,
        json={"chapter": chapter(number, **changes)},
    )


def status(client, agent, **params):
    return client.get(
        AGENT + "/stories/status", headers=agent, params={"story_key": "story"} | params
    )


def test_preview_delivery_rollover_readback_and_story_status_http(import_api):
    client, _, _, agent, _ = import_api
    plan = prepare(client, agent)
    assert plan["policy"] == {"max_characters": 22, "max_blocks": 20_000}
    assert [part["chapter_keys"] for part in plan["parts"]] == [["1", "2"], ["3"]]
    assert client.get(AGENT + "/articles", headers=agent).json()["items"] == []
    replay = prepare(client, agent)
    assert replay["plan_id"] == plan["plan_id"] and replay["outcome"] == "already_prepared"
    results = []
    for number in (1, 2, 3):
        response = deliver(client, agent, plan, number)
        assert response.status_code == 200, response.text
        results.append(response.json())
    assert [result["complete"] for result in results] == [False, False, True]
    assert results[0]["document_id"] == results[1]["document_id"] != results[2]["document_id"]
    assert deliver(client, agent, plan, 1).json()["outcome"] == "already_imported"
    for result, expected in (
        (results[1], "T\n\nabcdefgh\n\nabcdefgh"),
        (results[2], "T\n\nabcdefgh"),
    ):
        offset, text = 0, ""
        version = None
        while True:
            params = {"offset": offset, "limit": 5}
            if version is not None:
                params["expected_row_version"] = version
            response = client.get(
                AGENT + f"/articles/{result['document_id']}", headers=agent, params=params
            )
            assert response.status_code == 200, response.text
            page = response.json()
            version = page["article"]["row_version"]
            text += page["text"]
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        assert text == expected and len(text) <= 22
    first = status(client, agent, limit=2).json()
    rest = status(client, agent, offset=first["next_offset"]).json()
    assert first["story_version"] == 3
    assert first["append_only_receipts"] and not first["current_text_verified"]
    assert [item["part_number"] for item in first["items"] + rest["items"]] == [1, 1, 2]
    assert rest["next_offset"] is None


def test_default_policy_and_safe_creation_replay_http(import_api):
    client, _, _, agent, _ = import_api
    payload = preparation()
    payload.pop("max_characters")
    response = client.post(AGENT + "/import-plans", headers=agent, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["policy"] == {"max_characters": 900_000, "max_blocks": 20_000}
    creation = {"title": "Created once", "text": "Body", "retry_key": "creation-1"}
    first = client.post(AGENT + "/articles", headers=agent, json=creation)
    second = client.post(AGENT + "/articles", headers=agent, json=creation)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    conflict = client.post(AGENT + "/articles", headers=agent, json=creation | {"text": "Changed"})
    assert conflict.status_code == 409


def test_managed_receipt_blocks_duplicate_m1_delivery_to_another_article(import_api):
    client, _, _, agent, _ = import_api
    plan = prepare(client, agent)
    assert deliver(client, agent, plan, 1).status_code == 200
    other = client.post(
        AGENT + "/articles", headers=agent, json={"title": "Other", "text": "Intro"}
    )
    response = client.post(
        AGENT + f"/articles/{other.json()['id']}/chapters",
        headers=agent,
        json=chapter(1) | {"expected_row_version": 1},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["type"] == "reader_agent_conflict"
    assert len(status(client, agent).json()["items"]) == 1


def test_playback_lease_prevents_progress_without_stopping_reads(import_api):
    client, app, _, agent, _ = import_api
    plan = prepare(client, agent)
    first = deliver(client, agent, plan, 1).json()
    service = app.state.container.reader.service
    with service.content_leases.lease(first["document_id"], "desktop-stream"):
        response = deliver(client, agent, plan, 2)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["type"] == "reader_document_locked"
        assert prepare(client, agent)["next_index"] == 1
        assert len(status(client, agent).json()["items"]) == 1
        assert (
            client.get(AGENT + f"/articles/{first['document_id']}", headers=agent).status_code
            == 200
        )
        assert service.content_leases.is_locked(first["document_id"])
    assert deliver(client, agent, plan, 2).json()["next_index"] == 2


def test_application_target_race_cannot_skip_required_existing_part_lease(import_api, monkeypatch):
    client, app, _, agent, _ = import_api
    plan = prepare(client, agent)
    store = app.state.container.reader.service.agents.store
    original = store.import_target
    raced = False

    def target(credential, plan_id, chapter_key):
        nonlocal raced
        chosen = original(credential, plan_id, chapter_key)
        if chapter_key == "2" and not raced:
            raced = True
            # Another writer creates the part after target selection, before the
            # application can acquire a lease for that newly existing document.
            app.state.container.reader.service.agents.run(
                credential,
                "import_chapter",
                plan_id=plan_id,
                delivery=ChapterDelivery(**chapter(1)),
            )
        return chosen

    monkeypatch.setattr(store, "import_target", target)
    response = deliver(client, agent, plan, 2)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["type"] == "reader_agent_conflict"
    assert len(status(client, agent).json()["items"]) == 1
    assert prepare(client, agent)["next_index"] == 1
    assert deliver(client, agent, plan, 2).json()["next_index"] == 2


def test_competing_previews_and_payload_order_conflicts_leave_progress_unchanged(import_api):
    client, _, _, agent, _ = import_api
    plan = prepare(client, agent)
    other = prepare(client, agent, retry_key="other", chapters=[chapter(4)])
    for response in (
        deliver(client, agent, plan, 2),
        deliver(client, agent, plan, 1, text="changed"),
    ):
        assert response.status_code == 409, response.text
    assert client.get(AGENT + "/articles", headers=agent).json()["items"] == []
    assert deliver(client, agent, plan, 1).status_code == 200
    stale = deliver(client, agent, other, 4)
    assert stale.status_code == 409 and stale.json()["error"]["type"] == "reader_agent_conflict"
    assert prepare(client, agent, retry_key="other", chapters=[chapter(4)])["next_index"] == 0


def test_failed_first_delivery_rolls_back_created_part_and_receipt_http(import_api, monkeypatch):
    client, app, _, agent, _ = import_api
    plan = prepare(client, agent)
    store = app.state.container.reader.service.agents.store
    original = store._validate_part_after_append

    def fail(*_):
        raise ReaderValidationError("Injected validation failure")

    monkeypatch.setattr(store, "_validate_part_after_append", fail)
    response = deliver(client, agent, plan, 1)
    assert response.status_code == 400, response.text
    assert client.get(AGENT + "/articles", headers=agent).json()["items"] == []
    assert status(client, agent).json()["items"] == []
    assert prepare(client, agent)["next_index"] == 0
    monkeypatch.setattr(store, "_validate_part_after_append", original)
    assert deliver(client, agent, plan, 1).json()["next_index"] == 1


def test_other_folder_cannot_address_plan_or_observe_story_status(import_api):
    client, app, _, agent, _ = import_api
    plan = prepare(client, agent)
    first = deliver(client, agent, plan, 1).json()
    service = app.state.container.reader.service
    now = utc_now()
    folder = service.repository.create_folder(
        ReaderFolder(str(uuid.uuid4()), "Other", "other", now, now)
    )
    _, secret = service.agents.store.provision(folder.id, "Other")
    outsider = {"Authorization": "Bearer " + secret}
    assert deliver(client, outsider, plan, 2).status_code == 403
    assert status(client, outsider).json()["items"] == []
    service.repository.move_documents(
        (FolderDocumentVersion(first["document_id"], 2),), folder_id=None
    )
    assert deliver(client, agent, plan, 1).status_code == 403
    assert deliver(client, agent, plan, 2).status_code == 403
    assert status(client, agent).status_code == 403


def test_managed_routes_require_operation_permissions(import_api):
    client, app, _, agent, grant = import_api
    plan = prepare(client, agent)
    store = app.state.container.reader.service.agents.store
    for operations in (("create",), ("deliver",), ("read",)):
        _, secret = store.provision(grant["folder_id"], "Limited", operations=operations)
        limited = {"Authorization": "Bearer " + secret}
        assert (
            client.post(AGENT + "/import-plans", headers=limited, json=preparation()).status_code
            == 403
        )
        assert deliver(client, limited, plan, 1).status_code == 403
        assert status(client, limited).status_code == 403


def test_managed_routes_are_native_loopback_only_and_reject_owner_token(import_api):
    client, app, owner, agent, _ = import_api
    plan = prepare(client, agent)
    for headers in (
        owner,
        agent | {"Origin": ""},
        agent | {"Origin": "null"},
        agent | {"Origin": "https://example.com"},
    ):
        assert (
            client.post(AGENT + "/import-plans", headers=headers, json=preparation()).status_code
            == 403
        )
        assert deliver(client, headers, plan, 1).status_code == 403
        assert status(client, headers).status_code == 403
    with TestClient(app, client=("192.0.2.30", 45678)) as remote:
        assert (
            remote.post(AGENT + "/import-plans", headers=agent, json=preparation()).status_code
            == 403
        )
        assert deliver(remote, agent, plan, 1).status_code == 403
        assert status(remote, agent).status_code == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"max_characters": 0},
        {"max_characters": -1},
        {"max_characters": 1_000_001},
        {"max_characters": "22"},
        {"max_characters": True},
        {"max_blocks": -1},
        {"max_blocks": 20_001},
        {"chapters": []},
        {"unexpected": True},
    ],
)
def test_import_preview_strict_payload_validation(import_api, changes):
    client, _, _, agent, _ = import_api
    response = client.post(AGENT + "/import-plans", headers=agent, json=preparation(**changes))
    assert response.status_code == 400, response.text
    assert response.json()["error"]["type"] == "invalid_request"


@pytest.mark.parametrize("params", [{"offset": -1}, {"limit": 0}, {"limit": 101}])
def test_story_status_query_validation(import_api, params):
    client, _, _, agent, _ = import_api
    response = status(client, agent, **params)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["type"] == "invalid_request"
