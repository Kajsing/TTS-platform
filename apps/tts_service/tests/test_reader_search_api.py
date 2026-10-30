from __future__ import annotations

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from reader_core import FolderDocumentVersion
from reader_core.sqlite import search_source
from tts_service import reader_search, reader_search_routes
from tts_service.config import AppConfig
from tts_service.main import create_app
from tts_service.reader_privacy import PRIVACY_SESSION_HEADER
from tts_service.reader_search import ReaderSearchError


@pytest.fixture
def bundle(tmp_path):
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"warmup_on_start": False},
                "backend": {"mode": "stub"},
                "reader": {
                    "home_path": str(tmp_path / "reader"),
                    "exports": {"formats": ["wav"]},
                },
                "limits": {"requests_per_minute": 1000, "playback_requests_per_minute": 1000},
            }
        ),
        repo_root=tmp_path,
    )
    headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        yield SimpleNamespace(
            app=app,
            client=client,
            headers=headers,
            service=app.state.container.reader.service,
            manager=app.state.container.reader_search,
        )


def create_document(bundle, text="One paragraph.\n\nSecond paragraph."):
    response = bundle.client.post(
        "/v1/reader/documents",
        headers=bundle.headers,
        json={"title": "Synthetic search article", "source_type": "plain_text", "text": text},
    )
    assert response.status_code == 201, response.text
    return response.json()


def path(document, suffix):
    return f"/v1/reader/documents/{document['id']}/{suffix}"


def start_find(bundle, document, query="paragraph", **options):
    response = bundle.client.post(
        path(document, "search"),
        headers=bundle.headers,
        json={"expected_content_revision": document["content_revision"], "query": query, **options},
    )
    assert response.status_code == 200, response.text
    return response.json()


def result_page(bundle, document, search_id, **payload):
    return bundle.client.post(
        path(document, f"search/{search_id}/results"), headers=bundle.headers, json=payload
    )


