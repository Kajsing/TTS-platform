from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from fastapi.responses import Response
from fastapi.testclient import TestClient
from reader_core import FolderDocumentVersion
from reader_core.chapter_index import ChapterAnchor, ChapterIndex
from reader_core.chapters import CHAPTER_KEY
from test_remote_access import _manager, _profile
from tts_service import reader_chapter_routes
from tts_service.config import AppConfig
from tts_service.main import create_app
from tts_service.reader_privacy import PRIVACY_SESSION_HEADER
from tts_service.remote_gateway import create_remote_gateway_app, is_remote_route_allowed
from tts_service.security import request_budget


@pytest.fixture
def bundle(tmp_path):
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"warmup_on_start": False},
                "backend": {"mode": "stub"},
                "reader": {"home_path": str(tmp_path / "reader"), "exports": {"formats": ["wav"]}},
                "limits": {"requests_per_minute": 1000, "playback_requests_per_minute": 1000},
            }
        ),
        repo_root=tmp_path,
    )
    headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/v1/reader/documents",
            headers=headers,
            json={
                "title": "Private chapter title",
                "source_type": "plain_text",
                "text": "A😀 B.\n\nSecond synthetic paragraph.",
            },
        )
        assert response.status_code == 201, response.text
        yield SimpleNamespace(
            app=app,
            client=client,
            headers=headers,
            document=response.json(),
            service=app.state.container.reader.service,
        )


def endpoint(bundle, revision=None):
    document = bundle.document
    revision = document["content_revision"] if revision is None else revision
    return f"/v1/reader/documents/{document['id']}/chapters?expected_content_revision={revision}"


def private_folder(bundle, *, move=False):
    folder = bundle.service.create_folder("Protected chapters")
    privacy = bundle.service.privacy.setup(
        folder.id, code="correct code", expected_row_version=folder.row_version
    )
    if move:
        current = bundle.service.repository.get_document(bundle.document["id"])
        bundle.service.move_documents(
            (FolderDocumentVersion(current.id, current.row_version),), folder_id=folder.id
        )
    return folder, privacy


def test_chapter_index_preserves_unicode_codepoint_offsets_without_source_reads(
    bundle, monkeypatch
):
    repository = bundle.service.repository
    block = repository.list_blocks(bundle.document["id"])[0]
    updated = repository.edit_chapter(
        bundle.document["id"],
        expected_row_version=bundle.document["row_version"],
        action="add",
        block_id=block.id,
        codepoint_offset=2,
        title="After A😀",
    )
    original_connection = repository._connection
    block_columns = set()

    @contextmanager
    def scalar_connection():
        with original_connection() as connection:

            def authorize(action, table, column, database, trigger):
                if action == sqlite3.SQLITE_READ and table == "reader_blocks":
                    block_columns.add(column)
                    if column not in {"id", "document_id", "ordinal", "character_count"}:
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            connection.set_authorizer(authorize)
            try:
                yield connection
            finally:
                connection.set_authorizer(None)

    monkeypatch.setattr(repository, "_connection", scalar_connection)
    response = bundle.client.get(endpoint(bundle, updated.content_revision), headers=bundle.headers)
    assert response.status_code == 200, response.text
    index = response.json()
    assert set(index) == {"document_id", "content_revision", "chapters"}
    assert index["content_revision"] == updated.content_revision
    assert index["chapters"][1] == {
        "id": updated.metadata[CHAPTER_KEY][1]["id"],
        "title": "After A😀",
        "block_id": block.id,
        "block_ordinal": 0,
        "codepoint_offset": 2,
    }
    assert "character_offset" not in response.text and "synthetic" not in response.text
    assert block_columns <= {"id", "document_id", "ordinal", "character_count"}
    assert repository.get_document(updated.id).metadata == updated.metadata


