from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reader_core import ReaderDatabaseError
from tts_service.config import AppConfig
from tts_service.main import create_app


def build_reader_bundle(
    tmp_path: Path,
    *,
    reader_config: dict[str, object] | None = None,
    security_config: dict[str, object] | None = None,
) -> tuple[TestClient, dict[str, str], object]:
    reader = {"home_path": str(tmp_path / "reader")}
    if reader_config:
        reader.update(reader_config)
    config_data: dict[str, object] = {
        "tts": {"warmup_on_start": False},
        "reader": reader,
    }
    if security_config:
        config_data["security"] = security_config
    app = create_app(config=AppConfig.from_mapping(config_data), repo_root=tmp_path)
    headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    return TestClient(app), headers, app


def create_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str = "Reader document",
    text: str = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.",
    allow_duplicate: bool = False,
) -> dict[str, object]:
    response = client.post(
        "/v1/reader/documents",
        headers=headers,
        json={
            "title": title,
            "source_type": "plain_text",
            "text": text,
            "language_hint": "da",
            "allow_duplicate": allow_duplicate,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def cursor_for(block: dict[str, object], document: dict[str, object], offset: int = 0) -> dict:
    return {
        "block_id": block["id"],
        "block_ordinal": block["ordinal"],
        "character_offset": offset,
        "content_revision": document["content_revision"],
    }


def test_health_and_capabilities_report_truthful_reader_status(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(tmp_path)

    health = client.get("/v1/health")
    unauthorized = client.get("/v1/reader/capabilities")
    capabilities = client.get("/v1/reader/capabilities", headers=headers)

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["reader"] == {
        "enabled": True,
        "database_ready": True,
        "schema_version": 1,
        "startup_error": None,
    }
    assert unauthorized.status_code == 401
    assert capabilities.status_code == 200
    payload = capabilities.json()
    assert payload["contract_version"] == 1
    assert payload["database"] == {
        "ready": True,
        "schema_version": 1,
        "search_available": False,
    }
    assert payload["imports"]["formats"] == []
    assert payload["rules"]["types"] == []
    assert payload["playback"]["stream_protocol_version"] == 0
    assert payload["exports"]["formats"] == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/reader/documents"),
        ("POST", "/v1/reader/documents"),
        ("GET", "/v1/reader/queue"),
        ("POST", "/v1/reader/queue/reorder"),
    ],
)
def test_reader_reads_and_writes_require_authentication(
    tmp_path: Path,
    method: str,
    path: str,
) -> None:
    client, _, _ = build_reader_bundle(tmp_path)

    response = client.request(method, path, json={})

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "unauthorized"


def test_reader_routes_enforce_origin_policy(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(
        tmp_path,
        security_config={"allowed_origins": ["http://localhost:3000"]},
    )
    headers = {**headers, "Origin": "https://evil.example"}

    response = client.get("/v1/reader/documents", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["type"] == "forbidden_origin"


def test_document_crud_search_keyset_and_block_paging(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(tmp_path)
    first = create_document(client, headers, title="Alpha article")
    second = create_document(client, headers, title="Beta article", text="Unique beta")
    create_document(client, headers, title="Gamma notes", text="Unique gamma")

    duplicate = client.post(
        "/v1/reader/documents",
        headers=headers,
        json={"title": "Copy", "source_type": "plain_text", "text": "Unique beta"},
    )
    allowed_duplicate = client.post(
        "/v1/reader/documents",
        headers=headers,
        json={
            "title": "Copy",
            "source_type": "plain_text",
            "text": "Unique beta",
            "allow_duplicate": True,
        },
    )
    page_one = client.get("/v1/reader/documents?limit=2", headers=headers)
    page_two = client.get(
        "/v1/reader/documents",
        headers=headers,
        params={"limit": 2, "cursor": page_one.json()["next_cursor"]},
    )
    search = client.get("/v1/reader/documents?query=Beta", headers=headers)
    blocks_one = client.get(
        f"/v1/reader/documents/{first['id']}/blocks?limit=2",
        headers=headers,
    )
    blocks_two = client.get(
        f"/v1/reader/documents/{first['id']}/blocks",
        headers=headers,
        params={"limit": 2, "after_ordinal": blocks_one.json()["next_after_ordinal"]},
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["type"] == "reader_duplicate_document"
    assert allowed_duplicate.status_code == 201
    assert len(page_one.json()["documents"]) == 2
    assert len(page_two.json()["documents"]) == 2
    assert not {
        item["id"] for item in page_one.json()["documents"]
    } & {item["id"] for item in page_two.json()["documents"]}
    assert [item["id"] for item in search.json()["documents"]] == [second["id"]]
    assert [item["ordinal"] for item in blocks_one.json()["blocks"]] == [0, 1]
    assert blocks_one.json()["next_after_ordinal"] == 1
    assert [item["ordinal"] for item in blocks_two.json()["blocks"]] == [2]
    assert blocks_two.json()["next_after_ordinal"] is None

    updated = client.patch(
        f"/v1/reader/documents/{first['id']}",
        headers=headers,
        json={"expected_row_version": 1, "title": "Renamed", "state": "active"},
    )
    stale = client.patch(
        f"/v1/reader/documents/{first['id']}",
        headers=headers,
        json={"expected_row_version": 1, "title": "Lost update"},
    )
    deleted = client.delete(
        f"/v1/reader/documents/{first['id']}",
        headers=headers,
        params={"expected_row_version": updated.json()["row_version"]},
    )
    restored = client.post(
        f"/v1/reader/documents/{first['id']}/restore",
        headers=headers,
        json={"expected_row_version": deleted.json()["row_version"]},
    )

    assert updated.status_code == 200
    assert updated.json()["state"] == "active"
    assert stale.status_code == 409
    assert stale.json()["error"]["type"] == "reader_revision_conflict"
    assert stale.json()["error"]["details"] == {
        "entity_id": first["id"],
        "expected_row_version": 1,
        "actual_row_version": 2,
    }
    assert deleted.json()["deleted_at"] is not None
    assert restored.json()["deleted_at"] is None


def test_content_edit_append_undo_redo_and_typed_failures(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(tmp_path)
    document = create_document(client, headers, text="Alpha beta gamma.")
    block = client.get(
        f"/v1/reader/documents/{document['id']}/blocks",
        headers=headers,
    ).json()["blocks"][0]

    edited = client.patch(
        f"/v1/reader/documents/{document['id']}/content",
        headers=headers,
        json={
            "expected_row_version": document["row_version"],
            "block_id": block["id"],
            "start_offset": 6,
            "end_offset": 10,
            "replacement_text": "wonderful",
        },
    )
    stale = client.post(
        f"/v1/reader/documents/{document['id']}/append",
        headers=headers,
        json={"expected_row_version": 1, "text": "Stale append"},
    )
    appended = client.post(
        f"/v1/reader/documents/{document['id']}/append",
        headers=headers,
        json={
            "expected_row_version": edited.json()["document"]["row_version"],
            "text": "Copied forum selection.",
        },
    )
    undone = client.post(
        f"/v1/reader/documents/{document['id']}/undo",
        headers=headers,
        json={"expected_row_version": appended.json()["document"]["row_version"]},
    )
    redone = client.post(
        f"/v1/reader/documents/{document['id']}/redo",
        headers=headers,
        json={"expected_row_version": undone.json()["document"]["row_version"]},
    )
    missing_block = client.patch(
        f"/v1/reader/documents/{document['id']}/content",
        headers=headers,
        json={
            "expected_row_version": redone.json()["document"]["row_version"],
            "block_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "start_offset": 0,
            "end_offset": 0,
            "replacement_text": "x",
        },
    )

    assert edited.status_code == 200
    assert edited.json()["document"]["content_revision"] == 2
    assert edited.json()["edit"]["operation_type"] == "replace"
    assert "original_text" not in edited.json()["edit"]
    assert "replacement_text" not in edited.json()["edit"]
    assert stale.status_code == 409
    assert stale.json()["error"]["type"] == "reader_revision_conflict"
    assert appended.json()["edit"]["operation_type"] == "append"
    assert undone.json()["document"]["total_blocks"] == 1
    assert redone.json()["document"]["total_blocks"] == 2
    assert missing_block.status_code == 404
    assert missing_block.json()["error"]["type"] == "reader_block_not_found"


def test_positions_bookmarks_and_queue_endpoints_are_durable(tmp_path: Path) -> None:
    client, headers, app = build_reader_bundle(tmp_path)
    first = create_document(client, headers, text="First unique text")
    second = create_document(client, headers, title="Second", text="Second unique text")
    block = client.get(
        f"/v1/reader/documents/{first['id']}/blocks",
        headers=headers,
    ).json()["blocks"][0]
    cursor = cursor_for(block, first, offset=5)

    empty_position = client.get(
        f"/v1/reader/documents/{first['id']}/position",
        headers=headers,
    )
    saved_position = client.put(
        f"/v1/reader/documents/{first['id']}/position",
        headers=headers,
        json={"cursor": cursor, "expected_row_version": 0},
    )
    bookmark = client.post(
        f"/v1/reader/documents/{first['id']}/bookmarks",
        headers=headers,
        json={"cursor": cursor, "label": "Useful", "note": "Return here"},
    )
    updated_bookmark = client.patch(
        f"/v1/reader/bookmarks/{bookmark.json()['id']}",
        headers=headers,
        json={"expected_row_version": 1, "label": "Renamed"},
    )
    bookmarks = client.get(
        f"/v1/reader/documents/{first['id']}/bookmarks",
        headers=headers,
    )
    first_queue = client.post(
        "/v1/reader/queue/items",
        headers=headers,
        json={"document_id": first["id"]},
    )
    second_queue = client.post(
        "/v1/reader/queue/items",
        headers=headers,
        json={"document_id": second["id"]},
    )
    playing = client.patch(
        f"/v1/reader/queue/items/{first_queue.json()['id']}",
        headers=headers,
        json={"expected_row_version": 1, "status": "playing"},
    )
    reordered = client.post(
        "/v1/reader/queue/reorder",
        headers=headers,
        json={"item_ids": [second_queue.json()["id"], first_queue.json()["id"]]},
    )

    assert empty_position.json() == {"position": None}
    assert saved_position.status_code == 200
    assert saved_position.json()["cursor"]["character_offset"] == 5
    assert bookmark.status_code == 201
    assert updated_bookmark.json()["label"] == "Renamed"
    assert [item["id"] for item in bookmarks.json()["bookmarks"]] == [
        bookmark.json()["id"]
    ]
    assert playing.json()["status"] == "playing"
    assert [item["id"] for item in reordered.json()["items"]] == [
        second_queue.json()["id"],
        first_queue.json()["id"],
    ]

    reopened = create_app(config=app.state.container.config, repo_root=tmp_path)
    reopened_client = TestClient(reopened)
    reopened_headers = {"Authorization": f"Bearer {reopened.state.container.auth.token}"}
    assert (
        reopened_client.get(
            f"/v1/reader/documents/{first['id']}/position",
            headers=reopened_headers,
        ).json()["position"]["cursor"]["character_offset"]
        == 5
    )
    reopened_queue = reopened_client.get("/v1/reader/queue", headers=reopened_headers)
    assert len(reopened_queue.json()["items"]) == 2

    deleted_bookmark = client.delete(
        f"/v1/reader/bookmarks/{bookmark.json()['id']}",
        headers=headers,
        params={"expected_row_version": updated_bookmark.json()["row_version"]},
    )
    removed_queue = client.delete(
        f"/v1/reader/queue/items/{first_queue.json()['id']}",
        headers=headers,
        params={"expected_row_version": reordered.json()["items"][1]["row_version"]},
    )
    assert deleted_bookmark.status_code == 204
    assert removed_queue.status_code == 204


def test_disabled_and_degraded_reader_do_not_degrade_tts_health(tmp_path: Path) -> None:
    disabled_client, disabled_headers, _ = build_reader_bundle(
        tmp_path / "disabled",
        reader_config={"enabled": False},
    )
    blocked_home = tmp_path / "blocked-home"
    blocked_home.parent.mkdir(parents=True, exist_ok=True)
    blocked_home.write_text("not a directory", encoding="utf-8")
    degraded_client, degraded_headers, _ = build_reader_bundle(
        tmp_path / "degraded",
        reader_config={"home_path": str(blocked_home)},
    )

    disabled_health = disabled_client.get("/v1/health")
    disabled_route = disabled_client.get("/v1/reader/documents", headers=disabled_headers)
    degraded_health = degraded_client.get("/v1/health")
    degraded_route = degraded_client.get("/v1/reader/documents", headers=degraded_headers)

    assert disabled_health.json()["checks"]["backend_ready"] is True
    assert disabled_health.json()["reader"]["enabled"] is False
    assert disabled_route.status_code == 503
    assert disabled_route.json()["error"]["type"] == "reader_disabled"
    assert degraded_health.json()["status"] == "ok"
    assert degraded_health.json()["checks"]["backend_ready"] is True
    assert degraded_health.json()["reader"]["database_ready"] is False
    assert degraded_health.json()["reader"]["startup_error"] == (
        "Reader database initialization failed."
    )
    assert degraded_route.status_code == 503
    assert degraded_route.json()["error"]["type"] == "reader_database_unavailable"


def test_reader_database_errors_do_not_expose_sql_paths_or_tokens(tmp_path: Path) -> None:
    client, headers, app = build_reader_bundle(tmp_path)
    repository = app.state.container.reader.service.repository

    def fail_list(**_) -> None:
        raise ReaderDatabaseError(
            "SELECT secret FROM C:/private/reader.db with bearer super-secret-token"
        )

    repository.list_documents = fail_list
    response = client.get("/v1/reader/documents", headers=headers)

    assert response.status_code == 503
    body = response.text
    assert response.json()["error"]["type"] == "reader_database_unavailable"
    assert "SELECT" not in body
    assert "C:/private" not in body
    assert "super-secret-token" not in body


def test_reader_logs_identifiers_and_sizes_without_titles_or_text(tmp_path: Path) -> None:
    client, headers, app = build_reader_bundle(tmp_path)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = app.state.container.observability.logger
    logger.addHandler(handler)
    try:
        document = create_document(
            client,
            headers,
            title="PRIVATE TITLE",
            text="PRIVATE DOCUMENT TEXT",
        )
    finally:
        logger.removeHandler(handler)

    logs = stream.getvalue()
    assert document["id"] in logs
    assert '"character_count": 21' in logs
    assert "PRIVATE TITLE" not in logs
    assert "PRIVATE DOCUMENT TEXT" not in logs
