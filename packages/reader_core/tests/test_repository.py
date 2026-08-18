from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from reader_core import (
    Bookmark,
    DocumentState,
    ExportAudioFormat,
    ExportPhase,
    ExportStatus,
    HighlighterTerm,
    PlaybackPosition,
    QueueItem,
    QueueStatus,
    ReaderConflictError,
    ReaderCursor,
    ReaderDesktopOpenRequest,
    ReaderEditHistoryError,
    ReaderExportJob,
    ReaderLibrary,
    ReaderNotFoundError,
    ReaderStaleCursorError,
    ReaderValidationError,
    RuleScope,
    RuleStage,
    RuleType,
    SpeechRule,
    SpeechRuleSet,
    SqliteReaderRepository,
    initialize_reader_repository,
)
from reader_core.sqlite.connection import connect_sqlite

from .synthetic_library import populate_synthetic_documents


def _cursor(document, block, offset: int) -> ReaderCursor:
    return ReaderCursor(
        document_id=document.id,
        block_id=block.id,
        block_ordinal=block.ordinal,
        character_offset=offset,
        content_revision=document.content_revision,
    )


def test_highlighter_configuration_is_revisioned_and_persistent(repository) -> None:
    initial = repository.get_highlighter_configuration()
    now = datetime.now(timezone.utc)
    terms = (
        HighlighterTerm(
            id=str(uuid.uuid4()),
            term="Mara",
            normalized_term="mara",
            active=True,
            color="#BFE8D5",
            ordinal=0,
            created_at=now,
            updated_at=now,
        ),
    )

    saved = repository.replace_highlighter_terms(
        terms,
        expected_row_version=initial.row_version,
    )
    reopened = SqliteReaderRepository(repository.database_path)

    assert saved.row_version == initial.row_version + 1
    assert reopened.get_highlighter_configuration().terms == terms
    with pytest.raises(ReaderConflictError):
        reopened.replace_highlighter_terms((), expected_row_version=initial.row_version)


def test_rule_sets_rules_versions_and_conflicts_are_persistent(repository) -> None:
    now = datetime.now(timezone.utc)
    rule_set = repository.create_rule_set(
        SpeechRuleSet(
            id=str(uuid.uuid4()),
            name="Danish IT",
            scope=RuleScope.LANGUAGE,
            created_at=now,
            updated_at=now,
        )
    )
    version_after_set = repository.get_rules_version()
    rule = repository.create_rule(
        SpeechRule(
            id=str(uuid.uuid4()),
            rule_set_id=rule_set.id,
            name="Expand fx",
            stage=RuleStage.PRONUNCIATION,
            rule_type=RuleType.LITERAL_REPLACE,
            pattern="fx.",
            replacement="for eksempel",
            language_filter="da",
            created_at=now,
            updated_at=now,
        )
    )

    assert repository.get_rules_version() > version_after_set
    assert repository.list_rules((rule_set.id,)) == (rule,)
    touched_set = repository.get_rule_set(rule_set.id)
    assert touched_set.version == 2
    assert touched_set.row_version == 2

    changed = repository.update_rule(
        replace(rule, replacement="for eksempelvis"),
        expected_row_version=rule.row_version,
    )
    assert changed.replacement == "for eksempelvis"
    assert changed.row_version == 2
    with pytest.raises(ReaderConflictError):
        repository.delete_rule(rule.id, expected_row_version=1)

    repository.record_rule_import(rule_set.id, "a" * 64, {"imported": 1})
    assert repository.get_rule_import_report(rule_set.id, "a" * 64) == {"imported": 1}


def test_document_crud_order_soft_delete_and_restore(repository, document) -> None:
    bundle = repository.get_document_bundle(document.id)

    assert bundle.document == document
    assert [section.ordinal for section in bundle.sections] == [0]
    assert [block.ordinal for block in bundle.blocks] == [0, 1]
    assert [block.text for block in bundle.blocks] == ["Alpha beta gamma.", "Second paragraph."]

    updated = repository.update_document(
        document.id,
        expected_row_version=document.row_version,
        title="Renamed",
        state=DocumentState.ACTIVE,
    )
    assert updated.title == "Renamed"
    assert updated.state is DocumentState.ACTIVE
    assert updated.row_version == 2
    assert updated.content_revision == 1

    deleted = repository.soft_delete_document(
        document.id,
        expected_row_version=updated.row_version,
    )
    assert deleted.deleted_at is not None
    assert repository.list_documents().items == ()

    restored = repository.restore_document(
        document.id,
        expected_row_version=deleted.row_version,
    )
    assert restored.deleted_at is None
    assert repository.list_documents().items[0].id == document.id


