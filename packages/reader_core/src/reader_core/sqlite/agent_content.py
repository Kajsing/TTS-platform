"""Folder-scoped, revision-pinned chapter text and literal text search.

Mix this into the scoped agent repository. All methods authorize through its
existing ``_scope`` transaction and the existing ``read`` permission. Chapter IDs
are current structural marker IDs, never durable delivery receipt IDs. Text and
search offsets count Unicode code points in the canonical article text (blocks
joined by two newlines). Chapter pages retain boundary separators, so concatenated
chapter text equals the complete article text exactly.

Search is case-sensitive literal search, including across paragraph boundaries.
Its continuation is a candidate-start text offset, not a result count. Each call
scans at most 100,000 candidate positions plus query lookahead, and can return an
empty page with a continuation. At most 100 results are returned. Scalar block
inspection is limited to articles with 100,000 blocks / 32 million code points;
source hydration uses SQL substr and never loads an entire oversized block.
"""

from __future__ import annotations

import json

from ..agent_access import MAX_AGENT_PAGE, AgentConflictError, bounded_text
from ..chapter_index import ChapterAnchor
from ..chapters import CHAPTER_KEY, read_markers
from ..errors import ReaderConflictError, ReaderValidationError

MAX_CONTENT_BLOCKS = 100_000
MAX_CONTENT_CHARACTERS = 32_000_000
MAX_MARKER_JSON_CHARACTERS = 1_048_576
MAX_SEARCH_QUERY = 200
MAX_SEARCH_SCAN = 100_000


