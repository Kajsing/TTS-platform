from dataclasses import replace

import pytest
from reader_core import (
    ReaderConflictError,
    ReaderCursor,
    ReaderEditHistoryError,
    ReaderLibrary,
    ReaderValidationError,
    SqliteReaderRepository,
)
from reader_core.chapters import CHAPTER_KEY


def markers(document):
    return document.metadata[CHAPTER_KEY]


def test_chapter_snapshots_count_toward_bounded_contiguous_history(tmp_path):
    repository = SqliteReaderRepository(tmp_path / "bounded.db", max_edit_history_bytes=700)
    document = ReaderLibrary(repository).create_plain_text_document(title="Bounded", text="abcdef")
    block = repository.list_blocks(document.id)[0]
    updated, _ = repository.replace_block_text(
        document.id,
        block.id,
        start_offset=0,
        end_offset=1,
        replacement_text="A",
        expected_row_version=document.row_version,
    )
    updated = repository.edit_chapter(
        document.id,
        expected_row_version=updated.row_version,
        action="rename",
        chapter_id="root",
        title="界" * 300,
    )
    # A large newest snapshot must not expose an older non-contiguous Undo.
    with pytest.raises(ReaderEditHistoryError):
        repository.undo(document.id, expected_row_version=updated.row_version)
    assert repository.get_document_bundle(document.id).blocks[0].text == "Abcdef"
    assert markers(repository.get_document(document.id))[0]["title"] == "界" * 300


@pytest.mark.parametrize("original_offset,insert_at,expected", [(6, 10, 6), (6, 2, 11), (6, 6, 6)])
def test_whole_paragraph_save_preserves_unchanged_chapter_anchors(
    repository,
    document,
    original_offset,
    insert_at,
    expected,
):
    block = repository.list_blocks(document.id)[0]
    document = repository.edit_chapter(
        document.id,
        expected_row_version=document.row_version,
        action="add",
        block_id=block.id,
        codepoint_offset=original_offset,
    )
    text = block.text[:insert_at] + "EDIT " + block.text[insert_at:]
    updated, _ = repository.replace_block_text(
        document.id,
        block.id,
        start_offset=0,
        end_offset=len(block.text),
        replacement_text=text,
        expected_row_version=document.row_version,
    )
    assert markers(updated)[1]["codepoint_offset"] == expected
    undone = repository.undo(document.id, expected_row_version=updated.row_version)
    assert markers(undone) == markers(document)


def test_manual_boundary_rename_merge_and_undo_preserve_text_and_ids(repository, document):
    before = repository.get_document_bundle(document.id)
    block = before.blocks[0]
    original_cursor = ReaderCursor(document.id, block.id, 0, 12, document.content_revision)
    updated = repository.edit_chapter(
        document.id,
        expected_row_version=document.row_version,
        action="add",
        block_id=block.id,
        codepoint_offset=6,
        title="Second",
    )
    chapter = markers(updated)[1]
    assert chapter["codepoint_offset"] == 6
    assert repository.get_document_bundle(document.id).blocks == before.blocks
    assert repository.resolve_cursor(original_cursor) == replace(
        original_cursor, content_revision=updated.content_revision
    )
    renamed = repository.edit_chapter(
        document.id,
        expected_row_version=updated.row_version,
        action="rename",
        chapter_id=chapter["id"],
        title="Renamed",
    )
    merged = repository.edit_chapter(
        document.id,
        expected_row_version=renamed.row_version,
        action="merge",
        chapter_id=chapter["id"],
    )
    assert len(markers(merged)) == 1
    undo = repository.undo(document.id, expected_row_version=merged.row_version)
    assert markers(undo)[1]["title"] == "Renamed"
    undo = repository.undo(document.id, expected_row_version=undo.row_version)
    assert markers(undo)[1] == chapter
    undo = repository.undo(document.id, expected_row_version=undo.row_version)
    assert len(markers(undo)) == 1
    redo = repository.redo(document.id, expected_row_version=undo.row_version)
    assert markers(redo)[1] == chapter
    assert [b.text for b in repository.get_document_bundle(document.id).blocks] == [
        b.text for b in before.blocks
    ]


