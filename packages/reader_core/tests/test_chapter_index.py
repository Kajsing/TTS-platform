from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import pytest
from reader_core import ReaderConflictError, ReaderLibrary, ReaderValidationError
from reader_core.chapter_index import ChapterIndexConflictError
from reader_core.chapters import CHAPTER_KEY
from reader_core.sqlite.chapter_index import read_chapter_index


def set_metadata(repository, document_id, value):
    with repository._write() as connection:
        connection.execute(
            "UPDATE reader_documents SET metadata_json = ? WHERE id = ?",
            (json.dumps(value), document_id),
        )


def marker(block_id, offset=0, *, id="root", title="Chapter 1"):
    return {"id": id, "title": title, "block_id": block_id, "codepoint_offset": offset}


@contextmanager
def scalar_blocks_only(repository, monkeypatch):
    original_connection = repository._connection
    statements = []
    denied = []

    @contextmanager
    def guarded_connection():
        with original_connection() as connection:

            def authorize(action, table, column, database, trigger):
                if (
                    action == sqlite3.SQLITE_READ
                    and table == "reader_blocks"
                    and column not in {"id", "document_id", "ordinal", "character_count"}
                ):
                    denied.append(column)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            connection.set_authorizer(authorize)
            connection.set_trace_callback(statements.append)
            try:
                yield connection
            finally:
                connection.set_authorizer(None)
                connection.set_trace_callback(None)

    with monkeypatch.context() as patch:
        patch.setattr(repository, "_connection", guarded_connection)
        yield statements
    assert not denied


def test_missing_markers_use_first_scalar_block_without_loading_source(
    repository, document, monkeypatch
):
    first = repository.list_blocks(document.id)[0]
    with scalar_blocks_only(repository, monkeypatch) as statements:
        index = read_chapter_index(repository, document.id, document.content_revision)
    assert index.document_id == document.id and index.content_revision == document.content_revision
    assert len(index.chapters) == 1
    assert (index.chapters[0].id, index.chapters[0].title) == ("root", "Chapter 1")
    assert (
        index.chapters[0].block_id,
        index.chapters[0].block_ordinal,
        index.chapters[0].codepoint_offset,
    ) == (first.id, 0, 0)
    reads = [statement for statement in statements if "FROM reader_blocks" in statement]
    assert len(reads) == 1 and "LIMIT 1" in reads[0]
    assert sum(statement == "BEGIN" for statement in statements) == 1


def test_unicode_offsets_remain_codepoints_and_end_of_intermediate_block_is_valid(
    repository, monkeypatch
):
    document = ReaderLibrary(repository).create_plain_text_document(
        title="Unicode chapters", text="A😀 B.\n\nSecond block."
    )
    first, second = repository.list_blocks(document.id)
    raw = [
        marker(first.id),
        marker(first.id, 2, id="unicode", title="After A😀"),
        marker(first.id, first.character_count, id="end", title="At block end"),
        marker(second.id, 0, id="second", title="Second block"),
    ]
    set_metadata(repository, document.id, {CHAPTER_KEY: raw})
    with scalar_blocks_only(repository, monkeypatch):
        index = read_chapter_index(repository, document.id, 1)
    assert [item.codepoint_offset for item in index.chapters] == [0, 2, len(first.text), 0]
    assert [item.block_ordinal for item in index.chapters] == [0, 0, 0, 1]
    assert index.chapters[1].title == "After A😀"
    assert repository.get_document(document.id).metadata[CHAPTER_KEY] == raw


def test_1024_markers_use_at_most_three_indexed_id_batches_and_no_unrelated_blocks(
    repository, document, monkeypatch
):
    first = repository.list_blocks(document.id)[0]
    extra_ids = [f"synthetic-chapter-block-{index}" for index in range(1, 1200)]
    with repository._write() as connection:
        connection.executemany(
            "INSERT INTO reader_blocks "
            "SELECT ?, document_id, section_id, ?, kind, text, character_count, "
            "content_sha256, row_version, metadata_json FROM reader_blocks WHERE id = ?",
            ((block_id, ordinal + 1, first.id) for ordinal, block_id in enumerate(extra_ids, 1)),
        )
    raw = [marker(first.id)] + [
        marker(block_id, id=f"chapter-{index}")
        for index, block_id in enumerate(extra_ids[:1023], 1)
    ]
    set_metadata(repository, document.id, {CHAPTER_KEY: raw})
    with scalar_blocks_only(repository, monkeypatch) as statements:
        index = read_chapter_index(repository, document.id, 1)
    assert len(index.chapters) == 1024
    reads = [statement for statement in statements if "FROM reader_blocks" in statement]
    assert len(reads) == 4 and sum("LIMIT 1" in statement for statement in reads) == 1
    lookups = [statement for statement in reads if " IN (" in statement]
    assert len(lookups) == 3
    with repository._connection() as connection:
        for statement in lookups:
            plan = [row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + statement)]
            assert any("sqlite_autoindex_reader_blocks_1 (id=?)" in item for item in plan)
            assert not any("SCAN reader_blocks" in item for item in plan)