def test_document_listing_filters_title_and_finds_source_hash(repository, document) -> None:
    second = ReaderLibrary(repository).create_plain_text_document(
        title="A 100% literal underscore_ title",
        text="Different",
    )

    assert [item.id for item in repository.list_documents(query="literal underscore_").items] == [
        second.id
    ]
    assert repository.list_documents(query="missing").items == ()
    assert repository.find_document_by_source_hash(document.source_sha256).id == document.id
    assert repository.find_document_by_source_hash("0" * 64) is None


def test_document_updates_detect_optimistic_concurrency_conflicts(repository, document) -> None:
    repository.update_document(document.id, expected_row_version=1, title="First")

    with pytest.raises(ReaderConflictError) as error:
        repository.update_document(document.id, expected_row_version=1, title="Stale")

    assert error.value.expected == 1
    assert error.value.actual == 2


def test_replace_remaps_saved_and_external_cursors(repository, document) -> None:
    block = repository.list_blocks(document.id)[0]
    now = datetime.now(timezone.utc)
    position = repository.save_position(
        PlaybackPosition(
            document_id=document.id,
            cursor=_cursor(document, block, 12),
            updated_at=now,
        )
    )
    bookmark = repository.create_bookmark(
        Bookmark(
            id=str(uuid.uuid4()),
            document_id=document.id,
            cursor=_cursor(document, block, 12),
            label="After beta",
            created_at=now,
            updated_at=now,
        )
    )

    updated, edit = repository.replace_block_text(
        document.id,
        block.id,
        start_offset=6,
        end_offset=10,
        replacement_text="wonderful",
        expected_row_version=document.row_version,
    )

    assert edit.original_text == "beta"
    assert updated.content_revision == 2
    assert updated.row_version == 2
    assert repository.list_blocks(document.id)[0].text == "Alpha wonderful gamma."
    assert repository.get_position(document.id).cursor.character_offset == 17
    assert repository.get_position(document.id).row_version == position.row_version + 1
    stored_bookmark = repository.list_bookmarks(document.id)[0]
    assert stored_bookmark.cursor.character_offset == 17
    assert stored_bookmark.row_version == bookmark.row_version + 1
    assert repository.resolve_cursor(_cursor(document, block, 12)).character_offset == 17


def test_edit_append_undo_redo_are_atomic_and_persistent(repository, document) -> None:
    block = repository.list_blocks(document.id)[0]
    edited, _ = repository.replace_block_text(
        document.id,
        block.id,
        start_offset=6,
        end_offset=10,
        replacement_text="great",
        expected_row_version=document.row_version,
    )
    appended, append_edit = repository.append_text(
        document.id,
        "Copied forum selection.\nWith an intentional line.",
        expected_row_version=edited.row_version,
    )
    assert append_edit.replacement_text == "Copied forum selection.\nWith an intentional line."
    assert appended.content_revision == 3
    assert appended.row_version == 3
    assert appended.total_blocks == 3

    appended_block = repository.list_blocks(document.id)[-1]
    with connect_sqlite(repository.database_path) as connection:
        connection.execute(
            "UPDATE reader_document_edits SET metadata_json = ? WHERE id = ?",
            (
                json.dumps(
                    {
                        "section_id": appended_block.section_id,
                        "ordinal": appended_block.ordinal,
                        "kind": appended_block.kind.value,
                    }
                ),
                append_edit.id,
            ),
        )

    after_undo_append = repository.undo(document.id, expected_row_version=appended.row_version)
    assert after_undo_append.content_revision == 4
    assert after_undo_append.row_version == 4
    assert after_undo_append.total_blocks == 2
    assert repository.list_blocks(document.id)[-1].text == "Second paragraph."

    after_undo_edit = repository.undo(
        document.id,
        expected_row_version=after_undo_append.row_version,
    )
    assert after_undo_edit.content_revision == 5
    assert repository.list_blocks(document.id)[0].text == "Alpha beta gamma."

    after_redo_edit = repository.redo(
        document.id,
        expected_row_version=after_undo_edit.row_version,
    )
    assert after_redo_edit.content_revision == 6
    assert repository.list_blocks(document.id)[0].text == "Alpha great gamma."

    after_redo_append = repository.redo(
        document.id,
        expected_row_version=after_redo_edit.row_version,
    )
    assert after_redo_append.content_revision == 7
    assert repository.list_blocks(document.id)[-1].id == append_edit.block_id

    reopened = SqliteReaderRepository(repository.database_path)
    assert reopened.get_document(document.id).content_revision == 7
    assert reopened.list_blocks(document.id)[-1].text.startswith("Copied forum")


