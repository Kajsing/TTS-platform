from __future__ import annotations

import json
import uuid
from contextlib import contextmanager

import pytest
from reader_core import (
    FolderDocumentVersion,
    ReaderConflictError,
    ReaderFolder,
    ReaderFolderPrivacy,
    ReaderValidationError,
)
from reader_core.agent_access import AgentConflictError, AgentUnauthorizedError, ChapterDelivery
from reader_core.chapters import CHAPTER_KEY
from reader_core.models import utc_now
from reader_core.sqlite.agent_content import (
    MAX_CONTENT_BLOCKS,
    MAX_CONTENT_CHARACTERS,
    MAX_MARKER_JSON_CHARACTERS,
    MAX_SEARCH_SCAN,
)
from reader_core.sqlite.agent_repository import SqliteReaderAgentRepository

ContentRepository = SqliteReaderAgentRepository


@pytest.fixture
def content(repository):
    now = utc_now()
    folder = repository.create_folder(ReaderFolder(str(uuid.uuid4()), "Agent", "agent", now, now))
    agents = ContentRepository(repository)
    grant, secret = agents.provision(folder.id, "Agent")
    document = agents.create_article(
        secret, title="Chapters", text="Alpha 😀 beta.\n\nSecond para.\n\nThird end."
    )
    blocks = repository.list_blocks(document.id)
    document = repository.edit_chapter(
        document.id,
        expected_row_version=1,
        action="add",
        block_id=blocks[0].id,
        codepoint_offset=len("Alpha 😀 "),
        title="Middle",
    )
    document = repository.edit_chapter(
        document.id,
        expected_row_version=2,
        action="add",
        block_id=blocks[2].id,
        codepoint_offset=0,
        title="Last",
    )
    return agents, grant, secret, document


def test_chapter_discovery_and_paged_text_recombine_exactly(content):
    agents, _, secret, document = content
    first = agents.list_content_chapters(secret, document.id, expected_row_version=3, limit=2)
    assert first["chapter_count"] == 3 and first["next_offset"] == 2
    second = agents.list_content_chapters(secret, document.id, expected_row_version=3, offset=2)
    chapters = first["items"] + second["items"]
    assert [item["title"] for item in chapters] == ["Chapter 1", "Middle", "Last"]
    texts = []
    for chapter in chapters:
        text = ""
        offset = 0
        while True:
            page = agents.read_chapter(
                secret,
                document.id,
                chapter["id"],
                expected_row_version=3,
                offset=offset,
                limit=3,
            )
            assert len(page["text"]) <= 3
            text += page["text"]
            if page["next_offset"] is None:
                assert len(text) == page["text_length"]
                break
            offset = page["next_offset"]
        texts.append(text)
    assert texts == ["Alpha 😀 ", "beta.\n\nSecond para.\n\n", "Third end."]
    assert "".join(texts) == agents.read_article(secret, document.id).text
    assert set(first["article"]) == {
        "id",
        "title",
        "folder_id",
        "row_version",
        "content_revision",
        "state",
        "total_characters",
        "updated_at",
    }


def test_literal_search_handles_overlap_non_bmp_boundaries_and_pagination(content):
    agents, _, secret, document = content
    article = agents.create_article(secret, title="Search", text="😀aaaa\n\nAAA 😀aaaa")
    offsets = []
    offset = 0
    while True:
        result = agents.search_article(
            secret, article.id, query="aa", expected_row_version=1, offset=offset, limit=2
        )
        offsets.extend(item["offset"] for item in result["items"])
        assert result["match_mode"] == "literal_case_sensitive"
        if result["next_offset"] is None:
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
    assert offsets == [1, 2, 3, 12, 13, 14]
    result = agents.search_article(secret, document.id, query=".\n\nSecond", expected_row_version=3)
    assert result["items"] == [{"offset": 12, "end_offset": 21, "text": ".\n\nSecond"}]
    # Regex metacharacters have no special meaning.
    assert not agents.search_article(secret, document.id, query=".*", expected_row_version=3)[
        "items"
    ]