@pytest.mark.parametrize(
    "case",
    [
        "null",
        "object",
        "empty",
        "too_many",
        "duplicate_id",
        "duplicate_position",
        "order",
        "missing",
        "foreign",
        "negative",
        "bool_offset",
        "past_end",
        "first_offset",
        "first_block",
        "long_id",
        "blank_title",
        "bad_json",
        "non_object",
    ],
)
def test_malformed_metadata_is_a_typed_conflict_and_is_never_rewritten(repository, document, case):
    first, second = repository.list_blocks(document.id)
    raw = [marker(first.id), marker(second.id, id="second")]
    value = {CHAPTER_KEY: raw}
    if case == "null":
        value[CHAPTER_KEY] = None
    elif case == "object":
        value[CHAPTER_KEY] = {}
    elif case == "empty":
        value[CHAPTER_KEY] = []
    elif case == "too_many":
        value[CHAPTER_KEY] = [marker(first.id, index, id=str(index)) for index in range(1025)]
    elif case == "duplicate_id":
        raw[1]["id"] = raw[0]["id"]
    elif case == "duplicate_position":
        raw[1]["block_id"] = first.id
    elif case == "order":
        raw.extend([marker(first.id, 1, id="out-of-order")])
    elif case == "missing":
        raw[1]["block_id"] = "missing-block"
    elif case == "foreign":
        other = ReaderLibrary(repository).create_plain_text_document(title="Other", text="Other")
        raw[1]["block_id"] = repository.list_blocks(other.id)[0].id
    elif case == "negative":
        raw[1]["codepoint_offset"] = -1
    elif case == "bool_offset":
        raw[1]["codepoint_offset"] = True
    elif case == "past_end":
        raw[1]["codepoint_offset"] = second.character_count + 1
    elif case == "first_offset":
        raw[0]["codepoint_offset"] = 1
    elif case == "first_block":
        raw[0]["block_id"] = second.id
    elif case == "long_id":
        raw[1]["block_id"] = "x" * 101
    elif case == "blank_title":
        raw[1]["title"] = ""
    elif case == "non_object":
        value = []
    set_metadata(repository, document.id, value)
    if case == "bad_json":
        with repository._write() as connection:
            connection.execute(
                "UPDATE reader_documents SET metadata_json = '{bad json' WHERE id = ?",
                (document.id,),
            )
    with repository._connection() as connection:
        before = connection.execute(
            "SELECT metadata_json FROM reader_documents WHERE id = ?", (document.id,)
        ).fetchone()[0]
    with pytest.raises(ChapterIndexConflictError):
        read_chapter_index(repository, document.id, document.content_revision)
    with repository._connection() as connection:
        after = connection.execute(
            "SELECT metadata_json FROM reader_documents WHERE id = ?", (document.id,)
        ).fetchone()[0]
    assert after == before


def test_empty_article_has_no_implicit_chapter_but_explicit_markers_are_invalid(
    repository, document
):
    with repository._write() as connection:
        connection.execute("DELETE FROM reader_blocks WHERE document_id = ?", (document.id,))
    assert read_chapter_index(repository, document.id, 1).chapters == ()
    set_metadata(repository, document.id, {CHAPTER_KEY: [marker("missing")]})
    with pytest.raises(ChapterIndexConflictError):
        read_chapter_index(repository, document.id, 1)


@pytest.mark.parametrize("revision", [0, -1, True])
def test_revision_must_be_positive(repository, document, revision):
    with pytest.raises(ReaderValidationError):
        read_chapter_index(repository, document.id, revision)


def test_stale_revision_is_rejected_before_any_block_query(repository, document, monkeypatch):
    with scalar_blocks_only(repository, monkeypatch) as statements:
        with pytest.raises(ReaderConflictError):
            read_chapter_index(repository, document.id, 2)
    assert not any("FROM reader_blocks" in statement for statement in statements)


def test_metadata_and_anchor_resolution_share_one_read_snapshot(repository, document, monkeypatch):
    first, second = repository.list_blocks(document.id)
    set_metadata(
        repository, document.id, {CHAPTER_KEY: [marker(first.id), marker(second.id, id="2")]}
    )
    original_connection = repository._connection
    changed = False

    @contextmanager
    def writing_between_reads():
        with original_connection() as connection:

            def trace(statement):
                nonlocal changed
                if not changed and "ORDER BY ordinal LIMIT 1" in statement:
                    changed = True
                    with original_connection() as writer:
                        writer.execute("DELETE FROM reader_blocks WHERE id = ?", (second.id,))
                        writer.execute(
                            "UPDATE reader_documents SET content_revision = 2, "
                            "metadata_json = '{}' WHERE id = ?",
                            (document.id,),
                        )
                        writer.commit()

            connection.set_trace_callback(trace)
            try:
                yield connection
            finally:
                connection.set_trace_callback(None)

    monkeypatch.setattr(repository, "_connection", writing_between_reads)
    index = read_chapter_index(repository, document.id, 1)
    assert changed and index.content_revision == 1
    assert [item.block_id for item in index.chapters] == [first.id, second.id]
    assert repository.get_document(document.id).content_revision == 2