def test_multi_paragraph_append_is_one_undoable_action(repository, document) -> None:
    original_blocks = repository.list_blocks(document.id)
    predecessor = original_blocks[-1]
    appended, append_edit = repository.append_text(
        document.id,
        "First copied paragraph.\n\nSecond copied paragraph.\n\nThird copied paragraph.",
        expected_row_version=document.row_version,
    )
    appended_blocks = repository.list_blocks(document.id)[-3:]

    assert appended.total_blocks == document.total_blocks + 3
    assert [block.text for block in appended_blocks] == [
        "First copied paragraph.",
        "Second copied paragraph.",
        "Third copied paragraph.",
    ]
    assert append_edit.block_id == appended_blocks[0].id
    assert appended.total_characters == document.total_characters + sum(
        block.character_count for block in appended_blocks
    )

    now = datetime.now(timezone.utc)
    repository.save_position(
        PlaybackPosition(
            document_id=document.id,
            cursor=_cursor(appended, appended_blocks[1], 4),
            updated_at=now,
            completed=False,
        )
    )
    bookmark = repository.create_bookmark(
        Bookmark(
            id=str(uuid.uuid4()),
            document_id=document.id,
            cursor=_cursor(appended, appended_blocks[2], 5),
            label="Appended text",
            created_at=now,
            updated_at=now,
        )
    )

    undone = repository.undo(document.id, expected_row_version=appended.row_version)

    assert undone.total_blocks == document.total_blocks
    assert [block.id for block in repository.list_blocks(document.id)] == [
        block.id for block in original_blocks
    ]
    position = repository.get_position(document.id)
    assert position is not None
    assert position.cursor.block_id == predecessor.id
    assert position.cursor.character_offset == predecessor.character_count
    stored_bookmark = repository.get_bookmark(bookmark.id)
    assert stored_bookmark.cursor.block_id == predecessor.id
    assert stored_bookmark.cursor.character_offset == predecessor.character_count

    redone = repository.redo(document.id, expected_row_version=undone.row_version)

    assert redone.total_blocks == document.total_blocks + 3
    assert [block.id for block in repository.list_blocks(document.id)[-3:]] == [
        block.id for block in appended_blocks
    ]


