from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from reader_core import FolderDocumentVersion, ReaderFolderPrivacy, ReaderLibrary
from reader_core.models import utc_now
from tts_service.config import AppConfig
from tts_service.main import create_app

AGENT = "/v1/reader/agent"
ADMIN = "/v1/reader/agent-access/grants"


@pytest.fixture
def content_api(tmp_path):
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
    folder = client.post("/v1/reader/folders", headers=owner, json={"name": "Content test"}).json()
    provision = client.post(ADMIN, headers=owner, json={"folder_id": folder["id"]}).json()
    agent = {"Authorization": "Bearer " + provision["credential"]}
    initial = "Preface 😀.\n\nIntro end."
    chapter = "Chapter 2\n\nAlpha needle Ω😀.\n\nLast sentence."
    article = client.post(
        AGENT + "/articles", headers=agent, json={"title": "Story", "text": initial}
    ).json()
    delivered = client.post(
        AGENT + f"/articles/{article['id']}/chapters",
        headers=agent,
        json={
            "story_key": "story",
            "chapter_key": "chapter-2",
            "retry_key": "chapter-2",
            "title": "Two",
            "text": chapter,
            "source_url": "https://example.com/story/2",
            "expected_row_version": 1,
        },
    )
    assert delivered.status_code == 200, delivered.text
    yield client, app, owner, agent, provision["grant"], article["id"], initial + "\n\n" + chapter
    client.close()


def requests_for(identifier):
    base = AGENT + f"/articles/{identifier}"
    return (
        (base + "/content-chapters", {"expected_row_version": 2}),
        (base + "/chapter-text", {"chapter_id": "root", "expected_row_version": 2}),
        (base + "/search", {"query": "needle", "expected_row_version": 2}),
    )


