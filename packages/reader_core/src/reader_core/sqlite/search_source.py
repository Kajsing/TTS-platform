"""Bounded, single-snapshot source preparation for Reader search infrastructure."""

from __future__ import annotations

import sqlite3
import time
from bisect import bisect_left
from dataclasses import dataclass
from typing import Callable

from ..errors import ReaderError

MAX_SEARCH_UTF16 = 32_000_000
MAX_SEARCH_BLOCKS = 100_000
SEPARATOR = "\r\n\r\n"


class SearchSourceLimitError(ReaderError):
    pass


class SearchSourceChangedError(ReaderError):
    pass


class SearchSourceCancelledError(ReaderError):
    pass


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


@dataclass(frozen=True, slots=True)
class SearchSourceBlock:
    id: str
    ordinal: int
    start: int
    end: int
    utf16_start: int
    utf16_end: int


@dataclass(frozen=True, slots=True)
class SearchSource:
    text: str
    blocks: tuple[SearchSourceBlock, ...]
    content_revision: int


class SearchSourceMap:
    def __init__(self, blocks: tuple[SearchSourceBlock, ...]) -> None:
        self.blocks = blocks
        self._ends = tuple(block.end for block in blocks)

    def locate(self, codepoint: int, utf16: int) -> tuple[int, int]:
        index = min(bisect_left(self._ends, codepoint), len(self.blocks) - 1)
        if index < 0:
            raise SearchSourceLimitError("The article has no searchable source blocks.")
        block = self.blocks[index]
        offset = min(max(0, utf16 - block.utf16_start), block.utf16_end - block.utf16_start)
        return index, offset


def read_search_source(
    repository,
    document_id: str,
    expected_revision: int,
    *,
    cancelled: Callable[[], bool],
    deadline: float,
) -> SearchSource:
    def check() -> None:
        if cancelled() or time.monotonic() >= deadline:
            raise SearchSourceCancelledError(
                "Search source preparation was cancelled or timed out."
            )

    check()
    # This facade is infrastructure in the same SQLite package as the repository.
    # No SQL or database ownership is delegated to an HTTP/desktop client.
    with repository._connection() as connection:
        connection.set_progress_handler(
            lambda: int(cancelled() or time.monotonic() >= deadline), 1000
        )
        try:
            return _read_snapshot(repository, connection, document_id, expected_revision, check)
        except sqlite3.OperationalError as error:
            if cancelled() or time.monotonic() >= deadline:
                raise SearchSourceCancelledError(
                    "Search source preparation was interrupted."
                ) from error
            raise
        finally:
            connection.set_progress_handler(None, 0)


def _read_snapshot(repository, connection, document_id, expected_revision, check) -> SearchSource:
    connection.execute("BEGIN")
    document = repository._require_document(connection, document_id)
    if document.deleted_at is not None or document.content_revision != expected_revision:
        raise SearchSourceChangedError("The article revision changed before search.")
    size = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(character_count), 0) FROM "
        "(SELECT character_count FROM reader_blocks WHERE document_id = ? "
        "ORDER BY ordinal LIMIT ?)",
        (document_id, MAX_SEARCH_BLOCKS + 1),
    ).fetchone()
    check()
    if int(size[0]) > MAX_SEARCH_BLOCKS or int(size[1]) > MAX_SEARCH_UTF16:
        raise SearchSourceLimitError("The article exceeds the search source bounds.")
    pieces: list[str] = []
    blocks: list[SearchSourceBlock] = []
    codepoints = units = 0
    for row in connection.execute(
        "SELECT id, ordinal, text FROM reader_blocks WHERE document_id = ? ORDER BY ordinal",
        (document_id,),
    ):
        check()
        text = str(row["text"])
        if codepoints > 0:
            pieces.append(SEPARATOR)
            codepoints += len(SEPARATOR)
            units += len(SEPARATOR)
        length = utf16_length(text)
        if units + length > MAX_SEARCH_UTF16:
            raise SearchSourceLimitError("The article exceeds the search UTF-16 bound.")
        blocks.append(
            SearchSourceBlock(
                str(row["id"]),
                int(row["ordinal"]),
                codepoints,
                codepoints + len(text),
                units,
                units + length,
            )
        )
        pieces.append(text)
        codepoints += len(text)
        units += length
    check()
    return SearchSource("".join(pieces), tuple(blocks), document.content_revision)
