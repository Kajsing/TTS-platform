"""Application-owned, bounded indexes of search positions; never cached source text."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from uuid import uuid4

from reader_core.errors import ReaderError
from reader_core.search import SearchResult, highlight_text, search_text
from reader_core.sqlite.search_source import (
    SearchSource,
    SearchSourceCancelledError,
    SearchSourceChangedError,
    SearchSourceLimitError,
    SearchSourceMap,
    read_search_source,
    utf16_length,
)

SESSION_SECONDS = 300
MAX_SESSIONS = 4
MAX_INDEXED_MATCHES = 300_000
MAX_RESULT_PAGE = 1000
MAX_WINDOW_MATCHES = 2000
MAX_SCAN_SECONDS = 8.0


class ReaderSearchError(ReaderError):
    def __init__(self, kind: str, message: str, status: int = 409) -> None:
        self.kind, self.status = kind, status
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class IndexedMatch:
    start: int
    length: int
    term_id: str | None
    start_block: int
    start_offset: int
    end_block: int
    end_offset: int


@dataclass(slots=True)
class SearchSession:
    id: str
    document_id: str
    content_revision: int
    kind: str
    highlighter_version: int | None
    source_map: SearchSourceMap
    matches: tuple[IndexedMatch, ...]
    counts: dict[str, int]
    truncated: bool
    failure: str | None
    regex_dialect: str | None
    touched: float = field(default_factory=time.monotonic)

    def summary(self) -> dict:
        return {
            "search_id": self.id,
            "document_id": self.document_id,
            "content_revision": self.content_revision,
            "kind": self.kind,
            "total_matches": len(self.matches),
            "counts": self.counts,
            "truncated": self.truncated,
            "failure": self.failure,
            "regex_dialect": self.regex_dialect,
            "expires_in_seconds": SESSION_SECONDS,
        }

    def hit(self, index: int) -> dict:
        match = self.matches[index]

        def cursor(block_index: int, offset: int) -> dict:
            block = self.source_map.blocks[block_index]
            return {
                "document_id": self.document_id,
                "block_id": block.id,
                "block_ordinal": block.ordinal,
                "character_offset": offset,
                "content_revision": self.content_revision,
            }

        return {
            "index": index,
            "start": match.start,
            "length": match.length,
            "term_id": match.term_id,
            "start_cursor": cursor(match.start_block, match.start_offset),
            "end_cursor": cursor(match.end_block, match.end_offset),
        }


class ReaderSearchManager:
    def __init__(self, service) -> None:
        self.service = service
        self._lock = threading.RLock()
        self._scan = threading.Lock()
        self._sessions: OrderedDict[str, SearchSession] = OrderedDict()
        self._closed = threading.Event()

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            self._sessions.clear()

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _current(self, document_id: str, revision: int, highlighter_version: int | None) -> None:
        current = self.service.repository.get_document(document_id)
        if current.deleted_at is not None or current.content_revision != revision:
            raise ReaderSearchError(
                "reader_revision_conflict", "The article changed. Reopen it and search again."
            )
        if highlighter_version is not None:
            config = self.service.repository.get_highlighter_configuration()
            if config.row_version != highlighter_version:
                raise ReaderSearchError(
                    "reader_search_configuration_changed",
                    "Highlight terms changed. Refresh highlighting.",
                )

    def create(
        self,
        document_id: str,
        revision: int,
        *,
        query: str = "",
        case_sensitive: bool = False,
        whole_word: bool = False,
        use_regex: bool = False,
        max_results: int = 10_000,
        highlighter_version: int | None = None,
        cancellation: threading.Event | None = None,
    ) -> SearchSession:
        if not self._scan.acquire(blocking=False):
            raise ReaderSearchError(
                "reader_search_busy", "Another bounded search is running. Try again shortly.", 429
            )
        try:
            self._current(document_id, revision, highlighter_version)
            deadline = time.monotonic() + MAX_SCAN_SECONDS

            def cancelled() -> bool:
                return (
                    self._closed.is_set()
                    or bool(cancellation and cancellation.is_set())
                    or time.monotonic() >= deadline
                )

            config = (
                self.service.repository.get_highlighter_configuration()
                if highlighter_version is not None
                else None
            )
            try:
                empty = (
                    not query
                    if config is None
                    else not any(term.active and term.term.strip() for term in config.terms)
                )
                source = (
                    SearchSource("", (), revision)
                    if empty
                    else read_search_source(
                        self.service.repository,
                        document_id,
                        revision,
                        cancelled=cancelled,
                        deadline=deadline,
                    )
                )
                result = (
                    SearchResult(())
                    if empty
                    else (
                        highlight_text(source.text, config.terms, cancelled=cancelled)
                        if config is not None
                        else search_text(
                            source.text,
                            query,
                            case_sensitive=case_sensitive,
                            whole_word=whole_word,
                            use_regex=use_regex,
                            max_results=max_results,
                            cancelled=cancelled,
                        )
                    )
                )
                source_map = SearchSourceMap(source.blocks)
                indexed: list[IndexedMatch] = []
                previous = units = 0
                for match in result.matches:
                    if cancelled():
                        raise SearchSourceCancelledError("Search indexing was interrupted.")
                    units += utf16_length(source.text[previous : match.start])
                    start_units = units
                    units += utf16_length(source.text[match.start : match.end])
                    start_block, start_offset = source_map.locate(match.start, start_units)
                    end_block, end_offset = source_map.locate(match.end, units)
                    indexed.append(
                        IndexedMatch(
                            start_units,
                            units - start_units,
                            match.term_id,
                            start_block,
                            start_offset,
                            end_block,
                            end_offset,
                        )
                    )
                    previous = match.end
                session = SearchSession(
                    str(uuid4()),
                    document_id,
                    revision,
                    "highlighter" if config is not None else "find",
                    highlighter_version,
                    source_map,
                    tuple(indexed),
                    dict(result.counts),
                    result.truncated,
                    result.failure,
                    "regex-v0" if use_regex or config is not None else None,
                )
            except SearchSourceLimitError:
                session = self._failure(
                    document_id, revision, highlighter_version, "document_too_large"
                )
            except SearchSourceCancelledError:
                session = self._failure(document_id, revision, highlighter_version, "cancelled")
            except SearchSourceChangedError as error:
                raise ReaderSearchError(
                    "reader_revision_conflict", "The article changed during search."
                ) from error
            except ValueError as error:
                raise ReaderSearchError(
                    "reader_search_configuration_invalid"
                    if config is not None
                    else "invalid_request",
                    "The search or highlight configuration exceeds its bounded limits.",
                    400,
                ) from error
            self._current(document_id, revision, highlighter_version)
            if self._closed.is_set() or bool(cancellation and cancellation.is_set()):
                raise ReaderSearchError("reader_search_cancelled", "Search was cancelled.", 409)
            with self._lock:
                if self._closed.is_set() or bool(cancellation and cancellation.is_set()):
                    raise ReaderSearchError("reader_search_cancelled", "Search was cancelled.", 409)
                self._prune()
                while self._sessions and (
                    len(self._sessions) >= MAX_SESSIONS
                    or sum(len(item.matches) for item in self._sessions.values())
                    + len(session.matches)
                    > MAX_INDEXED_MATCHES
                ):
                    self._sessions.popitem(last=False)
                self._sessions[session.id] = session
            return session
        finally:
            self._scan.release()

    @staticmethod
    def _failure(
        document_id: str, revision: int, config: int | None, failure: str | None
    ) -> SearchSession:
        return SearchSession(
            str(uuid4()),
            document_id,
            revision,
            "highlighter" if config is not None else "find",
            config,
            SearchSourceMap(()),
            (),
            {},
            False,
            failure,
            None,
        )

    def _prune(self) -> None:
        now = time.monotonic()
        for key, item in tuple(self._sessions.items()):
            if now - item.touched >= SESSION_SECONDS:
                del self._sessions[key]

    def get(self, document_id: str, session_id: str) -> SearchSession:
        with self._lock:
            if self._closed.is_set():
                raise ReaderSearchError("reader_search_expired", "Search service has stopped.", 410)
            self._prune()
            session = self._sessions.get(session_id)
            if session is None or session.document_id != document_id:
                raise ReaderSearchError(
                    "reader_search_expired", "Search results expired. Search again.", 410
                )
            self._current(document_id, session.content_revision, session.highlighter_version)
            session.touched = time.monotonic()
            self._sessions.move_to_end(session.id)
            return session

    def results(
        self, document_id: str, session_id: str, offset: int, limit: int
    ) -> tuple[SearchSession, dict]:
        session = self.get(document_id, session_id)
        end = min(len(session.matches), offset + limit)
        return session, {
            "document_id": document_id,
            "content_revision": session.content_revision,
            "matches": [session.hit(index) for index in range(offset, end)],
            "next_offset": end if end < len(session.matches) else None,
            "total_matches": len(session.matches),
            "truncated": session.truncated,
        }

    def window(
        self, document_id: str, session_id: str, start_ordinal: int, end_ordinal: int, limit: int
    ) -> tuple[SearchSession, dict]:
        session = self.get(document_id, session_id)
        matches = []
        truncated = False
        for index, item in enumerate(session.matches):
            start = session.source_map.blocks[item.start_block].ordinal
            end = session.source_map.blocks[item.end_block].ordinal
            if (
                start > end_ordinal
                or end < start_ordinal
                or (end == start_ordinal and item.end_offset == 0)
            ):
                continue
            if len(matches) == limit:
                truncated = True
                break
            matches.append(session.hit(index))
        return session, {
            "document_id": document_id,
            "content_revision": session.content_revision,
            "matches": matches,
            "next_offset": None,
            "total_matches": len(session.matches),
            "truncated": truncated or session.truncated,
        }

    def next_match(
        self, document_id: str, session_id: str, term_id: str, after_index: int
    ) -> tuple[SearchSession, dict]:
        session = self.get(document_id, session_id)
        first = selected = None
        for index, item in enumerate(session.matches):
            if item.term_id == term_id:
                if first is None:
                    first = index
                if index > after_index:
                    selected = index
                    break
        if selected is None:
            selected = first
        return session, {"match": session.hit(selected) if selected is not None else None}
