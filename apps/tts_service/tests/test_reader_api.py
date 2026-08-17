from __future__ import annotations

import io
import json
import logging
import threading
import time
import wave
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reader_core import ReaderDatabaseError
from tts_service.audio_encoders import FfmpegMp3Encoder
from tts_service.config import AppConfig
from tts_service.main import create_app


def build_reader_bundle(
    tmp_path: Path,
    *,
    reader_config: dict[str, object] | None = None,
    security_config: dict[str, object] | None = None,
) -> tuple[TestClient, dict[str, str], object]:
    reader = {
        "home_path": str(tmp_path / "reader"),
        "exports": {"formats": ["wav"]},
    }
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


def wait_for_export(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"/v1/reader/exports/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    raise AssertionError("Reader export did not reach a terminal state")


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
        "schema_version": 6,
        "startup_error": None,
    }
    assert unauthorized.status_code == 401
    assert capabilities.status_code == 200
    payload = capabilities.json()
    assert payload["contract_version"] == 1
    assert payload["database"] == {
        "ready": True,
        "schema_version": 6,
        "search_available": True,
    }
    assert payload["imports"] == {
        "formats": ["txt", "md", "html", "docx", "epub"],
        "max_file_bytes": 52_428_800,
        "ocr_available": False,
    }
    assert payload["rules"] == {
        "types": [
            "literal_replace",
            "regex_replace",
            "skip",
            "spell",
            "pause",
            "phoneme",
        ],
        "regex_timeout_supported": True,
    }
    assert payload["playback"]["stream_protocol_version"] == 1
    assert payload["exports"]["formats"] == ["wav"]
    assert payload["browser_capture"] == {
        "available": True,
        "max_characters": 10_000_000,
        "desktop_handoff": True,
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/reader/documents"),
        ("POST", "/v1/reader/documents"),
        ("GET", "/v1/reader/queue"),
        ("POST", "/v1/reader/queue/reorder"),
        ("POST", "/v1/reader/imports"),
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


def test_import_preview_commit_duplicate_cancel_and_editable_copy(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(tmp_path)
    html = b"""
    <html><head><title>Imported article</title><script>PRIVATE SCRIPT</script></head>
    <body><h1>Chapter</h1><p>Readable paragraph.</p><p hidden>PRIVATE HIDDEN</p></body></html>
    """

    preview = client.post(
        "/v1/reader/imports/preview",
        headers=headers,
        files={"file": ("article.html", html, "text/html")},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["title"] == "Imported article"
    assert preview_body["source_type"] == "html"
    assert preview_body["total_blocks"] == 2
    assert {warning["code"] for warning in preview_body["warnings"]} == {
        "html_active_content_ignored",
        "html_hidden_content_ignored",
    }
    assert "PRIVATE" not in preview.text

    committed = client.post(
        f"/v1/reader/imports/{preview_body['preview_id']}/commit",
        headers=headers,
        json={"allow_duplicate": False},
    )
    assert committed.status_code == 201, committed.text
    document = committed.json()
    assert document["source_type"] == "html"
    assert document["metadata"]["import"]["network_requests"] == 0
    assert len(document["metadata"]["import"]["warnings"]) == 2

    duplicate_preview = client.post(
        "/v1/reader/imports/preview",
        headers=headers,
        files={"file": ("article.html", html, "text/html")},
    ).json()
    assert duplicate_preview["duplicate_document_id"] == document["id"]
    duplicate_conflict = client.post(
        f"/v1/reader/imports/{duplicate_preview['preview_id']}/commit",
        headers=headers,
        json={"allow_duplicate": False},
    )
    assert duplicate_conflict.status_code == 409
    assert duplicate_conflict.json()["error"]["type"] == "reader_duplicate_document"
    duplicate_allowed = client.post(
        f"/v1/reader/imports/{duplicate_preview['preview_id']}/commit",
        headers=headers,
        json={"allow_duplicate": True},
    )
    assert duplicate_allowed.status_code == 201

    cancelled_preview = client.post(
        "/v1/reader/imports/preview",
        headers=headers,
        files={"file": ("cancel.txt", b"Cancel me", "text/plain")},
    ).json()
    cancelled = client.delete(
        f"/v1/reader/imports/{cancelled_preview['preview_id']}",
        headers=headers,
    )
    missing = client.post(
        f"/v1/reader/imports/{cancelled_preview['preview_id']}/commit",
        headers=headers,
        json={"allow_duplicate": False},
    )
    assert cancelled.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "reader_import_invalid"

    editable = client.post(
        f"/v1/reader/documents/{document['id']}/duplicate-as-editable",
        headers=headers,
    )
    assert editable.status_code == 201
    assert editable.json()["source_type"] == "plain_text"
    editable_blocks = client.get(
        f"/v1/reader/documents/{editable.json()['id']}/blocks",
        headers=headers,
    ).json()["blocks"]
    assert [block["text"] for block in editable_blocks] == [
        "Chapter",
        "Readable paragraph.",
    ]


def test_direct_import_can_copy_source_into_managed_library(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(tmp_path)

    response = client.post(
        "/v1/reader/imports",
        headers=headers,
        files={"file": ("notes.txt", b"Heading\n\nParagraph.", "text/plain")},
        data={"copy_source_file": "true"},
    )

    assert response.status_code == 201, response.text
    document = response.json()
    assert document["source_uri"].startswith("managed/")
    managed = tmp_path / "reader" / "library" / Path(document["source_uri"]).name
    assert managed.read_bytes() == b"Heading\n\nParagraph."


def test_import_rejects_unsafe_archive_and_file_quota(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(
        tmp_path,
        reader_config={"imports": {"max_file_bytes": 2_048}},
    )
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
        )
        archive.writestr("../outside", "unsafe")

    unsafe = client.post(
        "/v1/reader/imports",
        headers=headers,
        files={"file": ("unsafe.docx", archive_bytes.getvalue(), "application/octet-stream")},
    )
    too_large = client.post(
        "/v1/reader/imports",
        headers=headers,
        files={"file": ("large.txt", b"x" * 2_049, "text/plain")},
    )

    assert unsafe.status_code == 400
    assert unsafe.json()["error"]["type"] == "reader_archive_unsafe"
    assert too_large.status_code == 413
    assert too_large.json()["error"]["type"] == "reader_import_too_large"


def test_rule_crud_preview_interchange_and_idempotent_import(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(tmp_path)
    created_set = client.post(
        "/v1/reader/rule-sets",
        headers=headers,
        json={"name": "Danish IT", "scope": "language"},
    )
    assert created_set.status_code == 201, created_set.text
    rule_set = created_set.json()
    created_rule = client.post(
        f"/v1/reader/rule-sets/{rule_set['id']}/rules",
        headers=headers,
        json={
            "name": "Expand API",
            "stage": "pronunciation",
            "rule_type": "literal_replace",
            "pattern": "API",
            "replacement": "A P I",
            "language_filter": "da",
            "priority": 10,
        },
    )
    assert created_rule.status_code == 201, created_rule.text
    rule = created_rule.json()

    preview = client.post(
        "/v1/reader/rules/preview",
        headers=headers,
        json={
            "text": "L\u00e6s API \U0001f600.",
            "rule_set_ids": [rule_set["id"]],
            "language": "da",
        },
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["spoken_text"] == "L\u00e6s A P I \U0001f600."
    assert body["trace"][0]["rule_id"] == rule["id"]
    assert body["trace"][0]["start_offset"] == 4
    assert body["trace"][0]["end_offset"] == 7
    assert len(body["source_spans"]) == len(body["spoken_text"])
    assert body["rules_version"] > 1

    invalid = client.patch(
        f"/v1/reader/rules/{rule['id']}",
        headers=headers,
        json={
            "expected_row_version": rule["row_version"],
            "rule_type": "regex_replace",
            "pattern": "(",
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["type"] == "reader_rule_invalid"

    exported = client.get(
        f"/v1/reader/rule-sets/{rule_set['id']}/export", headers=headers
    )
    assert exported.status_code == 200
    target = client.post(
        "/v1/reader/rule-sets",
        headers=headers,
        json={"name": "Imported", "scope": "global"},
    ).json()
    dry_run = client.post(
        "/v1/reader/rule-imports",
        headers=headers,
        json={
            "target_rule_set_id": target["id"],
            "content": exported.text,
            "commit": False,
        },
    )
    committed = client.post(
        "/v1/reader/rule-imports",
        headers=headers,
        json={
            "target_rule_set_id": target["id"],
            "content": exported.text,
            "commit": True,
        },
    )
    repeated = client.post(
        "/v1/reader/rule-imports",
        headers=headers,
        json={
            "target_rule_set_id": target["id"],
            "content": exported.text,
            "commit": True,
        },
    )
    assert dry_run.json()["imported"] == 0
    assert committed.json()["imported"] == 1
    assert repeated.json()["idempotent"] is True
    imported_rules = client.get(
        f"/v1/reader/rule-sets/{target['id']}/rules", headers=headers
    ).json()["rules"]
    assert len(imported_rules) == 1


def test_rule_import_preserves_unknown_provider_rule_disabled(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(tmp_path)
    target = client.post(
        "/v1/reader/rule-sets",
        headers=headers,
        json={"name": "Provider", "scope": "global"},
    ).json()
    content = json.dumps(
        {
            "format": "tts-platform-reader-rule-set",
            "version": 1,
            "rule_set": {"name": "Provider", "scope": "global"},
            "rules": [
                {
                    "name": "Vendor rule",
                    "stage": "pronunciation",
                    "rule_type": "vendor_phoneme",
                    "pattern": "name",
                    "replacement": "ne\u026am",
                    "vendor_hint": "preserve",
                }
            ],
        }
    )

    response = client.post(
        "/v1/reader/rule-imports",
        headers=headers,
        json={
            "target_rule_set_id": target["id"],
            "content": content,
            "commit": True,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["unsupported"] == 1
    assert response.json()["disabled"] == 1
    imported = client.get(
        f"/v1/reader/rule-sets/{target['id']}/rules", headers=headers
    ).json()["rules"][0]
    assert imported["enabled"] is False
    assert imported["raw_import_metadata"]["unsupported_rule_type"] == "vendor_phoneme"


def test_rule_preview_rejects_mapping_response_amplification(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(tmp_path)

    response = client.post(
        "/v1/reader/rules/preview",
        headers=headers,
        json={"text": "x" * 4_097, "rule_set_ids": []},
    )

    assert response.status_code == 400
    assert "x" * 100 not in response.text


def test_reader_routes_enforce_origin_policy(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(
        tmp_path,
        security_config={"allowed_origins": ["http://localhost:3000"]},
    )
    headers = {**headers, "Origin": "https://evil.example"}

    response = client.get("/v1/reader/documents", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["type"] == "forbidden_origin"


def test_browser_capture_is_structured_protected_and_handed_to_desktop(
    tmp_path: Path,
) -> None:
    extension_origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    client, headers, _ = build_reader_bundle(
        tmp_path,
        security_config={"allowed_origins": [extension_origin]},
    )
    payload = {
        "title": "Structured browser article",
        "source_uri": "https://example.test/articles/reader?part=1",
        "source_name": "example.test",
        "language_hint": "en",
        "blocks": [
            {"kind": "heading", "text": "Chapter one", "heading_level": 2},
            {"kind": "paragraph", "text": "Readable browser body."},
            {"kind": "list_item", "text": "A captured list item."},
            {"kind": "quote", "text": "A captured quotation."},
        ],
        "extraction_source": "readable-blocks",
        "truncated": False,
        "add_to_queue": True,
        "open_in_desktop": True,
    }

    unauthenticated = client.post(
        "/v1/reader/browser-captures",
        headers={"Origin": extension_origin},
        json=payload,
    )
    wrong_origin = client.post(
        "/v1/reader/browser-captures",
        headers={**headers, "Origin": "https://evil.example"},
        json=payload,
    )
    created = client.post(
        "/v1/reader/browser-captures",
        headers={**headers, "Origin": extension_origin},
        json=payload,
    )

    assert unauthenticated.status_code == 401
    assert wrong_origin.status_code == 403
    assert created.status_code == 201, created.text
    body = created.json()
    document = body["document"]
    assert document["source_type"] == "browser"
    assert document["source_uri"] == payload["source_uri"]
    assert document["metadata"]["browser_capture"] == {
        "extraction_source": "readable-blocks",
        "truncated": False,
    }
    assert body["queue_item"]["document_id"] == document["id"]
    assert body["desktop_open_request"]["document_id"] == document["id"]
    assert body["reused_existing"] is False

    reused = client.post(
        "/v1/reader/browser-captures",
        headers={**headers, "Origin": extension_origin},
        json=payload,
    )
    assert reused.status_code == 201
    assert reused.json()["document"]["id"] == document["id"]
    assert reused.json()["queue_item"]["id"] == body["queue_item"]["id"]
    assert reused.json()["desktop_open_request"]["id"] == body["desktop_open_request"]["id"]
    assert reused.json()["reused_existing"] is True

    duplicate_rejected = client.post(
        "/v1/reader/browser-captures",
        headers={**headers, "Origin": extension_origin},
        json={**payload, "reuse_existing": False},
    )
    assert duplicate_rejected.status_code == 409

    different_source_rejected = client.post(
        "/v1/reader/browser-captures",
        headers={**headers, "Origin": extension_origin},
        json={**payload, "source_uri": "https://other.example/same-text"},
    )
    assert different_source_rejected.status_code == 409

    blocks = client.get(
        f"/v1/reader/documents/{document['id']}/blocks",
        headers=headers,
    ).json()["blocks"]
    assert [block["kind"] for block in blocks] == [
        "heading",
        "paragraph",
        "list_item",
        "quote",
    ]
    assert [block["text"] for block in blocks] == [
        item["text"] for item in payload["blocks"]
    ]

    next_request = client.get(
        "/v1/reader/desktop/open-requests/next",
        headers=headers,
    )
    assert next_request.status_code == 200
    assert next_request.json()["document_id"] == document["id"]
    acknowledged = client.delete(
        f"/v1/reader/desktop/open-requests/{next_request.json()['id']}",
        headers=headers,
    )
    assert acknowledged.status_code == 204
    assert client.get(
        "/v1/reader/desktop/open-requests/next",
        headers=headers,
    ).json() is None

    unsafe_source = client.post(
        "/v1/reader/browser-captures",
        headers={**headers, "Origin": extension_origin},
        json={**payload, "source_uri": "file:///C:/private.txt"},
    )
    assert unsafe_source.status_code == 400


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
    assert {item["id"] for item in search.json()["documents"]} == {
        second["id"],
        allowed_duplicate.json()["id"],
    }
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
            "text": "First copied paragraph.\n\nSecond copied paragraph.",
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
    assert appended.json()["document"]["total_blocks"] == 3
    assert undone.json()["document"]["total_blocks"] == 1
    assert redone.json()["document"]["total_blocks"] == 3
    assert missing_block.status_code == 404
    assert missing_block.json()["error"]["type"] == "reader_block_not_found"


def test_content_edit_uses_utf16_offsets_at_the_http_boundary(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(tmp_path)
    document = create_document(client, headers, text="A😀B")
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
            "start_offset": 1,
            "end_offset": 3,
            "replacement_text": "ø",
        },
    )
    invalid = client.patch(
        f"/v1/reader/documents/{document['id']}/content",
        headers=headers,
        json={
            "expected_row_version": edited.json()["document"]["row_version"],
            "block_id": block["id"],
            "start_offset": 99,
            "end_offset": 99,
            "replacement_text": "x",
        },
    )
    current_block = client.get(
        f"/v1/reader/documents/{document['id']}/blocks",
        headers=headers,
    ).json()["blocks"][0]

    assert edited.status_code == 200
    assert edited.json()["edit"]["start_offset"] == 1
    assert edited.json()["edit"]["end_offset"] == 3
    assert current_block["text"] == "AøB"
    assert invalid.status_code == 400
    assert invalid.json()["error"]["type"] == "reader_invalid_offset"


def test_content_mutations_are_rejected_while_reader_lease_is_active(
    tmp_path: Path,
) -> None:
    client, headers, app = build_reader_bundle(tmp_path)
    document = create_document(client, headers, text="Lease protected.")
    service = app.state.container.reader.service
    assert service is not None

    with service.content_lease(document["id"], "active-stream"):
        response = client.post(
            f"/v1/reader/documents/{document['id']}/append",
            headers=headers,
            json={
                "expected_row_version": document["row_version"],
                "text": "Must wait.",
            },
        )

    allowed = client.post(
        f"/v1/reader/documents/{document['id']}/append",
        headers=headers,
        json={
            "expected_row_version": document["row_version"],
            "text": "Allowed now.",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["type"] == "reader_document_locked"
    assert allowed.status_code == 200


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


def test_position_and_bookmark_offsets_use_utf16_code_units(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(tmp_path)
    document = create_document(client, headers, text="A\U0001f600BC")
    block = client.get(
        f"/v1/reader/documents/{document['id']}/blocks",
        headers=headers,
    ).json()["blocks"][0]
    cursor = cursor_for(block, document, offset=3)

    position = client.put(
        f"/v1/reader/documents/{document['id']}/position",
        headers=headers,
        json={"cursor": cursor, "expected_row_version": 0},
    )
    bookmark = client.post(
        f"/v1/reader/documents/{document['id']}/bookmarks",
        headers=headers,
        json={"cursor": cursor, "label": "After emoji"},
    )
    invalid = client.put(
        f"/v1/reader/documents/{document['id']}/position",
        headers=headers,
        json={
            "cursor": cursor_for(block, document, offset=2),
            "expected_row_version": position.json()["row_version"],
        },
    )

    assert position.status_code == 200
    assert position.json()["cursor"]["character_offset"] == 3
    assert bookmark.status_code == 201
    assert bookmark.json()["cursor"]["character_offset"] == 3
    assert invalid.status_code == 400
    assert invalid.json()["error"]["type"] == "reader_invalid_cursor"


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


def test_queue_auto_advance_export_and_diagnostics_workflow(tmp_path: Path) -> None:
    client, headers, app = build_reader_bundle(tmp_path)
    first = create_document(client, headers, title="First export", text="Hello world.")
    second = create_document(client, headers, title="Second export", text="Goodbye world.")
    first_queue = client.post(
        "/v1/reader/queue/items",
        headers=headers,
        json={"document_id": first["id"]},
    ).json()
    second_queue = client.post(
        "/v1/reader/queue/items",
        headers=headers,
        json={"document_id": second["id"]},
    ).json()

    activated = client.post(
        f"/v1/reader/queue/items/{first_queue['id']}/activate",
        headers=headers,
    )
    advanced = client.post(
        f"/v1/reader/queue/advance/{first['id']}",
        headers=headers,
    )
    assert activated.json()["status"] == "playing"
    assert advanced.json()["id"] == second_queue["id"]
    queue = client.get("/v1/reader/queue", headers=headers).json()["items"]
    assert sum(item["status"] == "playing" for item in queue) == 1

    created = client.post(
        "/v1/reader/exports",
        headers=headers,
        json={
            "queue_item_ids": [first_queue["id"], second_queue["id"]],
            "output_basename": "../../ignored-for-batch",
        },
    )
    assert created.status_code == 202, created.text
    job = wait_for_export(client, headers, created.json()["id"])
    assert job["status"] == "completed", job
    assert job["progress_phase"] == "completed"
    assert job["progress_percent"] == 100
    assert len(job["output_files"]) == 2
    export_directory = tmp_path / "reader" / "data" / "exports"
    assert all((export_directory / name).is_file() for name in job["output_files"])
    assert not (tmp_path / "ignored-for-batch.wav").exists()
    with wave.open(str(export_directory / job["output_files"][0]), "rb") as exported:
        assert exported.getnchannels() == 1
        assert exported.getsampwidth() == 2
        assert exported.getnframes() > 0

    safe_name_job = client.post(
        "/v1/reader/exports",
        headers=headers,
        json={"document_ids": [first["id"]], "output_basename": "../../CON"},
    )
    assert safe_name_job.status_code == 202
    safe_name_result = wait_for_export(client, headers, safe_name_job.json()["id"])
    assert safe_name_result["status"] == "completed"
    assert safe_name_result["output_files"] == ["_CON.wav"]
    assert (export_directory / "_CON.wav").is_file()
    assert not (tmp_path / "CON.wav").exists()

    result = client.get(
        f"/v1/reader/exports/{job['id']}/result?index=0",
        headers=headers,
    )
    diagnostics = client.get("/v1/reader/diagnostics", headers=headers)
    assert result.status_code == 200
    assert result.headers["content-type"] == "audio/wav"
    assert diagnostics.status_code == 200
    assert diagnostics.json()["schema_version"] == 6
    assert diagnostics.json()["export_status_counts"]["completed"] == 2
    assert diagnostics.json()["document_counts_by_state"] == {
        "inbox": 2,
        "active": 0,
        "finished": 0,
        "archived": 0,
    }
    assert app.state.container.reader.service.repository.search_available is True

    deleted = client.delete(
        f"/v1/reader/exports/{job['id']}/history",
        headers=headers,
    )
    assert deleted.status_code == 204
    assert all(not (export_directory / name).exists() for name in job["output_files"])
    assert (
        client.get(f"/v1/reader/exports/{job['id']}", headers=headers).status_code
        == 404
    )


def test_cancelled_export_removes_temporary_and_final_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, headers, app = build_reader_bundle(tmp_path)
    document = create_document(client, headers, title="Cancelled", text="Please stop now.")
    backend = app.state.container.backend
    original_synthesize = backend.synthesize
    entered = threading.Event()
    release = threading.Event()

    def slow_synthesize(_, request):
        entered.set()
        release.wait(timeout=3)
        return original_synthesize(request)

    monkeypatch.setattr(type(backend), "synthesize", slow_synthesize)
    created = client.post(
        "/v1/reader/exports",
        headers=headers,
        json={"document_ids": [document["id"]], "output_basename": "cancelled"},
    )
    assert created.status_code == 202, created.text
    assert entered.wait(timeout=2)
    active_delete = client.delete(
        f"/v1/reader/exports/{created.json()['id']}/history",
        headers=headers,
    )
    assert active_delete.status_code == 400
    cancelled = client.delete(
        f"/v1/reader/exports/{created.json()['id']}",
        headers=headers,
    )
    assert cancelled.status_code == 200
    release.set()
    job = wait_for_export(client, headers, created.json()["id"])
    assert job["status"] == "cancelled"
    export_directory = tmp_path / "reader" / "data" / "exports"
    assert not (export_directory / "cancelled.wav").exists()
    assert list(export_directory.glob("*.part")) == []
    deleted = client.delete(
        f"/v1/reader/exports/{created.json()['id']}/history",
        headers=headers,
    )
    assert deleted.status_code == 204


def test_export_reports_synthesis_progress_before_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, headers, app = build_reader_bundle(tmp_path)
    document = create_document(
        client,
        headers,
        title="Progress",
        text="First sentence.\n\nSecond sentence.\n\nThird sentence.",
    )
    backend = app.state.container.backend
    original_synthesize = backend.synthesize
    entered_second_fragment = threading.Event()
    release = threading.Event()
    synthesis_calls = 0

    def slow_second_synthesis(_, request):
        nonlocal synthesis_calls
        synthesis_calls += 1
        if synthesis_calls == 2:
            entered_second_fragment.set()
            release.wait(timeout=3)
        return original_synthesize(request)

    monkeypatch.setattr(type(backend), "synthesize", slow_second_synthesis)
    created = client.post(
        "/v1/reader/exports",
        headers=headers,
        json={"document_ids": [document["id"]], "output_basename": "progress"},
    )
    assert created.status_code == 202, created.text
    assert entered_second_fragment.wait(timeout=2)

    running = client.get(
        f"/v1/reader/exports/{created.json()['id']}",
        headers=headers,
    )
    assert running.status_code == 200
    assert running.json()["status"] == "running"
    assert running.json()["progress_phase"] == "synthesizing"
    assert 0 < running.json()["progress_percent"] < 96

    release.set()
    completed = wait_for_export(client, headers, created.json()["id"])
    assert completed["status"] == "completed"
    assert completed["progress_phase"] == "completed"
    assert completed["progress_percent"] == 100


def test_mp3_export_uses_ready_encoder_and_returns_mpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded_titles: list[str] = []

    class FakeMp3Encoder:
        def encode(
            self,
            source_wav: Path,
            target_mp3: Path,
            *,
            title: str,
            should_cancel,
        ) -> None:
            assert source_wav.read_bytes().startswith(b"RIFF")
            assert should_cancel() is False
            encoded_titles.append(title)
            target_mp3.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00fake-mp3")

    monkeypatch.setattr(
        FfmpegMp3Encoder,
        "discover",
        classmethod(lambda cls, configured_path=None, *, bitrate_kbps=96: FakeMp3Encoder()),
    )
    client, headers, _ = build_reader_bundle(
        tmp_path,
        reader_config={"exports": {"formats": ["wav", "mp3"]}},
    )
    capabilities = client.get("/v1/reader/capabilities", headers=headers)
    assert capabilities.json()["exports"]["formats"] == ["wav", "mp3"]
    document = create_document(
        client,
        headers,
        title="MP3 article title",
        text="This article becomes an audio file.",
    )

    created = client.post(
        "/v1/reader/exports",
        headers=headers,
        json={
            "document_ids": [document["id"]],
            "audio_format": "mp3",
            "output_basename": "spoken-article.mp3",
        },
    )
    assert created.status_code == 202, created.text
    job = wait_for_export(client, headers, created.json()["id"])

    assert job["status"] == "completed", job
    assert job["audio_format"] == "mp3"
    assert job["output_files"] == ["spoken-article.mp3"]
    assert encoded_titles == ["MP3 article title"]
    result = client.get(
        f"/v1/reader/exports/{job['id']}/result",
        headers=headers,
    )
    assert result.status_code == 200
    assert result.headers["content-type"] == "audio/mpeg"
    assert result.content.startswith(b"ID3")


def test_mp3_export_is_rejected_when_ffmpeg_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        FfmpegMp3Encoder,
        "discover",
        classmethod(lambda cls, configured_path=None, *, bitrate_kbps=96: None),
    )
    client, headers, _ = build_reader_bundle(
        tmp_path,
        reader_config={"exports": {"formats": ["wav", "mp3"]}},
    )
    document = create_document(client, headers)

    capabilities = client.get("/v1/reader/capabilities", headers=headers)
    created = client.post(
        "/v1/reader/exports",
        headers=headers,
        json={"document_ids": [document["id"]], "audio_format": "mp3"},
    )

    assert capabilities.json()["exports"]["formats"] == ["wav"]
    assert created.status_code == 503
    assert "MP3 export is not available" in created.json()["error"]["message"]
