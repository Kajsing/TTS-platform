from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from test_reader_api import build_reader_bundle


def capture(client, headers, operation, **payload):
    return client.post(f"/v1/reader/captures/{operation}", headers=headers, json=payload)


def test_large_capture_and_dependent_appends_survive_lost_responses(tmp_path):
    client, headers, app = build_reader_bundle(tmp_path)
    operation = str(uuid4())
    payload = dict(action="create", title="Queued article", text="A long paragraph. " * 9000)
    first = capture(client, headers, operation, **payload)
    assert first.status_code == 200, first.text
    document_id = first.json()["document_id"]
    replay = capture(client, headers, operation, **payload)
    assert replay.json()["outcome"] == "already_delivered"
    service = app.state.container.reader.service
    for chapter in range(3):
        append_id = str(uuid4())
        append = dict(action="append", text=f"Chapter {chapter}.", target_operation_id=operation)
        response = capture(client, headers, append_id, **append)
        assert response.status_code == 200, response.text
        repeated = capture(client, headers, append_id, **append)
        assert repeated.json()["outcome"] == "already_delivered"
    document = service.repository.get_document(document_id)
    assert document.content_revision == 4
    assert document.total_characters == len(payload["text"].strip()) + sum(
        len(f"Chapter {i}.") for i in range(3)
    )


def test_same_operation_cannot_change_payload_and_concurrent_delivery_is_once(tmp_path):
    client, headers, app = build_reader_bundle(tmp_path)
    operation = str(uuid4())
    payload = dict(action="create", text="Exactly once.")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: capture(client, headers, operation, **payload), range(2)))
    assert all(result.status_code == 200 for result in results), [r.text for r in results]
    assert {r.json()["outcome"] for r in results} == {"delivered", "already_delivered"}
    changed = capture(client, headers, operation, action="create", text="Changed payload.")
    assert changed.status_code == 409
    repository = app.state.container.reader.service.repository
    with repository._connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reader_documents").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM reader_capture_receipts").fetchone()[0] == 1


def test_lease_denial_does_not_consume_receipt_and_deleted_target_stays_deleted(tmp_path):
    client, headers, app = build_reader_bundle(tmp_path)
    create_id, append_id = str(uuid4()), str(uuid4())
    created = capture(client, headers, create_id, action="create", text="First chapter.")
    document_id = created.json()["document_id"]
    service = app.state.container.reader.service
    payload = dict(action="append", text="Second chapter.", document_id=document_id)
    with service.content_lease(document_id, "capture-test"):
        blocked = capture(client, headers, append_id, **payload)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["type"] == "reader_document_locked"
    assert capture(client, headers, append_id, **payload).status_code == 200
    document = service.repository.get_document(document_id)
    service.repository.soft_delete_document(document_id, expected_row_version=document.row_version)
    assert capture(client, headers, str(uuid4()), **payload).status_code == 404


def test_receipt_survives_undo_and_duplicate_requires_explicit_permission(tmp_path):
    client, headers, app = build_reader_bundle(tmp_path)
    create_id, append_id = str(uuid4()), str(uuid4())
    created = capture(client, headers, create_id, action="create", text="Original.")
    document_id = created.json()["document_id"]
    payload = dict(action="append", text="Appended.", document_id=document_id)
    assert capture(client, headers, append_id, **payload).status_code == 200
    repository = app.state.container.reader.service.repository
    document = repository.get_document(document_id)
    undone = repository.undo(document_id, expected_row_version=document.row_version)
    assert capture(client, headers, append_id, **payload).json()["outcome"] == "already_delivered"
    assert repository.get_document(document_id).content_revision == undone.content_revision
    duplicate_id = str(uuid4())
    duplicate = capture(client, headers, duplicate_id, action="create", text="Original.")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["type"] == "reader_duplicate_document"
    assert (
        capture(
            client, headers, duplicate_id, action="create", text="Original.", allow_duplicate=True
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "payload",
    [
        dict(action="create", text=" "),
        dict(action="create", text="ok", document_id="wrong"),
        dict(action="append", text="ok"),
        dict(action="append", text="ok", document_id="a", target_operation_id="b"),
    ],
)
def test_capture_validation_and_authentication(tmp_path, payload):
    client, headers, _ = build_reader_bundle(tmp_path)
    operation = str(uuid4())
    assert capture(client, {}, operation, **payload).status_code == 401
    assert capture(client, headers, operation, **payload).status_code == 400


def test_rate_limit_response_supplies_a_bounded_retry_after(tmp_path):
    client, headers, app = build_reader_bundle(tmp_path)
    app.state.container.rate_limiter.requests_per_minute = 1
    operation = str(uuid4())
    payload = dict(action="create", text="Rate limited capture.")
    assert capture(client, headers, operation, **payload).status_code == 200
    limited = capture(client, headers, operation, **payload)
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["Retry-After"]) <= 60
    app.state.container.rate_limiter._events.clear()
    assert capture(client, headers, operation, **payload).json()["outcome"] == "already_delivered"


def test_capture_privacy_denial_rolls_back_and_can_be_retried_after_unlock(tmp_path):
    client, headers, app = build_reader_bundle(tmp_path)
    folder = client.post("/v1/reader/folders", headers=headers, json={"name": "Protected"}).json()
    created = capture(
        client,
        headers,
        str(uuid4()),
        action="create",
        text="Protected first.",
        folder_id=folder["id"],
    )
    document_id = created.json()["document_id"]
    setup = client.put(
        f"/v1/reader/folders/{folder['id']}/privacy-lock",
        headers=headers,
        json={"code": "six secret words", "expected_row_version": folder["row_version"]},
    )
    assert setup.status_code == 200
    operation = str(uuid4())
    payload = dict(action="append", text="Protected second.", document_id=document_id)
    blocked = capture(client, headers, operation, **payload)
    assert blocked.status_code == 423, blocked.text
    assert (
        capture(
            client,
            headers,
            str(uuid4()),
            action="create",
            text="Blocked create.",
            folder_id=folder["id"],
        ).status_code
        == 423
    )
    authorized = {**headers, "X-Reader-Privacy-Sessions": setup.json()["session"]["session_token"]}
    assert capture(client, authorized, operation, **payload).status_code == 200
    assert capture(client, headers, operation, **payload).status_code == 423
    assert (
        app.state.container.reader.service.repository.get_document(document_id).content_revision
        == 2
    )


def test_receipt_failure_rolls_back_article_and_retry_survives_restart(tmp_path):
    client, headers, app = build_reader_bundle(tmp_path)
    repository = app.state.container.reader.service.repository
    with repository._write() as connection:
        connection.execute("""CREATE TRIGGER reject_capture BEFORE INSERT ON reader_capture_receipts
                              BEGIN SELECT RAISE(ABORT, 'synthetic receipt failure'); END""")
    operation = str(uuid4())
    payload = dict(action="create", text="Atomic capture.")
    assert capture(client, headers, operation, **payload).status_code == 503
    with repository._write() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reader_documents").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM reader_capture_receipts").fetchone()[0] == 0
        connection.execute("DROP TRIGGER reject_capture")
    assert capture(client, headers, operation, **payload).status_code == 200
    restarted, restarted_headers, _ = build_reader_bundle(tmp_path)
    replay = capture(restarted, restarted_headers, operation, **payload)
    assert replay.json()["outcome"] == "already_delivered"