def test_search_empty_scan_page_continues_and_finds_cross_scan_match(content):
    agents, _, secret, _ = content
    text = "x" * (MAX_SEARCH_SCAN - 1) + "needle" + "x" * 20 + "needle"
    article = agents.create_article(secret, title="Scan", text=text)
    first = agents.search_article(secret, article.id, query="absent", expected_row_version=1)
    assert first["items"] == [] and first["next_offset"] == MAX_SEARCH_SCAN
    assert first["scanned_characters"] == MAX_SEARCH_SCAN
    found = agents.search_article(secret, article.id, query="needle", expected_row_version=1)
    assert [item["offset"] for item in found["items"]] == [MAX_SEARCH_SCAN - 1]
    following = agents.search_article(
        secret, article.id, query="needle", expected_row_version=1, offset=found["next_offset"]
    )
    assert [item["offset"] for item in following["items"]] == [MAX_SEARCH_SCAN + 25]
    assert following["next_offset"] is None


def test_missing_or_merged_chapter_is_explicit_and_old_pages_conflict(repository, content):
    agents, _, secret, document = content
    chapter = agents.list_content_chapters(secret, document.id, expected_row_version=3)["items"][1]
    updated = repository.edit_chapter(
        document.id, expected_row_version=3, action="merge", chapter_id=chapter["id"]
    )
    with pytest.raises(ReaderConflictError):
        agents.read_chapter(secret, document.id, chapter["id"], expected_row_version=3)
    with pytest.raises(AgentConflictError, match="unavailable"):
        agents.read_chapter(
            secret, document.id, chapter["id"], expected_row_version=updated.row_version
        )
    with pytest.raises(ReaderConflictError):
        agents.search_article(secret, document.id, query="Alpha", expected_row_version=3)


def test_undo_delivery_changes_structure_without_restoring_receipt_text(repository, content):
    agents, _, secret, document = content
    receipt = agents.deliver_chapter(
        secret,
        document.id,
        ChapterDelivery("story", "new", "retry", "https://example.com/chapter", "New", "New body"),
        expected_row_version=3,
    )
    chapters = agents.list_content_chapters(secret, document.id, expected_row_version=4)["items"]
    new_id = chapters[-1]["id"]
    undone = repository.undo(document.id, expected_row_version=4)
    assert agents.list_chapters(secret, document.id)[0].id == receipt.id
    with pytest.raises(AgentConflictError):
        agents.read_chapter(secret, document.id, new_id, expected_row_version=undone.row_version)


@pytest.mark.parametrize("change", ["revoke", "move", "delete", "privacy"])
def test_every_content_read_rechecks_scope(repository, content, change):
    agents, grant, secret, document = content
    if change == "revoke":
        agents.revoke(grant.id)
    elif change == "move":
        repository.move_documents((FolderDocumentVersion(document.id, 3),), folder_id=None)
    elif change == "delete":
        repository.soft_delete_document(document.id, expected_row_version=3)
    else:
        repository.set_folder_privacy(
            ReaderFolderPrivacy(grant.folder_id, "x" * 64, "y" * 64, utc_now()),
            expected_row_version=1,
        )
    for operation in (
        lambda: agents.list_content_chapters(secret, document.id, expected_row_version=3),
        lambda: agents.read_chapter(secret, document.id, "root", expected_row_version=3),
        lambda: agents.search_article(secret, document.id, query="Alpha", expected_row_version=3),
    ):
        with pytest.raises(AgentUnauthorizedError):
            operation()


@pytest.mark.parametrize("corruption", [None, [], [{"id": "bad"}], "invalid"])
def test_invalid_structural_metadata_returns_conflict(repository, content, corruption):
    agents, _, secret, document = content
    with repository._write() as connection:
        connection.execute(
            "UPDATE reader_documents SET metadata_json = ? WHERE id = ?",
            (json.dumps({CHAPTER_KEY: corruption}), document.id),
        )
    with pytest.raises(AgentConflictError):
        agents.list_content_chapters(secret, document.id, expected_row_version=3)


def test_content_source_hydration_is_substring_bounded_and_no_full_bundle(repository, content):
    agents, _, secret, _ = content
    article = agents.create_article(secret, title="Large block", text="a" * 190_000)
    statements = []
    original_scope = agents._scope

    @contextmanager
    def traced_scope(*args, **kwargs):
        with original_scope(*args, **kwargs) as scope:
            scope[1].set_trace_callback(statements.append)
            yield scope

    agents._scope = traced_scope
    page = agents.read_chapter(
        secret, article.id, "root", expected_row_version=1, offset=150_000, limit=7
    )
    assert page["text"] == "a" * 7
    assert any("substr(text, 150001, 7)" in query for query in statements)
    assert not any(
        "SELECT text FROM" in query or "SELECT * FROM reader_blocks" in query
        for query in statements
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_row_version": True},
        {"offset": True},
        {"limit": True},
        {"offset": -1},
        {"limit": 20_001},
        {"offset": 1_000},
    ],
)
def test_invalid_chapter_paging_is_rejected(content, changes):
    agents, _, secret, document = content
    arguments = {"expected_row_version": 3, "offset": 0, "limit": 20_000} | changes
    with pytest.raises(ReaderValidationError):
        agents.read_chapter(secret, document.id, "root", **arguments)