def test_chapter_read_auth_origin_positive_revision_and_background_budget(bundle):
    url = endpoint(bundle)
    assert bundle.client.get(url).status_code == 401
    assert bundle.client.get(url, headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert (
        bundle.client.get(
            url,
            headers={
                **bundle.headers,
                "Origin": "https://foreign.invalid",
            },
        ).status_code
        == 403
    )
    base = url.split("?", 1)[0]
    for query in [
        "",
        "?expected_content_revision=0",
        "?expected_content_revision=-1",
        "?expected_content_revision=true",
        "?expected_content_revision=bad",
    ]:
        assert bundle.client.get(base + query, headers=bundle.headers).status_code == 400
    stale = bundle.client.get(endpoint(bundle, 2), headers=bundle.headers)
    assert stale.status_code == 409 and stale.json()["error"]["type"] == "reader_revision_conflict"
    assert request_budget("GET", base) == "background"


def test_chapter_index_checks_privacy_before_reading_metadata(bundle, monkeypatch):
    folder, privacy = private_folder(bundle, move=True)
    original = reader_chapter_routes.read_chapter_index
    reads = []

    def observe(*args, **kwargs):
        reads.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(reader_chapter_routes, "read_chapter_index", observe)
    blocked = bundle.client.get(endpoint(bundle), headers=bundle.headers)
    assert blocked.status_code == 423 and not reads
    headers = {**bundle.headers, PRIVACY_SESSION_HEADER: privacy.session.token}
    assert bundle.client.get(endpoint(bundle), headers=headers).status_code == 200
    assert len(reads) == 1
    bundle.service.privacy.relock(folder.id, (privacy.session.token,))
    assert bundle.client.get(endpoint(bundle), headers=headers).status_code == 423
    assert len(reads) == 1


@pytest.mark.parametrize("phase", ["encoded", "final_worker"])
@pytest.mark.parametrize("change", ["revision", "deleted", "relock", "move"])
def test_final_chapter_fences_reject_revision_privacy_or_folder_changes(
    bundle, monkeypatch, phase, change
):
    headers = bundle.headers
    if change in {"relock", "move"}:
        folder, privacy = private_folder(bundle, move=change == "relock")
        if change == "relock":
            headers = {**headers, PRIVACY_SESSION_HEADER: privacy.session.token}

    def mutate():
        repository = bundle.service.repository
        current = repository.get_document(bundle.document["id"])
        if change == "revision":
            repository.append_text(
                current.id, "Later content.", expected_row_version=current.row_version
            )
        elif change == "deleted":
            repository.soft_delete_document(current.id, expected_row_version=current.row_version)
        elif change == "relock":
            bundle.service.privacy.relock(folder.id, (privacy.session.token,))
        else:
            bundle.service.move_documents(
                (FolderDocumentVersion(current.id, current.row_version),), folder_id=folder.id
            )

    if phase == "encoded":
        original_response = reader_chapter_routes._response

        def response_then_mutate(*args, **kwargs):
            response = original_response(*args, **kwargs)
            mutate()
            return response

        monkeypatch.setattr(reader_chapter_routes, "_response", response_then_mutate)
    else:
        original_worker = reader_chapter_routes.run_in_threadpool
        access_workers = 0

        async def worker_then_mutate(call, *args, **kwargs):
            nonlocal access_workers
            result = await original_worker(call, *args, **kwargs)
            if call == reader_chapter_routes._require_current_access:
                access_workers += 1
                if access_workers == 2:
                    mutate()
            return result

        monkeypatch.setattr(reader_chapter_routes, "run_in_threadpool", worker_then_mutate)
    response = bundle.client.get(endpoint(bundle), headers=headers)
    expected = 409 if change in {"revision", "deleted"} else 423
    assert response.status_code == expected, response.text
    assert response.json()["error"]["type"] == (
        "reader_revision_conflict" if expected == 409 else "reader_privacy_locked"
    )
    assert "Chapter 1" not in response.text


@pytest.mark.parametrize("metadata", [{CHAPTER_KEY: []}, {CHAPTER_KEY: None}, {CHAPTER_KEY: {}}])
def test_malformed_chapter_metadata_is_a_conflict_without_rewriting(bundle, metadata):
    repository = bundle.service.repository
    encoded = json.dumps(metadata)
    with repository._write() as connection:
        connection.execute(
            "UPDATE reader_documents SET metadata_json = ? WHERE id = ?",
            (encoded, bundle.document["id"]),
        )
    response = bundle.client.get(endpoint(bundle), headers=bundle.headers)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["type"] == "reader_chapter_index_conflict"
    with repository._connection() as connection:
        assert (
            connection.execute(
                "SELECT metadata_json FROM reader_documents WHERE id = ?", (bundle.document["id"],)
            ).fetchone()[0]
            == encoded
        )


@pytest.mark.parametrize("encoded", ["{bad json", "[]"])
@pytest.mark.parametrize("protected", [False, True])
def test_corrupt_document_json_remains_private_and_returns_a_typed_chapter_conflict(
    bundle, encoded, protected
):
    headers = bundle.headers
    if protected:
        _, privacy = private_folder(bundle, move=True)
        headers = {**headers, PRIVACY_SESSION_HEADER: privacy.session.token}
    repository = bundle.service.repository
    with repository._write() as connection:
        connection.execute(
            "UPDATE reader_documents SET metadata_json = ? WHERE id = ?",
            (encoded, bundle.document["id"]),
        )
    if protected:
        locked = bundle.client.get(endpoint(bundle), headers=bundle.headers)
        assert locked.status_code == 423, locked.text
    response = bundle.client.get(endpoint(bundle), headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["type"] == "reader_chapter_index_conflict"
    with repository._connection() as connection:
        assert (
            connection.execute(
                "SELECT metadata_json FROM reader_documents WHERE id = ?", (bundle.document["id"],)
            ).fetchone()[0]
            == encoded
        )


def test_empty_document_has_an_empty_index(bundle):
    with bundle.service.repository._write() as connection:
        connection.execute(
            "DELETE FROM reader_blocks WHERE document_id = ?", (bundle.document["id"],)
        )
    response = bundle.client.get(endpoint(bundle), headers=bundle.headers)
    assert response.status_code == 200, response.text
    assert response.json()["chapters"] == []


def test_response_bound_is_exact_and_never_silently_drops_chapters(bundle, monkeypatch):
    index = ChapterIndex(
        bundle.document["id"], 1, (ChapterAnchor("root", "Chapter 😀", "block", 0, 0),)
    )
    monkeypatch.setattr(reader_chapter_routes, "read_chapter_index", lambda *args: index)
    encoded_size = len(
        json.dumps(
            asdict(index), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    )
    monkeypatch.setattr(reader_chapter_routes, "MAX_CHAPTER_RESPONSE_BYTES", encoded_size)
    accepted = bundle.client.get(endpoint(bundle), headers=bundle.headers)
    assert accepted.status_code == 200 and len(accepted.content) == encoded_size
    monkeypatch.setattr(reader_chapter_routes, "MAX_CHAPTER_RESPONSE_BYTES", encoded_size - 1)
    rejected = bundle.client.get(endpoint(bundle), headers=bundle.headers)
    assert rejected.status_code == 413
    assert rejected.json()["error"]["type"] == "reader_chapter_index_too_large"


def test_chapter_gateway_allowlist_is_exact_and_device_credentials_are_required(
    bundle, tmp_path, monkeypatch
):
    base = f"/v1/reader/documents/{bundle.document['id']}/chapters"
    assert is_remote_route_allowed("GET", base) and is_remote_route_allowed("POST", base)
    assert not is_remote_route_allowed("PUT", base)
    assert not is_remote_route_allowed("GET", base + "/extra")
    assert not is_remote_route_allowed("GET", base.replace(bundle.document["id"], "not-a-uuid"))
    manager = _manager(tmp_path / "gateway")
    invitation = manager.store.create_invitation(_profile(tmp_path))
    device, credential = manager.store.consume_invitation(
        str(invitation["ticket_id"]), str(invitation["ticket_secret"]), "Chapter device"
    )
    calls = []

    async def proxy(_manager, request, path, body):
        assert not body
        calls.append(path)
        response = bundle.client.get(path + "?" + request.url.query, headers=bundle.headers)
        return Response(
            response.content, status_code=response.status_code, media_type="application/json"
        )

    monkeypatch.setattr("tts_service.remote_gateway._proxy_http", proxy)
    with TestClient(create_remote_gateway_app(manager)) as gateway:
        assert gateway.get(endpoint(bundle)).status_code == 401
        headers = {"Authorization": f"Bearer {credential}"}
        accepted = gateway.get(endpoint(bundle), headers=headers)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["chapters"][0]["id"] == "root" and len(calls) == 1
        assert (
            gateway.get(
                endpoint(bundle),
                headers={
                    **headers,
                    "Origin": "https://foreign.invalid",
                },
            ).status_code
            == 403
        )
        manager.store.revoke_device(device.id)
        assert gateway.get(endpoint(bundle), headers=headers).status_code == 401
        assert len(calls) == 1


def test_chapter_titles_and_query_parameters_are_not_logged(bundle, monkeypatch):
    repository = bundle.service.repository
    updated = repository.edit_chapter(
        bundle.document["id"],
        expected_row_version=1,
        action="rename",
        chapter_id="root",
        title="PRIVATE TITLE",
    )
    logs = []
    monkeypatch.setattr(bundle.app.state.container.observability.logger, "info", logs.append)
    response = bundle.client.get(
        endpoint(bundle, updated.content_revision) + "&private=QUERY_SECRET", headers=bundle.headers
    )
    assert response.status_code == 200, response.text
    combined = json.dumps(logs)
    for secret in ["PRIVATE TITLE", "QUERY_SECRET", "A😀 B.", bundle.headers["Authorization"]]:
        assert secret not in combined