def set_terms(bundle, *terms):
    current = bundle.service.repository.get_highlighter_configuration()
    response = bundle.client.put(
        "/v1/reader/highlighter",
        headers=bundle.headers,
        json={
            "expected_row_version": current.row_version,
            "terms": [{"term": term, "active": True} for term in terms],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def start_highlights(bundle, document, config):
    response = bundle.client.post(
        path(document, "highlights"),
        headers=bundle.headers,
        json={
            "expected_content_revision": document["content_revision"],
            "expected_highlighter_row_version": config["row_version"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_cross_block_emoji_source_returns_exact_utf16_cursors_without_source_text(bundle):
    document = create_document(bundle, "😀 one\n\ntwo tail.")
    summary = start_find(bundle, document, "one\r\n\r\ntwo")
    assert summary["total_matches"] == 1
    assert summary["failure"] is None and not summary["truncated"]
    response = result_page(bundle, document, summary["search_id"])
    assert response.status_code == 200, response.text
    result = response.json()
    match = result["matches"][0]
    blocks = bundle.service.repository.list_blocks(document["id"])
    assert (match["start"], match["length"]) == (3, 10)
    assert match["start_cursor"] == {
        "document_id": document["id"],
        "block_id": blocks[0].id,
        "block_ordinal": 0,
        "character_offset": 3,
        "content_revision": document["content_revision"],
    }
    assert match["end_cursor"]["block_id"] == blocks[1].id
    assert match["end_cursor"]["block_ordinal"] == 1
    assert match["end_cursor"]["character_offset"] == 3
    assert "one" not in response.text and "tail" not in response.text and "😀" not in response.text
    greedy = start_find(bundle, document, r"one[\s\S]*tail\.", use_regex=True)
    assert greedy["regex_dialect"] == "regex-v0" and greedy["total_matches"] == 1
    greedy_hit = result_page(bundle, document, greedy["search_id"]).json()["matches"][0]
    assert greedy_hit["end_cursor"]["character_offset"] == len("two tail.")


def test_find_cap_and_paging_remain_bounded_and_explicit(bundle):
    document = create_document(bundle, "word " * 100)
    summary = start_find(bundle, document, "word", max_results=3)
    assert summary["total_matches"] == 3 and summary["truncated"]
    first = result_page(bundle, document, summary["search_id"], offset=0, limit=2)
    assert first.status_code == 200
    assert [item["index"] for item in first.json()["matches"]] == [0, 1]
    assert first.json()["next_offset"] == 2
    second = result_page(bundle, document, summary["search_id"], offset=2, limit=2)
    assert [item["index"] for item in second.json()["matches"]] == [2]
    assert second.json()["next_offset"] is None
    rejected = result_page(bundle, document, summary["search_id"], limit=1001)
    assert rejected.status_code == 400
    assert len(first.content) < 1024 * 1024


def test_highlighter_counts_window_and_next_wrap_preserve_term_identity(bundle):
    document = create_document(bundle, "New York New.\n\nNEW YORK.\n\nNew only.")
    config = set_terms(bundle, "New", "New York")
    by_text = {term["term"]: term["id"] for term in config["terms"]}
    summary = start_highlights(bundle, document, config)
    assert summary["counts"] == {by_text["New"]: 2, by_text["New York"]: 2}
    assert summary["total_matches"] == 4 and summary["regex_dialect"] == "regex-v0"
    base = f"search/{summary['search_id']}"
    window = bundle.client.post(
        path(document, base + "/window"),
        headers=bundle.headers,
        json={"start_ordinal": 1, "end_ordinal": 1},
    )
    assert window.status_code == 200, window.text
    assert len(window.json()["matches"]) == 1
    assert window.json()["matches"][0]["term_id"] == by_text["New York"]
    assert window.json()["matches"][0]["start_cursor"]["block_ordinal"] == 1
    indexes = []
    after = -1
    for _ in range(3):
        next_match = bundle.client.post(
            path(document, base + "/next"),
            headers=bundle.headers,
            json={"term_id": by_text["New York"], "after_index": after},
        )
        assert next_match.status_code == 200, next_match.text
        after = next_match.json()["match"]["index"]
        indexes.append(after)
    assert indexes == [0, 2, 0]
    invalid_window = bundle.client.post(
        path(document, base + "/window"),
        headers=bundle.headers,
        json={"start_ordinal": 2, "end_ordinal": 1},
    )
    assert invalid_window.status_code == 400


def search_requests(document, session_id, revision, config_version):
    return [
        (path(document, "search"), {"expected_content_revision": revision, "query": "paragraph"}),
        (
            path(document, "highlights"),
            {
                "expected_content_revision": revision,
                "expected_highlighter_row_version": config_version,
            },
        ),
        (path(document, f"search/{session_id}/results"), {}),
        (path(document, f"search/{session_id}/window"), {"start_ordinal": 0, "end_ordinal": 1}),
        (path(document, f"search/{session_id}/next"), {"term_id": "synthetic-term"}),
    ]


def test_every_search_operation_authenticates_before_json_and_rejects_foreign_origins(bundle):
    document = create_document(bundle)
    config = set_terms(bundle, "paragraph")
    summary = start_find(bundle, document)
    for endpoint, _ in search_requests(
        document, summary["search_id"], document["content_revision"], config["row_version"]
    ):
        unauthenticated = bundle.client.post(endpoint, content=b"{bad json")
        assert unauthenticated.status_code == 401, (endpoint, unauthenticated.text)
        origin = bundle.client.post(
            endpoint,
            headers={**bundle.headers, "Origin": "https://foreign.invalid"},
            content=b"{bad json",
        )
        assert origin.status_code == 403, (endpoint, origin.text)


def test_every_search_operation_checks_privacy_even_for_existing_sessions(bundle):
    document = create_document(bundle)
    config = set_terms(bundle, "paragraph")
    summary = start_find(bundle, document)
    folder = bundle.service.create_folder("Private search")
    bundle.service.move_documents(
        (FolderDocumentVersion(document["id"], document["row_version"]),), folder_id=folder.id
    )
    privacy = bundle.service.privacy.setup(
        folder.id, code="correct code", expected_row_version=folder.row_version
    )
    private_headers = {**bundle.headers, PRIVACY_SESSION_HEADER: privacy.session.token}
    requests = search_requests(
        document, summary["search_id"], document["content_revision"], config["row_version"]
    )
    for endpoint, payload in requests:
        blocked = bundle.client.post(endpoint, headers=bundle.headers, json=payload)
        assert blocked.status_code == 423, (endpoint, blocked.text)
        assert blocked.json()["error"]["type"] == "reader_privacy_locked"
        allowed = bundle.client.post(endpoint, headers=private_headers, json=payload)
        assert allowed.status_code == 200, (endpoint, allowed.text)
    bundle.service.privacy.relock(folder.id, (privacy.session.token,))
    for endpoint, payload in requests:
        blocked = bundle.client.post(endpoint, headers=private_headers, json=payload)
        assert blocked.status_code == 423, (endpoint, blocked.text)
        assert blocked.json()["error"]["type"] == "reader_privacy_locked"


def test_privacy_relock_during_scan_discards_the_new_session(bundle, monkeypatch):
    document = create_document(bundle)
    folder = bundle.service.create_folder("Private scan")
    bundle.service.move_documents(
        (FolderDocumentVersion(document["id"], document["row_version"]),), folder_id=folder.id
    )
    privacy = bundle.service.privacy.setup(
        folder.id, code="correct code", expected_row_version=folder.row_version
    )
    original = reader_search.search_text

    def relocking_scan(*args, **kwargs):
        result = original(*args, **kwargs)
        bundle.service.privacy.relock(folder.id, (privacy.session.token,))
        return result

    monkeypatch.setattr(reader_search, "search_text", relocking_scan)
    response = bundle.client.post(
        path(document, "search"),
        headers={**bundle.headers, PRIVACY_SESSION_HEADER: privacy.session.token},
        json={"expected_content_revision": document["content_revision"], "query": "paragraph"},
    )
    assert response.status_code == 423
    assert response.json()["error"]["type"] == "reader_privacy_locked"
    assert not bundle.manager._sessions


def test_sessions_reject_changed_document_or_highlighter_configuration(bundle):
    document = create_document(bundle)
    config = set_terms(bundle, "paragraph")
    highlights = start_highlights(bundle, document, config)
    set_terms(bundle, "Second")
    changed_config = result_page(bundle, document, highlights["search_id"])
    assert changed_config.status_code == 409
    assert changed_config.json()["error"]["type"] == "reader_search_configuration_changed"
    find = start_find(bundle, document)
    bundle.service.repository.append_text(
        document["id"], "Extra paragraph.", expected_row_version=document["row_version"]
    )
    changed = result_page(bundle, document, find["search_id"])
    assert changed.status_code == 409
    assert changed.json()["error"]["type"] == "reader_revision_conflict"


def test_body_limit_precedes_json_and_all_logs_omit_query_source_and_credentials(
    bundle, monkeypatch
):
    document = create_document(bundle, "PRIVATE SOURCE PARAGRAPH")
    summary = start_find(bundle, document, "PRIVATE")
    for endpoint, _ in search_requests(document, summary["search_id"], 1, 1):
        response = bundle.client.post(endpoint, headers=bundle.headers, content=b"{" + b" " * 16384)
        assert response.status_code == 413, (endpoint, response.text)
        assert response.json()["error"]["type"] == "reader_search_request_too_large"
    logs = []
    monkeypatch.setattr(bundle.app.state.container.observability.logger, "info", logs.append)
    query = "PRIVATE QUERY PHRASE"
    response = bundle.client.post(
        path(document, "search") + "?token=QUERY_SECRET&text=QUERY_TEXT",
        headers=bundle.headers,
        json={"expected_content_revision": document["content_revision"], "query": query},
    )
    assert response.status_code == 200, response.text
    combined = json.dumps(logs)
    for private in [
        query,
        "PRIVATE SOURCE PARAGRAPH",
        "QUERY_SECRET",
        "QUERY_TEXT",
        bundle.headers["Authorization"],
    ]:
        assert private not in combined


def test_source_limit_returns_no_source_body_and_empty_query_avoids_hydration(bundle, monkeypatch):
    document = create_document(bundle, "PRIVATE source is deliberately beyond the test bound.")
    monkeypatch.setattr(search_source, "MAX_SEARCH_UTF16", 8)
    summary = start_find(bundle, document, "PRIVATE")
    assert summary["failure"] == "document_too_large" and summary["total_matches"] == 0
    assert "PRIVATE" not in json.dumps(summary)
    assert result_page(bundle, document, summary["search_id"]).json()["matches"] == []

    def no_hydration(*args, **kwargs):
        raise AssertionError("Empty search hydrated source text")

    monkeypatch.setattr(reader_search, "read_search_source", no_hydration)
    empty = start_find(bundle, document, "")
    assert empty["failure"] is None and empty["total_matches"] == 0
    config = bundle.service.repository.get_highlighter_configuration()
    inactive = start_highlights(bundle, document, {"row_version": config.row_version})
    assert inactive["failure"] is None and inactive["total_matches"] == 0


@pytest.mark.parametrize("limit", ["MAX_SEARCH_BLOCKS", "MAX_SEARCH_UTF16"])
def test_source_preflight_rejects_before_reading_any_block_text(bundle, monkeypatch, limit):
    document = create_document(bundle, "First synthetic block.\n\nSecond synthetic block.")
    monkeypatch.setattr(search_source, limit, 1)
    repository = bundle.service.repository
    original_connection = repository._connection
    text_reads = []
    statements = []

    @contextmanager
    def guarded_connection():
        with original_connection() as connection:
            def authorize(action, table, column, database, trigger):
                if action == sqlite3.SQLITE_READ and table == "reader_blocks" and column == "text":
                    text_reads.append(column)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            connection.set_authorizer(authorize)
            connection.set_trace_callback(statements.append)
            try:
                yield connection
            finally:
                connection.set_authorizer(None)
                connection.set_trace_callback(None)

    monkeypatch.setattr(repository, "_connection", guarded_connection)
    summary = start_find(bundle, document, "synthetic")
    assert summary["failure"] == "document_too_large"
    assert summary["total_matches"] == 0 and not text_reads
    preflight = next(statement for statement in statements if "SUM(character_count)" in statement)
    assert "LIMIT " in preflight


@pytest.mark.parametrize("operation", ["results", "window", "next"])
@pytest.mark.parametrize("change", ["revision", "configuration", "privacy"])
def test_result_operations_recheck_state_after_building_response(
    bundle, monkeypatch, operation, change
):
    document = create_document(bundle)
    config = set_terms(bundle, "paragraph")
    headers = bundle.headers
    if change == "privacy":
        folder = bundle.service.create_folder("Private result fence")
        bundle.service.move_documents(
            (FolderDocumentVersion(document["id"], document["row_version"]),), folder_id=folder.id
        )
        privacy = bundle.service.privacy.setup(
            folder.id, code="correct code", expected_row_version=folder.row_version
        )
        headers = {**headers, PRIVACY_SESSION_HEADER: privacy.session.token}
    response = bundle.client.post(
        path(document, "highlights"),
        headers=headers,
        json={
            "expected_content_revision": document["content_revision"],
            "expected_highlighter_row_version": config["row_version"],
        },
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["search_id"]
    original_response = reader_search_routes._response

    def changed_after_encoding(*args, **kwargs):
        response = original_response(*args, **kwargs)
        if change == "revision":
            current = bundle.service.repository.get_document(document["id"])
            bundle.service.repository.append_text(
                document["id"], "Changed after response encoding.",
                expected_row_version=current.row_version,
            )
        elif change == "configuration":
            current = bundle.service.repository.get_highlighter_configuration()
            bundle.service.repository.replace_highlighter_terms(
                current.terms, expected_row_version=current.row_version
            )
        else:
            bundle.service.privacy.relock(folder.id, (privacy.session.token,))
        return response

    monkeypatch.setattr(reader_search_routes, "_response", changed_after_encoding)
    payload = {
        "results": {},
        "window": {"start_ordinal": 0, "end_ordinal": 1},
        "next": {"term_id": config["terms"][0]["id"]},
    }[operation]
    response = bundle.client.post(
        path(document, f"search/{session_id}/{operation}"), headers=headers, json=payload
    )
    expected = {
        "revision": (409, "reader_revision_conflict"),
        "configuration": (409, "reader_search_configuration_changed"),
        "privacy": (423, "reader_privacy_locked"),
    }[change]
    assert response.status_code == expected[0], response.text
    assert response.json()["error"]["type"] == expected[1]


def test_valid_persisted_term_exceeding_utf16_engine_bound_returns_explicit_400(bundle):
    document = create_document(bundle)
    config = set_terms(bundle, "😀" * 101)
    response = bundle.client.post(
        path(document, "highlights"),
        headers=bundle.headers,
        json={
            "expected_content_revision": 1,
            "expected_highlighter_row_version": config["row_version"],
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["type"] == "reader_search_configuration_invalid"


def test_search_sessions_expire_and_lru_is_limited_to_four(bundle):
    document = create_document(bundle)
    sessions = [start_find(bundle, document)["search_id"] for _ in range(4)]
    assert result_page(bundle, document, sessions[0]).status_code == 200
    fifth = start_find(bundle, document)["search_id"]
    assert len(bundle.manager._sessions) == 4
    assert result_page(bundle, document, sessions[1]).status_code == 410
    assert result_page(bundle, document, sessions[0]).status_code == 200
    bundle.manager._sessions[fifth].touched = time.monotonic() - reader_search.SESSION_SECONDS - 1
    expired = result_page(bundle, document, fifth)
    assert expired.status_code == 410
    assert expired.json()["error"]["type"] == "reader_search_expired"


def test_concurrent_scan_is_rejected_with_background_budget_metadata(bundle):
    document = create_document(bundle)
    assert bundle.manager._scan.acquire(blocking=False)
    try:
        response = bundle.client.post(
            path(document, "search"),
            headers=bundle.headers,
            json={"expected_content_revision": 1, "query": "paragraph"},
        )
    finally:
        bundle.manager._scan.release()
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert response.headers["X-TTS-Request-Budget"] == "background"
    assert response.json()["error"]["details"]["request_budget"] == "background"
    assert response.json()["error"]["type"] == "reader_search_busy"


@pytest.mark.parametrize("close", [False, True])
def test_cancel_or_close_before_publication_never_republishes_a_session(bundle, close):
    document = create_document(bundle)
    cancellation = threading.Event()
    publication = threading.Event()
    release = threading.Event()
    original_lock = bundle.manager._lock
    owner = threading.get_ident()

    class PublicationGate:
        def __enter__(self):
            if threading.get_ident() != owner:
                publication.set()
                assert release.wait(5), "Search did not receive publication release"
            return original_lock.__enter__()

        def __exit__(self, *args):
            return original_lock.__exit__(*args)

    bundle.manager._lock = PublicationGate()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            bundle.manager.create, document["id"], 1, query="paragraph", cancellation=cancellation
        )
        try:
            assert publication.wait(5), "Search did not reach publication"
            if close:
                bundle.manager.close()
            else:
                cancellation.set()
        finally:
            release.set()
        with pytest.raises(ReaderSearchError) as failure:
            future.result(timeout=5)
        assert failure.value.kind == "reader_search_cancelled"
    assert not bundle.manager._sessions