def test_read_permission_is_required_and_scope_does_not_leak_ids(repository, content):
    agents, grant, _, document = content
    _, secret = agents.provision(grant.folder_id, "List only", operations=("list",))
    for identifier in (document.id, str(uuid.uuid4())):
        with pytest.raises(AgentUnauthorizedError):
            agents.read_chapter(secret, identifier, "root", expected_row_version=3)
        with pytest.raises(AgentUnauthorizedError):
            agents.search_article(secret, identifier, query="Alpha", expected_row_version=3)


@pytest.mark.parametrize(
    "column,value",
    [("total_blocks", MAX_CONTENT_BLOCKS + 1), ("total_characters", MAX_CONTENT_CHARACTERS + 1)],
)
def test_oversized_source_is_refused_before_hydrating_any_source(
    repository, content, column, value
):
    agents, _, secret, document = content
    with repository._write() as connection:
        connection.execute(
            f"UPDATE reader_documents SET {column} = ? WHERE id = ?", (value, document.id)
        )
    for operation in (
        lambda: agents.list_content_chapters(secret, document.id, expected_row_version=3),
        lambda: agents.read_chapter(secret, document.id, "root", expected_row_version=3),
        lambda: agents.search_article(secret, document.id, query="Alpha", expected_row_version=3),
    ):
        with pytest.raises(ReaderValidationError, match="source limits"):
            operation()


def test_current_chapter_text_follows_normal_revisioned_edits(repository, content):
    agents, _, secret, document = content
    block = repository.list_blocks(document.id)[0]
    edited, _ = repository.replace_block_text(
        document.id,
        block.id,
        start_offset=0,
        end_offset=5,
        replacement_text="Opening",
        expected_row_version=3,
    )
    text = agents.read_chapter(
        secret, document.id, "root", expected_row_version=edited.row_version
    )["text"]
    assert text == "Opening 😀 "
    assert agents.search_article(
        secret, document.id, query="Opening", expected_row_version=edited.row_version
    )["items"] == [{"offset": 0, "end_offset": 7, "text": "Opening"}]


@pytest.mark.parametrize("query", ["", " " * 5, "a" * 201, "a\x00b"])
def test_literal_search_rejects_empty_or_oversized_queries(content, query):
    agents, _, secret, document = content
    with pytest.raises(ReaderValidationError):
        agents.search_article(secret, document.id, query=query, expected_row_version=3)


@pytest.mark.parametrize(
    "raw",
    ["{", "[]", "null", "[" * 1100 + "0" + "]" * 1100, " " * (MAX_MARKER_JSON_CHARACTERS + 1)],
    ids=["malformed", "array", "null", "deep-nesting", "oversized"],
)
def test_corrupt_raw_metadata_is_bounded_conflict_but_text_search_remains_usable(
    repository, content, raw
):
    agents, _, secret, document = content
    with repository._write() as connection:
        connection.execute(
            "UPDATE reader_documents SET metadata_json = ? WHERE id = ?", (raw, document.id)
        )
    with pytest.raises(AgentConflictError):
        agents.list_content_chapters(secret, document.id, expected_row_version=3)
    with pytest.raises(AgentConflictError):
        agents.read_chapter(secret, document.id, "root", expected_row_version=3)
    assert agents.search_article(secret, document.id, query="Alpha", expected_row_version=3)[
        "items"
    ] == [{"offset": 0, "end_offset": 5, "text": "Alpha"}]


@pytest.mark.parametrize("marker_id", [" ", "bad\x00id"])
def test_chapter_discovery_does_not_advertise_unreadable_corrupt_ids(
    repository, content, marker_id
):
    agents, _, secret, document = content
    with repository._write() as connection:
        metadata = json.loads(
            connection.execute(
                "SELECT metadata_json FROM reader_documents WHERE id = ?", (document.id,)
            ).fetchone()[0]
        )
        metadata[CHAPTER_KEY][0]["id"] = marker_id
        connection.execute(
            "UPDATE reader_documents SET metadata_json = ? WHERE id = ?",
            (json.dumps(metadata), document.id),
        )
    with pytest.raises(AgentConflictError):
        agents.list_content_chapters(secret, document.id, expected_row_version=3)