def test_append_boundary_is_one_atomic_undo_and_redo_with_unchanged_sections(repository, document):
    before = repository.get_document_bundle(document.id)
    appended, _ = repository.append_text(
        document.id,
        "Chapter two\n\nMore text",
        expected_row_version=document.row_version,
        new_chapter=True,
    )
    chapter = markers(appended)[1]
    assert len(markers(appended)) == 2
    assert repository.get_document_bundle(document.id).sections == before.sections
    undone = repository.undo(document.id, expected_row_version=appended.row_version)
    assert len(markers(undone)) == 1
    assert repository.get_document_bundle(document.id).blocks == before.blocks
    redone = repository.redo(document.id, expected_row_version=undone.row_version)
    assert markers(redone)[1] == chapter
    continued, _ = repository.append_text(
        document.id, "Continuation", expected_row_version=redone.row_version
    )
    assert markers(continued) == markers(redone)


def test_replacement_maps_codepoints_and_undo_restores_exact_boundary(repository):
    document = ReaderLibrary(repository).create_plain_text_document(
        title="Unicode", text="A😀 B😀 C"
    )
    block = repository.get_document_bundle(document.id).blocks[0]
    document = repository.edit_chapter(
        document.id,
        expected_row_version=document.row_version,
        action="add",
        block_id=block.id,
        codepoint_offset=5,
    )
    old_markers = markers(document)
    updated, _ = repository.replace_block_text(
        document.id,
        block.id,
        start_offset=1,
        end_offset=2,
        replacement_text="hello",
        expected_row_version=document.row_version,
    )
    assert markers(updated)[1]["codepoint_offset"] == 9
    restored = repository.undo(document.id, expected_row_version=updated.row_version)
    assert markers(restored) == old_markers
    redone = repository.redo(document.id, expected_row_version=restored.row_version)
    assert markers(redone)[1]["codepoint_offset"] == 9


def test_cross_chapter_range_deletion_collapses_empty_boundaries_and_undo_restores_them(repository):
    document = ReaderLibrary(repository).create_plain_text_document(
        title="Ranges", text="First\n\nSecond\n\nThird\n\nFourth"
    )
    blocks = repository.get_document_bundle(document.id).blocks
    for block in blocks[1:]:
        document = repository.edit_chapter(
            document.id,
            expected_row_version=document.row_version,
            action="add",
            block_id=block.id,
            codepoint_offset=0,
        )
    original = markers(document)
    deleted, _ = repository.delete_block_range(
        document.id,
        blocks[0].id,
        blocks[2].id,
        start_offset=2,
        end_offset=2,
        expected_row_version=document.row_version,
    )
    assert len(markers(deleted)) == 3
    assert markers(deleted)[1]["block_id"] == blocks[0].id
    restored = repository.undo(document.id, expected_row_version=deleted.row_version)
    assert markers(restored) == original
    redone = repository.redo(document.id, expected_row_version=restored.row_version)
    assert markers(redone) == markers(deleted)


@pytest.mark.parametrize(
    "action,offset", [("add", -1), ("add", 500), ("add", 0), ("merge", 0), ("unknown", 0)]
)
def test_invalid_mutations_are_atomic(repository, document, action, offset):
    before = repository.get_document_bundle(document.id)
    with pytest.raises(ReaderValidationError):
        repository.edit_chapter(
            document.id,
            expected_row_version=document.row_version,
            action=action,
            block_id=before.blocks[0].id,
            codepoint_offset=offset,
            chapter_id="root",
        )
    assert repository.get_document_bundle(document.id) == before


def test_conflicting_version_does_not_change_chapters(repository, document):
    with pytest.raises(ReaderConflictError):
        repository.edit_chapter(
            document.id,
            expected_row_version=document.row_version + 1,
            action="rename",
            chapter_id="root",
            title="Changed",
        )
    assert CHAPTER_KEY not in repository.get_document_bundle(document.id).document.metadata
