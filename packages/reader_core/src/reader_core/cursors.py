from __future__ import annotations

from dataclasses import replace

from .errors import ReaderValidationError
from .models import ReaderCursor


def remap_text_offset(
    offset: int,
    *,
    start_offset: int,
    end_offset: int,
    replacement_length: int,
) -> int:
    """Map a source offset through one replace operation."""
    if min(offset, start_offset, end_offset, replacement_length) < 0:
        raise ReaderValidationError("edit offsets must not be negative")
    if end_offset < start_offset:
        raise ReaderValidationError("edit end_offset must not precede start_offset")

    if start_offset == end_offset:
        return offset if offset < start_offset else offset + replacement_length
    if offset <= start_offset:
        return offset
    if offset >= end_offset:
        return offset + replacement_length - (end_offset - start_offset)
    relative = offset - start_offset
    return start_offset + min(relative, replacement_length)


def remap_cursor_for_edit(
    cursor: ReaderCursor,
    *,
    edited_block_id: str,
    start_offset: int,
    end_offset: int,
    replacement_length: int,
    new_content_revision: int,
) -> ReaderCursor:
    offset = cursor.character_offset
    if cursor.block_id == edited_block_id:
        offset = remap_text_offset(
            offset,
            start_offset=start_offset,
            end_offset=end_offset,
            replacement_length=replacement_length,
        )
    return replace(
        cursor,
        character_offset=offset,
        content_revision=new_content_revision,
        segment_index=None,
    )