def test_structural_discovery_chapter_readback_and_search_over_http(content_api):
    client, _, _, agent, _, identifier, expected_text = content_api
    base = AGENT + f"/articles/{identifier}"
    first = client.get(
        base + "/content-chapters",
        headers=agent,
        params={
            "expected_row_version": 2,
            "limit": 1,
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["chapter_count"] == 2 and first.json()["next_offset"] == 1
    last = client.get(
        base + "/content-chapters",
        headers=agent,
        params={
            "expected_row_version": 2,
            "offset": 1,
        },
    ).json()
    chapters = first.json()["items"] + last["items"]
    assert [item["title"] for item in chapters] == ["Chapter 1", "Two"]
    text = ""
    for chapter in chapters:
        offset = 0
        while True:
            response = client.get(
                base + "/chapter-text",
                headers=agent,
                params={
                    "chapter_id": chapter["id"],
                    "expected_row_version": 2,
                    "offset": offset,
                    "limit": 7,
                },
            )
            assert response.status_code == 200, response.text
            page = response.json()
            assert len(page["text"]) <= 7 and page["article"]["row_version"] == 2
            text += page["text"]
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
    assert text == expected_text
    normal = client.get(base, headers=agent).json()
    assert normal["text"] == text
    found = client.get(
        base + "/search",
        headers=agent,
        params={
            "expected_row_version": 2,
            "query": "needle Ω😀.",
        },
    )
    assert found.status_code == 200, found.text
    assert found.json()["items"] == [
        {
            "offset": expected_text.index("needle"),
            "end_offset": expected_text.index("needle") + 10,
            "text": "needle Ω😀.",
        }
    ]
    # Current structural IDs are not delivery receipt IDs.
    receipt = client.get(base + "/chapters", headers=agent).json()["items"][0]
    assert receipt["id"] not in {item["id"] for item in chapters}


def test_all_content_reads_remain_available_during_playback_lease(content_api):
    client, app, _, agent, _, identifier, _ = content_api
    service = app.state.container.reader.service
    with service.content_leases.lease(identifier, "desktop-playback"):
        for path, params in requests_for(identifier):
            response = client.get(path, headers=agent, params=params)
            assert response.status_code == 200, response.text
            assert service.content_leases.is_locked(identifier)


def test_stale_revision_and_missing_current_marker_are_explicit_conflicts(content_api):
    client, _, _, agent, _, identifier, _ = content_api
    for path, params in requests_for(identifier):
        response = client.get(path, headers=agent, params=params | {"expected_row_version": 1})
        assert response.status_code == 409, response.text
        assert response.json()["error"]["type"] == "reader_revision_conflict"
    missing = client.get(
        AGENT + f"/articles/{identifier}/chapter-text",
        headers=agent,
        params={
            "chapter_id": "removed",
            "expected_row_version": 2,
        },
    )
    assert missing.status_code == 409
    assert missing.json()["error"]["type"] == "reader_agent_conflict"


@pytest.mark.parametrize("change", ["revoke", "move", "delete", "privacy"])
def test_content_routes_recheck_scope_after_owner_changes(content_api, change):
    client, app, owner, agent, grant, identifier, _ = content_api
    repository = app.state.container.reader.service.repository
    if change == "revoke":
        assert client.delete(ADMIN + "/" + grant["id"], headers=owner).status_code == 200
    elif change == "move":
        repository.move_documents((FolderDocumentVersion(identifier, 2),), folder_id=None)
    elif change == "delete":
        repository.soft_delete_document(identifier, expected_row_version=2)
    else:
        repository.set_folder_privacy(
            ReaderFolderPrivacy(grant["folder_id"], "x" * 64, "y" * 64, utc_now()),
            expected_row_version=1,
        )
    for path, params in requests_for(identifier):
        response = client.get(path, headers=agent, params=params)
        assert response.status_code == 403, response.text


def test_content_routes_require_read_permission_and_do_not_leak_outside_articles(content_api):
    client, app, _, agent, grant, identifier, _ = content_api
    service = app.state.container.reader.service
    hidden = ReaderLibrary(service.repository).create_plain_text_document(
        title="Private",
        text="needle outside",
        folder_id=None,
    )
    _, secret = service.agents.store.provision(
        grant["folder_id"], "List only", operations=("list",)
    )
    limited = {"Authorization": "Bearer " + secret}
    for target, headers in ((identifier, limited), (hidden.id, agent), (str(uuid.uuid4()), agent)):
        for path, params in requests_for(target):
            response = client.get(path, headers=headers, params=params)
            assert response.status_code == 403, response.text
            assert "needle outside" not in response.text


def test_content_routes_reject_browser_remote_and_owner_auth(content_api):
    client, app, owner, agent, _, identifier, _ = content_api
    for path, params in requests_for(identifier):
        assert client.get(path, headers=owner, params=params).status_code == 403
        for origin in ("", "null", "https://example.com"):
            assert (
                client.get(path, headers=agent | {"Origin": origin}, params=params).status_code
                == 403
            )
        with TestClient(app, client=("192.0.2.30", 45678)) as remote:
            assert remote.get(path, headers=agent, params=params).status_code == 403


@pytest.mark.parametrize(
    "suffix,params",
    [
        ("content-chapters", {"limit": 101}),
        ("content-chapters", {"offset": -1}),
        ("chapter-text", {"chapter_id": "root", "limit": 20_001}),
        ("chapter-text", {"chapter_id": "root", "offset": -1}),
        ("chapter-text", {"chapter_id": "x" * 101}),
        ("search", {"query": "x" * 201}),
        ("search", {"query": "x", "limit": 101}),
        ("search", {"query": "x", "offset": -1}),
    ],
)
def test_content_route_limits_reject_invalid_query_parameters(content_api, suffix, params):
    client, _, _, agent, _, identifier, _ = content_api
    response = client.get(
        AGENT + f"/articles/{identifier}/{suffix}",
        headers=agent,
        params={
            "expected_row_version": 2,
        }
        | params,
    )
    assert response.status_code in {400, 422}, response.text


def test_corrupt_marker_json_is_explicit_but_search_does_not_depend_on_it(content_api):
    client, app, _, agent, _, identifier, _ = content_api
    with app.state.container.reader.service.repository._write() as connection:
        connection.execute(
            "UPDATE reader_documents SET metadata_json = '{' WHERE id = ?", (identifier,)
        )
    for path, params in requests_for(identifier)[:2]:
        response = client.get(path, headers=agent, params=params)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["type"] == "reader_agent_conflict"
    path, params = requests_for(identifier)[2]
    assert client.get(path, headers=agent, params=params).status_code == 200