def test_cross_block_delete_is_one_undoable_action(repository) -> None:
    document = ReaderLibrary(repository).create_plain_text_document(
        title="Delete selection",
        text=(
            "First keep and remove.\n\n"
            "Middle gone.\n\n"
            "Third remove and keep.\n\n"
            "Last untouched."
        ),
    )
    original_blocks = repository.list_blocks(document.id)
    start_offset = len("First keep and ")
    end_offset = len("Third remove ")
    now = datetime.now(timezone.utc)
    repository.save_position(
        PlaybackPosition(
            document_id=document.id,
            cursor=_cursor(document, original_blocks[2], end_offset + 3),
            updated_at=now,
            completed=False,
        )
    )
    middle_bookmark = repository.create_bookmark(
        Bookmark(
            id=str(uuid.uuid4()),
            document_id=document.id,
            cursor=_cursor(document, original_blocks[1], 4),
            label="Removed text",
            created_at=now,
            updated_at=now,
        )
    )
    later_bookmark = repository.create_bookmark(
        Bookmark(
            id=str(uuid.uuid4()),
            document_id=document.id,
            cursor=_cursor(document, original_blocks[3], 2),
            label="Later text",
            created_at=now,
            updated_at=now,
        )
    )
    old_suffix_cursor = _cursor(document, original_blocks[2], end_offset + 3)

    deleted, edit = repository.delete_block_range(
        document.id,
        original_blocks[0].id,
        original_blocks[2].id,
        start_offset=start_offset,
        end_offset=end_offset,
        expected_row_version=document.row_version,
    )

    current_blocks = repository.list_blocks(document.id)
    assert edit.operation_type.value == "replace"
    assert edit.metadata["range_delete"] is True
    assert edit.end_offset == start_offset
    assert edit.metadata["range_end_offset"] == end_offset
    assert deleted.total_blocks == 2
    assert [block.text for block in current_blocks] == [
        "First keep and and keep.",
        "Last untouched.",
    ]
    assert [block.ordinal for block in current_blocks] == [0, 1]
    position = repository.get_position(document.id)
    assert position is not None
    assert position.cursor.block_id == original_blocks[0].id
    assert position.cursor.character_offset == start_offset + 3
    assert repository.get_bookmark(middle_bookmark.id).cursor.character_offset == start_offset
    shifted_later = repository.get_bookmark(later_bookmark.id)
    assert shifted_later.cursor.block_id == original_blocks[3].id
    assert shifted_later.cursor.block_ordinal == 1
    resolved_suffix = repository.resolve_cursor(old_suffix_cursor)
    assert resolved_suffix.block_id == original_blocks[0].id
    assert resolved_suffix.character_offset == start_offset + 3

    undone = repository.undo(document.id, expected_row_version=deleted.row_version)

    restored_blocks = repository.list_blocks(document.id)
    assert undone.total_blocks == 4
    assert [block.id for block in restored_blocks] == [
        block.id for block in original_blocks
    ]
    assert [block.text for block in restored_blocks] == [
        block.text for block in original_blocks
    ]
    restored_position = repository.get_position(document.id)
    assert restored_position is not None
    assert restored_position.cursor.block_id == original_blocks[2].id
    assert restored_position.cursor.character_offset == end_offset + 3
    assert repository.get_bookmark(later_bookmark.id).cursor.block_ordinal == 3

    redone = repository.redo(document.id, expected_row_version=undone.row_version)

    assert redone.total_blocks == 2
    assert [block.text for block in repository.list_blocks(document.id)] == [
        "First keep and and keep.",
        "Last untouched.",
    ]


def test_new_edit_after_undo_discards_redo_branch(repository, document) -> None:
    block = repository.list_blocks(document.id)[0]
    edited, _ = repository.replace_block_text(
        document.id,
        block.id,
        start_offset=0,
        end_offset=5,
        replacement_text="First",
        expected_row_version=document.row_version,
    )
    undone = repository.undo(document.id, expected_row_version=edited.row_version)
    changed, _ = repository.replace_block_text(
        document.id,
        block.id,
        start_offset=0,
        end_offset=5,
        replacement_text="Other",
        expected_row_version=undone.row_version,
    )

    with pytest.raises(ReaderEditHistoryError):
        repository.redo(document.id, expected_row_version=changed.row_version)


def test_cursor_after_undo_returns_typed_stale_conflict(repository, document) -> None:
    block = repository.list_blocks(document.id)[0]
    old_cursor = _cursor(document, block, 12)
    edited, _ = repository.replace_block_text(
        document.id,
        block.id,
        start_offset=6,
        end_offset=10,
        replacement_text="wonderful",
        expected_row_version=document.row_version,
    )
    repository.undo(document.id, expected_row_version=edited.row_version)

    with pytest.raises(ReaderStaleCursorError):
        repository.resolve_cursor(old_cursor)


def test_edit_history_is_bounded_and_can_be_cleared(tmp_path: Path) -> None:
    repository = SqliteReaderRepository(
        tmp_path / "reader.db",
        max_edit_history_operations=2,
        max_edit_history_bytes=100,
    )
    document = ReaderLibrary(repository).create_plain_text_document(title="Test", text="abc")
    block = repository.list_blocks(document.id)[0]
    for replacement in ("A", "B", "C"):
        document, _ = repository.replace_block_text(
            document.id,
            block.id,
            start_offset=0,
            end_offset=1,
            replacement_text=replacement,
            expected_row_version=document.row_version,
        )

    repository.undo(document.id, expected_row_version=document.row_version)
    current = repository.get_document(document.id)
    repository.undo(document.id, expected_row_version=current.row_version)
    current = repository.get_document(document.id)
    with pytest.raises(ReaderEditHistoryError):
        repository.undo(document.id, expected_row_version=current.row_version)

    repository.clear_edit_history(document.id)
    current = repository.get_document(document.id)
    with pytest.raises(ReaderEditHistoryError):
        repository.redo(document.id, expected_row_version=current.row_version)


