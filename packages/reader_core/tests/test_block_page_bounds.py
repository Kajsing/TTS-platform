from __future__ import annotations

import hashlib
import json

import pytest
from reader_core import ReaderBlockTooLargeError, ReaderLibrary
from reader_core.sqlite import repository as repository_module


def test_raw_byte_pages_reconstruct_complete_blocks_without_skipping(repository):
    document = ReaderLibrary(repository).create_plain_text_document(
        title="Byte pages",
        text="\n\n".join(f"Paragraph {i}: " + "Ω😀" * 25 for i in range(11)),
    )
    expected = repository.list_blocks(document.id)
    actual = []
    after = -1
    while True:
        page = repository.list_blocks_bounded(
            document.id, after_ordinal=after, limit=8, max_bytes=400
        )
        assert page.blocks
        assert (
            sum(
                len(block.text.encode()) + len(json.dumps(dict(block.metadata)).encode())
                for block in page.blocks
            )
            <= 400
        )
        actual.extend(page.blocks)
        if page.next_after_ordinal is None:
            break
        assert page.next_after_ordinal > after
        after = page.next_after_ordinal
    assert actual == list(expected)


def test_character_preflight_rejects_before_byte_scan_or_block_hydration(repository, monkeypatch):
    document = ReaderLibrary(repository).create_plain_text_document(
        title="Large", text="x" * 1_000_001
    )
    statements = []
    original_connect = repository_module.connect_sqlite

    def connect(path):
        connection = original_connect(path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(repository_module, "connect_sqlite", connect)
    monkeypatch.setattr(
        repository_module, "_block_from_row", lambda _: pytest.fail("Hydrated refused block")
    )
    with pytest.raises(ReaderBlockTooLargeError) as refused:
        repository.list_blocks_bounded(document.id, max_bytes=2 * 1024 * 1024)
    assert refused.value.character_count == 1_000_001
    assert refused.value.text_bytes is None
    assert not any("CAST(text AS BLOB)" in statement for statement in statements)
    assert not any("SELECT * FROM reader_blocks" in statement for statement in statements)


@pytest.mark.parametrize("oversized_metadata", [False, True])
def test_byte_preflight_refuses_before_hydration(repository, monkeypatch, oversized_metadata):
    document = ReaderLibrary(repository).create_plain_text_document(
        title="Preflight",
        text="short" if oversized_metadata else "😀" * 300,
    )
    if oversized_metadata:
        with repository._write() as connection:
            connection.execute(
                "UPDATE reader_blocks SET metadata_json = ? WHERE document_id = ?",
                (json.dumps({"source": "private" * 300}), document.id),
            )
    monkeypatch.setattr(
        repository_module, "_block_from_row", lambda _: pytest.fail("Hydrated refused block")
    )
    with pytest.raises(ReaderBlockTooLargeError) as refused:
        repository.list_blocks_bounded(document.id, max_bytes=1000)
    assert refused.value.text_bytes + refused.value.metadata_bytes > 1000


def test_later_oversized_block_is_not_skipped(repository):
    document = ReaderLibrary(repository).create_plain_text_document(
        title="Later block",
        text="Small first.\n\n" + "x" * 1500,
    )
    page = repository.list_blocks_bounded(document.id, max_bytes=1000)
    assert [block.text for block in page.blocks] == ["Small first."]
    assert page.next_after_ordinal == 0
    with pytest.raises(ReaderBlockTooLargeError) as refused:
        repository.list_blocks_bounded(document.id, after_ordinal=0, max_bytes=1000)
    assert refused.value.ordinal == 1


def test_preflight_and_hydration_share_one_snapshot(repository, monkeypatch):
    document = ReaderLibrary(repository).create_plain_text_document(
        title="Snapshot", text="Original."
    )
    block = repository.list_blocks(document.id)[0]
    original_connect = repository_module.connect_sqlite
    changed = False
    mutation_errors = []
    new_text = "changed" * 500

    def before_hydration(statement):
        nonlocal changed
        if changed or not statement.startswith("SELECT * FROM reader_blocks WHERE id"):
            return
        changed = True
        try:
            with original_connect(repository.database_path) as writer:
                writer.execute(
                    "UPDATE reader_blocks SET text = ?, character_count = ?, content_sha256 = ?, "
                    "row_version = row_version + 1 WHERE id = ?",
                    (
                        new_text,
                        len(new_text),
                        hashlib.sha256(new_text.encode()).hexdigest(),
                        block.id,
                    ),
                )
                writer.execute(
                    "UPDATE reader_documents SET total_characters = ?, "
                    "content_revision = content_revision + 1, row_version = row_version + 1 "
                    "WHERE id = ?",
                    (len(new_text), document.id),
                )
        except Exception as error:
            mutation_errors.append(error)

    def connect(path):
        connection = original_connect(path)
        connection.set_trace_callback(before_hydration)
        return connection

    monkeypatch.setattr(repository_module, "connect_sqlite", connect)
    page = repository.list_blocks_bounded(document.id, max_bytes=1000)
    assert changed and not mutation_errors
    assert page.blocks[0].text == "Original."
    assert repository.list_blocks(document.id)[0].text == new_text


@pytest.mark.parametrize(
    "options",
    [dict(max_bytes=0), dict(max_bytes=100, limit=0), dict(max_bytes=100, max_characters=0)],
)
def test_bounded_pagination_rejects_invalid_limits(repository, options):
    document = ReaderLibrary(repository).create_plain_text_document(title="Limits", text="Text.")
    from reader_core import ReaderValidationError

    with pytest.raises(ReaderValidationError):
        repository.list_blocks_bounded(document.id, **options)