class AgentContentMixin:
    def list_content_chapters(
        self,
        credential: str,
        document_id: str,
        *,
        expected_row_version: int,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Discover current structural chapter IDs, independently of receipts."""
        _page(offset, limit, 100)
        with self._scope(credential, "read", document_id) as (_bound, connection, _):
            document = _document(connection, document_id, expected_row_version)
            anchors = _anchors(connection, document_id)
            if offset > len(anchors):
                raise ReaderValidationError("Chapter offset exceeds the current chapter count")
            end = min(len(anchors), offset + limit)
            return {
                "article": _article(document),
                "items": [
                    {
                        "id": anchor.id,
                        "title": anchor.title,
                        "block_ordinal": anchor.block_ordinal,
                        "codepoint_offset": anchor.codepoint_offset,
                    }
                    for anchor in anchors[offset:end]
                ],
                "offset": offset,
                "next_offset": end if end < len(anchors) else None,
                "chapter_count": len(anchors),
            }

    def read_chapter(
        self,
        credential: str,
        document_id: str,
        chapter_id: str,
        *,
        expected_row_version: int,
        offset: int = 0,
        limit: int = MAX_AGENT_PAGE,
    ) -> dict:
        """Read a current chapter page, including canonical boundary separators."""
        bounded_text(chapter_id, "chapter_id", 100)
        _page(offset, limit, MAX_AGENT_PAGE)
        with self._scope(credential, "read", document_id) as (_bound, connection, _):
            document = _document(connection, document_id, expected_row_version)
            anchors = _anchors(connection, document_id)
            target = next(
                (index for index, item in enumerate(anchors) if item.id == chapter_id), None
            )
            if target is None:
                raise AgentConflictError("Current chapter is unavailable; list chapters again")
            anchor = anchors[target]
            start = _anchor_position(connection, document_id, anchor)
            end = (
                _anchor_position(connection, document_id, anchors[target + 1])
                if target + 1 < len(anchors)
                else _text_length(document)
            )
            length = end - start
            if offset > length:
                raise ReaderValidationError("Chapter offset exceeds current chapter text length")
            page_end = min(length, offset + limit)
            return {
                "article": _article(document),
                "chapter": {"id": anchor.id, "title": anchor.title},
                "text": _read_range(connection, document_id, start + offset, start + page_end),
                "offset": offset,
                "next_offset": page_end if page_end < length else None,
                "text_length": length,
            }

    def search_article(
        self,
        credential: str,
        document_id: str,
        *,
        query: str,
        expected_row_version: int,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Find overlapping literal matches using a bounded text scan per call."""
        bounded_text(query, "query", MAX_SEARCH_QUERY)
        _page(offset, limit, 100)
        with self._scope(credential, "read", document_id) as (_bound, connection, _):
            document = _document(connection, document_id, expected_row_version)
            length = _text_length(document)
            if offset > length:
                raise ReaderValidationError("Search offset exceeds current article text length")
            scan_end = min(length, offset + MAX_SEARCH_SCAN)
            text = _read_range(
                connection, document_id, offset, min(length, scan_end + len(query) - 1)
            )
            items = []
            candidate = 0
            next_offset = scan_end if scan_end < length else None
            while len(items) < limit:
                found = text.find(query, candidate)
                if found < 0 or offset + found >= scan_end:
                    break
                start = offset + found
                items.append({"offset": start, "end_offset": start + len(query), "text": query})
                candidate = found + 1
            if len(items) == limit:
                following = offset + candidate
                next_offset = following if following < length else None
            return {
                "article": _article(document),
                "query": query,
                "match_mode": "literal_case_sensitive",
                "items": items,
                "offset": offset,
                "next_offset": next_offset,
                "text_length": length,
                "scanned_characters": scan_end - offset,
            }


def _page(offset: int, limit: int, maximum: int) -> None:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= maximum:
        raise ReaderValidationError("Invalid content page offset or size")


def _text_length(document) -> int:
    return document["total_characters"] + max(0, document["total_blocks"] - 1) * 2


def _document(connection, document_id: str, expected: int):
    if type(expected) is not int or expected < 1:
        raise ReaderValidationError("Content reads require a positive expected row version")
    # A read does not need importer metadata, local paths or a full document object.
    document = connection.execute(
        "SELECT id, title, folder_id, row_version, content_revision, state, "
        "total_characters, total_blocks, updated_at FROM reader_documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    if document["row_version"] != expected:
        raise ReaderConflictError(document_id, expected=expected, actual=document["row_version"])
    if (
        document["total_blocks"] > MAX_CONTENT_BLOCKS
        or _text_length(document) > MAX_CONTENT_CHARACTERS
    ):
        raise ReaderValidationError("Article exceeds bounded chapter/search source limits")
    return document


def _article(document) -> dict:
    return {
        key: document[key]
        for key in (
            "id",
            "title",
            "folder_id",
            "row_version",
            "content_revision",
            "state",
            "total_characters",
            "updated_at",
        )
    }


def _anchors(connection, document_id: str) -> tuple[ChapterAnchor, ...]:
    """Validate scalar anchors inside the already-authorized transaction."""
    size = connection.execute(
        "SELECT length(metadata_json) FROM reader_documents WHERE id = ?", (document_id,)
    ).fetchone()[0]
    if size > MAX_MARKER_JSON_CHARACTERS:
        raise AgentConflictError("Current chapter metadata exceeds its supported bound")
    raw = connection.execute(
        "SELECT metadata_json FROM reader_documents WHERE id = ?", (document_id,)
    ).fetchone()[0]
    try:
        metadata = json.loads(raw)
        if not isinstance(metadata, dict) or (
            CHAPTER_KEY in metadata and metadata[CHAPTER_KEY] is None
        ):
            raise ValueError()
        first = connection.execute(
            "SELECT id, ordinal, character_count FROM reader_blocks "
            "WHERE document_id = ? ORDER BY ordinal LIMIT 1",
            (document_id,),
        ).fetchone()
        if first is None:
            if CHAPTER_KEY in metadata:
                raise ValueError()
            return ()
        markers = read_markers(metadata, first["id"])
        for marker in markers:
            bounded_text(marker.id, "chapter_id", 100)
            bounded_text(marker.block_id, "chapter block id", 100)
            bounded_text(marker.title, "chapter title", 300)
        locations = {first["id"]: first}
        wanted = tuple(dict.fromkeys(marker.block_id for marker in markers))
        for start in range(0, len(wanted), 500):
            batch = wanted[start : start + 500]
            rows = connection.execute(
                "SELECT id, ordinal, character_count FROM reader_blocks "
                "INDEXED BY sqlite_autoindex_reader_blocks_1 "
                f"WHERE id IN ({','.join('?' for _ in batch)}) AND document_id = ?",
                (*batch, document_id),
            )
            locations.update((row["id"], row) for row in rows)
        result = []
        previous = None
        for marker in markers:
            row = locations.get(marker.block_id)
            if row is None or marker.codepoint_offset > row["character_count"]:
                raise ValueError()
            position = (row["ordinal"], marker.codepoint_offset)
            if previous is None:
                if position != (first["ordinal"], 0):
                    raise ValueError()
            elif position <= previous:
                raise ValueError()
            previous = position
            result.append(ChapterAnchor(marker.id, marker.title, marker.block_id, *position))
        return tuple(result)
    except (ValueError, TypeError, RecursionError, ReaderValidationError) as error:
        raise AgentConflictError("Current chapter structure is invalid or changed") from error


def _anchor_position(connection, document_id: str, anchor: ChapterAnchor) -> int:
    preceding = connection.execute(
        "SELECT COALESCE(SUM(character_count + 2), 0) FROM reader_blocks "
        "WHERE document_id = ? AND ordinal < ?",
        (document_id, anchor.block_ordinal),
    ).fetchone()[0]
    return preceding + anchor.codepoint_offset


def _read_range(connection, document_id: str, start: int, end: int) -> str:
    """Inspect bounded scalar rows; hydrate only intersecting source substrings."""
    if start == end:
        return ""
    result = []
    position = 0
    for index, row in enumerate(
        connection.execute(
            "SELECT id, character_count FROM reader_blocks WHERE document_id = ? ORDER BY ordinal",
            (document_id,),
        )
    ):
        if index >= MAX_CONTENT_BLOCKS:
            raise ReaderValidationError("Article exceeds bounded content block limit")
        if index:
            separator_end = position + 2
            if start < separator_end and end > position:
                result.append("\n\n"[max(0, start - position) : min(2, end - position)])
            position = separator_end
        block_end = position + row["character_count"]
        if start < block_end and end > position:
            begin = max(0, start - position)
            size = min(block_end, end) - position - begin
            result.append(
                connection.execute(
                    "SELECT substr(text, ?, ?) FROM reader_blocks WHERE id = ? AND document_id = ?",
                    (begin + 1, size, row["id"], document_id),
                ).fetchone()[0]
            )
        position = block_end
        if position >= end:
            break
    text = "".join(result)
    if len(text) != end - start:
        raise AgentConflictError("Current article source lengths are inconsistent")
    return text