def test_positions_bookmarks_and_queue_are_durable(repository, document) -> None:
    second = ReaderLibrary(repository).create_plain_text_document(title="Second", text="Two")
    block = repository.list_blocks(document.id)[0]
    now = datetime.now(timezone.utc)
    position = repository.save_position(
        PlaybackPosition(
            document_id=document.id,
            cursor=_cursor(document, block, 3),
            updated_at=now,
            completed=False,
        )
    )
    bookmark = repository.create_bookmark(
        Bookmark(
            id=str(uuid.uuid4()),
            document_id=document.id,
            cursor=_cursor(document, block, 5),
            label="Useful",
            created_at=now,
            updated_at=now,
        )
    )
    first_item = QueueItem(
        id=str(uuid.uuid4()),
        document_id=document.id,
        ordinal=0,
        status=QueueStatus.QUEUED,
        added_at=now,
        updated_at=now,
    )
    second_item = QueueItem(
        id=str(uuid.uuid4()),
        document_id=second.id,
        ordinal=1,
        status=QueueStatus.QUEUED,
        added_at=now,
        updated_at=now,
    )
    repository.add_queue_item(first_item)
    repository.add_queue_item(second_item)
    reordered = repository.reorder_queue((second_item.id, first_item.id))

    reopened = SqliteReaderRepository(repository.database_path)
    assert reopened.get_position(document.id) == position
    assert reopened.list_bookmarks(document.id) == (bookmark,)
    assert [item.id for item in reordered] == [second_item.id, first_item.id]
    assert [item.id for item in reopened.list_queue()] == [second_item.id, first_item.id]


def test_position_retry_is_idempotent(repository, document) -> None:
    block = repository.list_blocks(document.id)[0]
    now = datetime.now(timezone.utc)
    requested = PlaybackPosition(
        document_id=document.id,
        cursor=_cursor(document, block, 4),
        updated_at=now,
    )

    first = repository.save_position(requested, expected_row_version=0)
    retried = repository.save_position(requested, expected_row_version=0)

    assert retried == first
    assert retried.row_version == 1


def test_bookmark_and_queue_mutations_use_row_versions(repository, document) -> None:
    second = ReaderLibrary(repository).create_plain_text_document(title="Second", text="Two")
    block = repository.list_blocks(document.id)[0]
    now = datetime.now(timezone.utc)
    bookmark = repository.create_bookmark(
        Bookmark(
            id=str(uuid.uuid4()),
            document_id=document.id,
            cursor=_cursor(document, block, 2),
            created_at=now,
            updated_at=now,
        )
    )
    updated_bookmark = repository.update_bookmark(
        bookmark.id,
        expected_row_version=bookmark.row_version,
        label="Renamed",
        note="Remember this",
    )
    assert updated_bookmark.label == "Renamed"
    assert updated_bookmark.row_version == 2
    with pytest.raises(ReaderConflictError):
        repository.delete_bookmark(bookmark.id, expected_row_version=1)
    repository.delete_bookmark(bookmark.id, expected_row_version=2)
    assert repository.list_bookmarks(document.id) == ()

    first_item = QueueItem(
        id=str(uuid.uuid4()),
        document_id=document.id,
        ordinal=0,
        status=QueueStatus.QUEUED,
        added_at=now,
        updated_at=now,
    )
    second_item = QueueItem(
        id=str(uuid.uuid4()),
        document_id=second.id,
        ordinal=1,
        status=QueueStatus.QUEUED,
        added_at=now,
        updated_at=now,
    )
    repository.add_queue_item(first_item)
    repository.add_queue_item(second_item)
    playing = repository.update_queue_item(
        first_item.id,
        expected_row_version=1,
        status=QueueStatus.PLAYING,
    )
    with pytest.raises(ReaderValidationError, match="only one"):
        repository.update_queue_item(
            second_item.id,
            expected_row_version=1,
            status=QueueStatus.PLAYING,
        )
    repository.remove_queue_item(first_item.id, expected_row_version=playing.row_version)
    remaining = repository.list_queue()
    assert len(remaining) == 1
    assert remaining[0].id == second_item.id
    assert remaining[0].ordinal == 0
    assert remaining[0].row_version == 2


