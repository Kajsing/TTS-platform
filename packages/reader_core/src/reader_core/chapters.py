"""Chapter boundaries over canonical text, independent of import sections.

The versioned metadata uses Unicode code-point offsets, not UTF-16. History
stores before/after marker snapshots alongside each normal content operation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Sequence

from .errors import ReaderValidationError

CHAPTER_KEY = "chapter_markers_v1"
MAX_CHAPTERS = 1024


@dataclass(frozen=True)
class ChapterMarker:
    id: str
    title: str
    block_id: str
    codepoint_offset: int


def read_markers(metadata: Mapping[str, Any], first_block_id: str) -> list[ChapterMarker]:
    raw = metadata.get(CHAPTER_KEY)
    if raw is None:
        return [ChapterMarker("root", "Chapter 1", first_block_id, 0)]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CHAPTERS:
        raise ReaderValidationError("chapter metadata is invalid")
    result = []
    for item in raw:
        if not isinstance(item, dict):
            raise ReaderValidationError("chapter marker must be an object")
        marker = ChapterMarker(
            id=item.get("id"),
            title=item.get("title"),
            block_id=item.get("block_id"),
            codepoint_offset=item.get("codepoint_offset"),
        )
        if (
            not isinstance(marker.id, str)
            or not 1 <= len(marker.id) <= 100
            or not isinstance(marker.block_id, str)
            or not marker.block_id
            or not isinstance(marker.title, str)
            or not 1 <= len(marker.title) <= 300
            or type(marker.codepoint_offset) is not int
            or marker.codepoint_offset < 0
        ):
            raise ReaderValidationError("chapter marker is invalid")
        result.append(marker)
    if len({marker.id for marker in result}) != len(result):
        raise ReaderValidationError("chapter IDs must be unique")
    return result


def marker_data(markers: Sequence[ChapterMarker]) -> list[dict[str, Any]]:
    return [asdict(marker) for marker in markers]


def normalize_markers(
    markers: Sequence[ChapterMarker],
    blocks: Sequence[tuple[str, int, int]],
) -> list[ChapterMarker]:
    """Keep the implicit first chapter; collapse deleted/empty boundaries."""
    if not blocks:
        return []
    locations = {block_id: (ordinal, length) for block_id, ordinal, length in blocks}
    first = replace(markers[0], block_id=blocks[0][0], codepoint_offset=0)
    candidates = [first] + [marker for marker in markers[1:] if marker.block_id in locations]
    candidates = [
        replace(
            marker, codepoint_offset=min(marker.codepoint_offset, locations[marker.block_id][1])
        )
        for marker in candidates
    ]
    candidates.sort(key=lambda marker: (locations[marker.block_id][0], marker.codepoint_offset))
    result: list[ChapterMarker] = []
    seen: set[tuple[str, int]] = set()
    for marker in candidates:
        anchor = (marker.block_id, marker.codepoint_offset)
        if anchor in seen or (result and anchor == (blocks[-1][0], blocks[-1][2])):
            continue
        seen.add(anchor)
        result.append(marker)
    if len(result) > MAX_CHAPTERS:
        raise ReaderValidationError("an article may contain at most 1024 chapters")
    return result


def map_replacement(
    marker: ChapterMarker, block_id: str, start: int, end: int, length: int
) -> ChapterMarker:
    offset = marker.codepoint_offset
    if marker.block_id != block_id or offset <= start:
        return marker
    return replace(
        marker, codepoint_offset=start + length if offset < end else offset + length - (end - start)
    )
