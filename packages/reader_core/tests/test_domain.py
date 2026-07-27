from __future__ import annotations

import pytest
from reader_core import (
    BlockKind,
    ReaderCursor,
    ReaderValidationError,
    build_plain_text_structure,
    remap_cursor_for_edit,
    remap_text_offset,
)

DOCUMENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BLOCK_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_plain_text_structure_preserves_paragraph_order() -> None:
    sections, blocks = build_plain_text_structure(
        document_id=DOCUMENT_ID,
        title="Heading",
        text="Short heading\r\n\r\nFirst paragraph.\n\nSecond paragraph.",
    )

    assert len(sections) == 1
    assert sections[0].heading == "Heading"
    assert [block.ordinal for block in blocks] == [0, 1, 2]
    assert [block.text for block in blocks] == [
        "Short heading",
        "First paragraph.",
        "Second paragraph.",
    ]
    assert blocks[0].kind is BlockKind.HEADING
    assert all(block.document_id == DOCUMENT_ID for block in blocks)


def test_plain_text_structure_rejects_empty_text() -> None:
    with pytest.raises(ReaderValidationError, match="must not be empty"):
        build_plain_text_structure(document_id=DOCUMENT_ID, title="Title", text=" \n ")


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(0, 0), (5, 5), (6, 6), (8, 8), (10, 11), (14, 15)],
)
def test_text_offsets_remap_deterministically(offset: int, expected: int) -> None:
    assert (
        remap_text_offset(
            offset,
            start_offset=6,
            end_offset=10,
            replacement_length=5,
        )
        == expected
    )


def test_cursor_remap_clears_generated_segment_hint() -> None:
    cursor = ReaderCursor(
        document_id=DOCUMENT_ID,
        block_id=BLOCK_ID,
        block_ordinal=0,
        character_offset=12,
        content_revision=1,
        segment_index=3,
    )

    remapped = remap_cursor_for_edit(
        cursor,
        edited_block_id=BLOCK_ID,
        start_offset=6,
        end_offset=10,
        replacement_length=9,
        new_content_revision=2,
    )

    assert remapped.character_offset == 17
    assert remapped.content_revision == 2
    assert remapped.segment_index is None