def test_wal_allows_reader_while_an_uncommitted_writer_exists(repository, document) -> None:
    reader = connect_sqlite(repository.database_path)
    writer = connect_sqlite(repository.database_path)
    try:
        reader.execute("BEGIN")
        assert reader.execute("SELECT COUNT(*) FROM reader_documents").fetchone()[0] == 1
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "UPDATE reader_documents SET title = 'Uncommitted' WHERE id = ?",
            (document.id,),
        )
        assert reader.execute("SELECT title FROM reader_documents").fetchone()[0] == "Test document"
        writer.commit()
        reader.commit()
        assert reader.execute("SELECT title FROM reader_documents").fetchone()[0] == "Uncommitted"
    finally:
        if reader.in_transaction:
            reader.rollback()
        if writer.in_transaction:
            writer.rollback()
        reader.close()
        writer.close()


def test_backup_is_consistent_and_does_not_overwrite_by_default(
    repository,
    document,
    tmp_path,
) -> None:
    backup = repository.backup_to(tmp_path / "backups" / "reader.db")
    restored = SqliteReaderRepository(backup)

    assert restored.get_document(document.id).title == document.title
    assert restored.report().integrity_ok is True
    with pytest.raises(FileExistsError):
        repository.backup_to(backup)
    assert repository.backup_to(backup, overwrite=True) == backup


def test_disabled_repository_initialization_has_no_filesystem_side_effect(tmp_path: Path) -> None:
    database = tmp_path / "missing" / "reader.db"

    result = initialize_reader_repository(enabled=False, database_path=database)

    assert result is None
    assert not database.parent.exists()


def test_ten_thousand_document_pages_use_keyset_pagination(tmp_path: Path) -> None:
    repository = SqliteReaderRepository(tmp_path / "reader.db")
    populate_synthetic_documents(repository.database_path, count=10_000)

    first = repository.list_documents(limit=73)
    second = repository.list_documents(limit=73, cursor=first.next_cursor)

    assert len(first.items) == 73
    assert len(second.items) == 73
    assert first.items[-1].id != second.items[0].id
    assert first.next_cursor is not None
    assert second.next_cursor is not None
    assert not set(item.id for item in first.items) & set(item.id for item in second.items)

    with connect_sqlite(repository.database_path) as connection:
        plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT * FROM reader_documents
            WHERE deleted_at IS NULL AND state = ?
              AND (updated_at < ? OR (updated_at = ? AND id < ?))
            ORDER BY updated_at DESC, id DESC LIMIT ?
            """,
            ("inbox", "9999", "9999", "z", 50),
        ).fetchall()
    assert any("INDEX" in str(row[3]).upper() for row in plan)


@pytest.mark.parametrize("cursor", ["%%%", "bm90LWpzb24", "WzFd"])
def test_document_listing_rejects_invalid_page_cursors(repository, cursor: str) -> None:
    with pytest.raises(ReaderValidationError, match="cursor is invalid"):
        repository.list_documents(cursor=cursor)


def test_invalid_append_and_soft_deleted_queue_are_rejected(repository, document) -> None:
    with pytest.raises(ReaderValidationError, match="must not be empty"):
        repository.append_text(document.id, " ", expected_row_version=document.row_version)

    deleted = repository.soft_delete_document(
        document.id,
        expected_row_version=document.row_version,
    )
    now = datetime.now(timezone.utc)
    with pytest.raises(ReaderValidationError, match="cannot be queued"):
        repository.add_queue_item(
            QueueItem(
                id=str(uuid.uuid4()),
                document_id=deleted.id,
                ordinal=0,
                status=QueueStatus.QUEUED,
                added_at=now,
                updated_at=now,
            )
        )


@pytest.mark.parametrize("enable_fts", [True, False])
def test_document_search_includes_content_with_fts_fallback(
    tmp_path: Path,
    enable_fts: bool,
) -> None:
    repository = SqliteReaderRepository(tmp_path / "reader.db", enable_fts=enable_fts)
    library = ReaderLibrary(repository)
    document = library.create_plain_text_document(
        title="Ordinary title",
        text="A paragraph containing ultramarine and nothing in the title.",
    )

    assert repository.list_documents(query="ultramarine").items == (document,)
    assert repository.search_available is enable_fts

    block = repository.list_blocks(document.id)[0]
    updated, _ = repository.replace_block_text(
        document.id,
        block.id,
        start_offset=23,
        end_offset=34,
        replacement_text="vermilion",
        expected_row_version=document.row_version,
    )
    assert repository.list_documents(query="ultramarine").items == ()
    assert repository.list_documents(query="vermilion").items == (updated,)


def test_queue_activation_and_advance_are_atomic_and_durable(repository, document) -> None:
    second = ReaderLibrary(repository).create_plain_text_document(title="Second", text="Two")
    now = datetime.now(timezone.utc)
    first_item = repository.add_queue_item(
        QueueItem(
            id=str(uuid.uuid4()),
            document_id=document.id,
            ordinal=0,
            status=QueueStatus.QUEUED,
            added_at=now,
            updated_at=now,
        )
    )
    second_item = repository.add_queue_item(
        QueueItem(
            id=str(uuid.uuid4()),
            document_id=second.id,
            ordinal=1,
            status=QueueStatus.QUEUED,
            added_at=now,
            updated_at=now,
        )
    )

    assert repository.activate_queue_item(first_item.id).status is QueueStatus.PLAYING
    advanced = repository.advance_queue(document.id)
    assert advanced is not None
    assert advanced.id == second_item.id
    assert sum(item.status is QueueStatus.PLAYING for item in repository.list_queue()) == 1

    reopened = SqliteReaderRepository(repository.database_path)
    persisted = reopened.list_queue()
    assert [item.document_id for item in persisted] == [document.id, second.id]
    assert [item.status for item in persisted] == [QueueStatus.COMPLETED, QueueStatus.PLAYING]


def test_desktop_open_request_is_idempotent_persistent_and_acknowledged(
    repository,
    document,
) -> None:
    request = ReaderDesktopOpenRequest(
        id=str(uuid.uuid4()),
        document_id=document.id,
        created_at=datetime.now(timezone.utc),
    )

    created = repository.request_desktop_open(request)
    duplicate = repository.request_desktop_open(
        replace(request, id=str(uuid.uuid4()))
    )
    reopened = SqliteReaderRepository(repository.database_path)

    assert duplicate == created
    assert reopened.peek_desktop_open_request() == created
    reopened.acknowledge_desktop_open_request(created.id)
    assert reopened.peek_desktop_open_request() is None


def test_export_jobs_persist_recover_and_cancel(repository, document) -> None:
    now = datetime.now(timezone.utc)
    job = repository.create_export_job(
        ReaderExportJob(
            id=str(uuid.uuid4()),
            status=ExportStatus.QUEUED,
            document_ids=(document.id,),
            audio_format=ExportAudioFormat.MP3,
            total_documents=1,
            output_basename="sample",
            created_at=now,
            updated_at=now,
        )
    )
    running = repository.claim_export_job(job.id)
    assert running.status is ExportStatus.RUNNING
    assert running.audio_format is ExportAudioFormat.MP3
    assert running.progress_phase is ExportPhase.PREPARING
    assert running.progress_percent == 0

    running = repository.update_export_progress(
        job.id,
        completed_documents=0,
        current_document_id=document.id,
        output_files=(),
        progress_phase=ExportPhase.SYNTHESIZING,
        progress_percent=37,
    )
    assert running.progress_phase is ExportPhase.SYNTHESIZING
    assert running.progress_percent == 37

    with pytest.raises(ReaderValidationError, match="monotonic"):
        repository.update_export_progress(
            job.id,
            completed_documents=0,
            current_document_id=document.id,
            output_files=(),
            progress_phase=ExportPhase.SYNTHESIZING,
            progress_percent=36,
        )

    reopened = SqliteReaderRepository(repository.database_path)
    recovered = reopened.recover_export_jobs()
    assert [item.id for item in recovered] == [job.id]
    assert reopened.get_export_job(job.id).status is ExportStatus.QUEUED
    assert reopened.get_export_job(job.id).audio_format is ExportAudioFormat.MP3
    assert reopened.get_export_job(job.id).progress_phase is ExportPhase.QUEUED
    assert reopened.get_export_job(job.id).progress_percent == 0

    with pytest.raises(ReaderValidationError, match="cancelled before deletion"):
        reopened.delete_export_job(job.id)

    cancelled = reopened.request_export_cancel(job.id)
    assert cancelled.status is ExportStatus.CANCELLED
    assert cancelled.progress_phase is ExportPhase.CANCELLED
    assert cancelled.cancel_requested is True
    assert cancelled.completed_at is not None
    reopened.delete_export_job(job.id)
    with pytest.raises(ReaderNotFoundError):
        reopened.get_export_job(job.id)
