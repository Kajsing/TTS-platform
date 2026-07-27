from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from ..cursors import remap_cursor_for_edit
from ..errors import (
    ReaderConflictError,
    ReaderDatabaseError,
    ReaderEditHistoryError,
    ReaderNotFoundError,
    ReaderStaleCursorError,
    ReaderValidationError,
)
from ..models import (
    BlockKind,
    Bookmark,
    DocumentEdit,
    DocumentPage,
    DocumentState,
    EditOperation,
    PlaybackPosition,
    QueueItem,
    QueueStatus,
    ReaderBlock,
    ReaderCursor,
    ReaderDatabaseReport,
    ReaderDocument,
    ReaderDocumentBundle,
    ReaderSection,
    SourceType,
    utc_now,
)
from .connection import connect_sqlite
from .migrations import apply_migrations


class SqliteReaderRepository:
    def __init__(
        self,
        database_path: str | Path,
        *,
        max_edit_history_operations: int = 1000,
        max_edit_history_bytes: int = 10_485_760,
        initialize: bool = True,
    ) -> None:
        if max_edit_history_operations <= 0 or max_edit_history_bytes <= 0:
            raise ReaderValidationError("Reader edit-history limits must be positive")
        self.database_path = Path(database_path).resolve()
        self.max_edit_history_operations = max_edit_history_operations
        self.max_edit_history_bytes = max_edit_history_bytes
        if initialize:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection:
                apply_migrations(connection)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = connect_sqlite(self.database_path)
            yield connection
        except sqlite3.DatabaseError as exc:
            raise ReaderDatabaseError(f"Reader database operation failed: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            else:
                connection.commit()

    def create_document(self, bundle: ReaderDocumentBundle) -> ReaderDocument:
        _validate_bundle(bundle)
        with self._write() as connection:
            self._insert_document(connection, bundle.document)
            connection.executemany(
                """
                INSERT INTO reader_sections(
                    id, document_id, parent_section_id, ordinal, level, heading,
                    first_block_ordinal, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        section.id,
                        section.document_id,
                        section.parent_section_id,
                        section.ordinal,
                        section.level,
                        section.heading,
                        section.first_block_ordinal,
                        _json_dump(section.metadata),
                    )
                    for section in bundle.sections
                ],
            )
            connection.executemany(
                """
                INSERT INTO reader_blocks(
                    id, document_id, section_id, ordinal, kind, text,
                    character_count, content_sha256, row_version, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [_block_values(block) for block in bundle.blocks],
            )
        return bundle.document

    def get_document(self, document_id: str) -> ReaderDocument:
        with self._connection() as connection:
            return self._require_document(connection, document_id)

    def get_document_bundle(self, document_id: str) -> ReaderDocumentBundle:
        with self._connection() as connection:
            document = self._require_document(connection, document_id)
            sections = tuple(
                _section_from_row(row)
                for row in connection.execute(
                    "SELECT * FROM reader_sections WHERE document_id = ? ORDER BY ordinal",
                    (document_id,),
                )
            )
            blocks = tuple(
                _block_from_row(row)
                for row in connection.execute(
                    "SELECT * FROM reader_blocks WHERE document_id = ? ORDER BY ordinal",
                    (document_id,),
                )
            )
            return ReaderDocumentBundle(document=document, sections=sections, blocks=blocks)

    def list_documents(
        self,
        *,
        state: DocumentState | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> DocumentPage:
        if limit <= 0:
            raise ReaderValidationError("document page limit must be positive")
        boundary = _decode_page_cursor(cursor) if cursor is not None else None
        clauses = ["deleted_at IS NULL"]
        parameters: list[Any] = []
        if state is not None:
            clauses.append("state = ?")
            parameters.append(state.value)
        if boundary is not None:
            clauses.append("(updated_at < ? OR (updated_at = ? AND id < ?))")
            parameters.extend((boundary[0], boundary[0], boundary[1]))
        parameters.append(limit + 1)
        sql = (
            "SELECT * FROM reader_documents WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC, id DESC LIMIT ?"
        )
        with self._connection() as connection:
            rows = list(connection.execute(sql, parameters))
        has_more = len(rows) > limit
        selected = rows[:limit]
        items = tuple(_document_from_row(row) for row in selected)
        next_cursor = None
        if has_more and selected:
            next_cursor = _encode_page_cursor(str(selected[-1]["updated_at"]), selected[-1]["id"])
        return DocumentPage(items=items, next_cursor=next_cursor)

    def list_blocks(
        self,
        document_id: str,
        *,
        after_ordinal: int = -1,
        limit: int = 200,
    ) -> tuple[ReaderBlock, ...]:
        if after_ordinal < -1 or limit <= 0:
            raise ReaderValidationError("block pagination values are invalid")
        with self._connection() as connection:
            self._require_document(connection, document_id)
            return tuple(
                _block_from_row(row)
                for row in connection.execute(
                    """
                    SELECT * FROM reader_blocks
                    WHERE document_id = ? AND ordinal > ?
                    ORDER BY ordinal LIMIT ?
                    """,
                    (document_id, after_ordinal, limit),
                )
            )

    def update_document(
        self,
        document_id: str,
        *,
        expected_row_version: int,
        title: str | None = None,
        state: DocumentState | None = None,
    ) -> ReaderDocument:
        if title is not None and not title.strip():
            raise ReaderValidationError("document title must not be empty")
        with self._write() as connection:
            current = self._require_document(connection, document_id)
            _check_version(current, expected_row_version)
            connection.execute(
                """
                UPDATE reader_documents
                SET title = ?, state = ?, updated_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (
                    title.strip() if title is not None else current.title,
                    (state or current.state).value,
                    _time_dump(utc_now()),
                    document_id,
                ),
            )
            return self._require_document(connection, document_id)

    def soft_delete_document(
        self,
        document_id: str,
        *,
        expected_row_version: int,
    ) -> ReaderDocument:
        with self._write() as connection:
            document = self._require_document(connection, document_id)
            _check_version(document, expected_row_version)
            now = _time_dump(utc_now())
            connection.execute(
                """
                UPDATE reader_documents
                SET deleted_at = ?, updated_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (now, now, document_id),
            )
            connection.execute(
                "DELETE FROM reader_queue_items WHERE document_id = ?", (document_id,)
            )
            self._compact_queue(connection)
            return self._require_document(connection, document_id)

    def restore_document(
        self,
        document_id: str,
        *,
        expected_row_version: int,
    ) -> ReaderDocument:
        with self._write() as connection:
            document = self._require_document(connection, document_id)
            _check_version(document, expected_row_version)
            connection.execute(
                """
                UPDATE reader_documents
                SET deleted_at = NULL, updated_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (_time_dump(utc_now()), document_id),
            )
            return self._require_document(connection, document_id)

    def replace_block_text(
        self,
        document_id: str,
        block_id: str,
        *,
        start_offset: int,
        end_offset: int,
        replacement_text: str,
        expected_row_version: int,
    ) -> tuple[ReaderDocument, DocumentEdit]:
        with self._write() as connection:
            document = self._require_editable_document(connection, document_id)
            _check_version(document, expected_row_version)
            row = connection.execute(
                "SELECT * FROM reader_blocks WHERE id = ? AND document_id = ?",
                (block_id, document_id),
            ).fetchone()
            if row is None:
                raise ReaderNotFoundError(f"Reader block not found: {block_id}")
            block = _block_from_row(row)
            if min(start_offset, end_offset) < 0 or end_offset < start_offset:
                raise ReaderValidationError("edit offsets are invalid")
            if end_offset > len(block.text):
                raise ReaderValidationError("edit range exceeds block text")
            original = block.text[start_offset:end_offset]
            updated_text = block.text[:start_offset] + replacement_text + block.text[end_offset:]
            new_revision = document.content_revision + 1
            now = utc_now()
            self._discard_redo(connection, document_id)
            edit = DocumentEdit(
                id=str(uuid.uuid4()),
                document_id=document_id,
                sequence=self._next_edit_sequence(connection, document_id),
                base_content_revision=document.content_revision,
                result_content_revision=new_revision,
                block_id=block_id,
                start_offset=start_offset,
                end_offset=end_offset,
                original_text=original,
                replacement_text=replacement_text,
                operation_type=EditOperation.REPLACE,
                created_at=now,
            )
            connection.execute(
                """
                UPDATE reader_blocks
                SET text = ?, character_count = ?, content_sha256 = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (updated_text, len(updated_text), _sha256(updated_text), block_id),
            )
            self._update_document_content(
                connection,
                document,
                new_revision=new_revision,
                block_delta=0,
                character_delta=len(replacement_text) - len(original),
                now=now,
            )
            self._remap_saved_cursors(
                connection,
                document_id=document_id,
                edited_block_id=block_id,
                start_offset=start_offset,
                end_offset=end_offset,
                replacement_length=len(replacement_text),
                new_revision=new_revision,
            )
            self._insert_edit(connection, edit)
            self._trim_history(connection, document_id)
            return self._require_document(connection, document_id), edit

    def append_text(
        self,
        document_id: str,
        text: str,
        *,
        expected_row_version: int,
    ) -> tuple[ReaderDocument, DocumentEdit]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise ReaderValidationError("appended text must not be empty")
        with self._write() as connection:
            document = self._require_editable_document(connection, document_id)
            _check_version(document, expected_row_version)
            last = connection.execute(
                """
                SELECT ordinal, section_id FROM reader_blocks
                WHERE document_id = ? ORDER BY ordinal DESC LIMIT 1
                """,
                (document_id,),
            ).fetchone()
            if last is None:
                raise ReaderValidationError("cannot append to a document without blocks")
            block_id = str(uuid.uuid4())
            ordinal = int(last["ordinal"]) + 1
            section_id = last["section_id"]
            new_revision = document.content_revision + 1
            now = utc_now()
            self._discard_redo(connection, document_id)
            edit = DocumentEdit(
                id=str(uuid.uuid4()),
                document_id=document_id,
                sequence=self._next_edit_sequence(connection, document_id),
                base_content_revision=document.content_revision,
                result_content_revision=new_revision,
                block_id=block_id,
                start_offset=0,
                end_offset=0,
                original_text="",
                replacement_text=normalized,
                operation_type=EditOperation.APPEND,
                created_at=now,
                metadata={
                    "section_id": section_id,
                    "ordinal": ordinal,
                    "kind": BlockKind.PARAGRAPH.value,
                },
            )
            connection.execute(
                """
                INSERT INTO reader_blocks(
                    id, document_id, section_id, ordinal, kind, text,
                    character_count, content_sha256, row_version, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, '{}')
                """,
                (
                    block_id,
                    document_id,
                    section_id,
                    ordinal,
                    BlockKind.PARAGRAPH.value,
                    normalized,
                    len(normalized),
                    _sha256(normalized),
                ),
            )
            self._update_document_content(
                connection,
                document,
                new_revision=new_revision,
                block_delta=1,
                character_delta=len(normalized),
                now=now,
            )
            self._advance_saved_cursor_revisions(connection, document_id, new_revision)
            self._insert_edit(connection, edit)
            self._trim_history(connection, document_id)
            return self._require_document(connection, document_id), edit

    def undo(self, document_id: str, *, expected_row_version: int) -> ReaderDocument:
        with self._write() as connection:
            document = self._require_editable_document(connection, document_id)
            _check_version(document, expected_row_version)
            row = connection.execute(
                """
                SELECT * FROM reader_document_edits
                WHERE document_id = ? AND applied = 1
                ORDER BY sequence DESC LIMIT 1
                """,
                (document_id,),
            ).fetchone()
            if row is None:
                raise ReaderEditHistoryError("No Reader edit is available to undo")
            edit = _edit_from_row(row)
            new_revision = document.content_revision + 1
            now = utc_now()
            if edit.operation_type is EditOperation.REPLACE:
                self._apply_replace_inverse(connection, edit, new_revision)
                character_delta = len(edit.original_text) - len(edit.replacement_text)
                block_delta = 0
            else:
                self._remove_appended_block(connection, edit, new_revision)
                character_delta = -len(edit.replacement_text)
                block_delta = -1
            self._update_document_content(
                connection,
                document,
                new_revision=new_revision,
                block_delta=block_delta,
                character_delta=character_delta,
                now=now,
            )
            connection.execute(
                "UPDATE reader_document_edits SET applied = 0, undone_at = ? WHERE id = ?",
                (_time_dump(now), edit.id),
            )
            return self._require_document(connection, document_id)

    def redo(self, document_id: str, *, expected_row_version: int) -> ReaderDocument:
        with self._write() as connection:
            document = self._require_editable_document(connection, document_id)
            _check_version(document, expected_row_version)
            row = connection.execute(
                """
                SELECT * FROM reader_document_edits
                WHERE document_id = ? AND applied = 0
                ORDER BY sequence ASC LIMIT 1
                """,
                (document_id,),
            ).fetchone()
            if row is None:
                raise ReaderEditHistoryError("No Reader edit is available to redo")
            edit = _edit_from_row(row)
            new_revision = document.content_revision + 1
            now = utc_now()
            if edit.operation_type is EditOperation.REPLACE:
                self._apply_replace_forward(connection, edit, new_revision)
                character_delta = len(edit.replacement_text) - len(edit.original_text)
                block_delta = 0
            else:
                self._restore_appended_block(connection, edit)
                self._advance_saved_cursor_revisions(connection, document_id, new_revision)
                character_delta = len(edit.replacement_text)
                block_delta = 1
            self._update_document_content(
                connection,
                document,
                new_revision=new_revision,
                block_delta=block_delta,
                character_delta=character_delta,
                now=now,
            )
            connection.execute(
                "UPDATE reader_document_edits SET applied = 1, undone_at = NULL WHERE id = ?",
                (edit.id,),
            )
            return self._require_document(connection, document_id)

    def clear_edit_history(self, document_id: str) -> None:
        with self._write() as connection:
            self._require_document(connection, document_id)
            connection.execute(
                "DELETE FROM reader_document_edits WHERE document_id = ?", (document_id,)
            )

    def resolve_cursor(self, cursor: ReaderCursor) -> ReaderCursor:
        with self._connection() as connection:
            return self._resolve_cursor(connection, cursor)

    def get_position(self, document_id: str) -> PlaybackPosition | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM reader_playback_positions WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            return _position_from_row(row) if row is not None else None

    def save_position(
        self,
        position: PlaybackPosition,
        *,
        expected_row_version: int | None = None,
    ) -> PlaybackPosition:
        with self._write() as connection:
            cursor = self._resolve_cursor(connection, position.cursor)
            existing = connection.execute(
                "SELECT * FROM reader_playback_positions WHERE document_id = ?",
                (position.document_id,),
            ).fetchone()
            if existing is None:
                if expected_row_version not in (None, 0):
                    raise ReaderConflictError(
                        position.document_id,
                        expected=expected_row_version,
                        actual=0,
                    )
                row_version = 1
                connection.execute(
                    """
                    INSERT INTO reader_playback_positions(
                        document_id, block_id, block_ordinal, character_offset,
                        content_revision, segment_index, voice_profile_id,
                        pipeline_version, rules_version, updated_at, completed, row_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _position_values(replace(position, cursor=cursor, row_version=row_version)),
                )
            else:
                current = _position_from_row(existing)
                candidate = replace(position, cursor=cursor, row_version=current.row_version)
                if candidate == current:
                    return current
                actual = int(existing["row_version"])
                if expected_row_version is not None and expected_row_version != actual:
                    raise ReaderConflictError(
                        position.document_id,
                        expected=expected_row_version,
                        actual=actual,
                    )
                row_version = actual + 1
                stored = replace(position, cursor=cursor, row_version=row_version)
                connection.execute(
                    """
                    UPDATE reader_playback_positions SET
                        block_id = ?, block_ordinal = ?, character_offset = ?,
                        content_revision = ?, segment_index = ?, voice_profile_id = ?,
                        pipeline_version = ?, rules_version = ?, updated_at = ?,
                        completed = ?, row_version = ?
                    WHERE document_id = ?
                    """,
                    _position_update_values(stored),
                )
            row = connection.execute(
                "SELECT * FROM reader_playback_positions WHERE document_id = ?",
                (position.document_id,),
            ).fetchone()
            assert row is not None
            return _position_from_row(row)

    def create_bookmark(self, bookmark: Bookmark) -> Bookmark:
        with self._write() as connection:
            cursor = self._resolve_cursor(connection, bookmark.cursor)
            stored = replace(bookmark, cursor=cursor)
            connection.execute(
                """
                INSERT INTO reader_bookmarks(
                    id, document_id, block_id, block_ordinal, character_offset,
                    content_revision, segment_index, label, note, created_at,
                    updated_at, row_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _bookmark_values(stored),
            )
            return stored

    def list_bookmarks(self, document_id: str) -> tuple[Bookmark, ...]:
        with self._connection() as connection:
            self._require_document(connection, document_id)
            return tuple(
                _bookmark_from_row(row)
                for row in connection.execute(
                    """
                    SELECT * FROM reader_bookmarks WHERE document_id = ?
                    ORDER BY block_ordinal, character_offset, created_at, id
                    """,
                    (document_id,),
                )
            )

    def update_bookmark(
        self,
        bookmark_id: str,
        *,
        expected_row_version: int,
        cursor: ReaderCursor | None = None,
        label: str | None = None,
        note: str | None = None,
    ) -> Bookmark:
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM reader_bookmarks WHERE id = ?", (bookmark_id,)
            ).fetchone()
            if row is None:
                raise ReaderNotFoundError(f"Reader bookmark not found: {bookmark_id}")
            current = _bookmark_from_row(row)
            if current.row_version != expected_row_version:
                raise ReaderConflictError(
                    bookmark_id,
                    expected=expected_row_version,
                    actual=current.row_version,
                )
            resolved = self._resolve_cursor(connection, cursor) if cursor else current.cursor
            updated = replace(
                current,
                cursor=resolved,
                label=current.label if label is None else label,
                note=current.note if note is None else note,
                updated_at=utc_now(),
                row_version=current.row_version + 1,
            )
            connection.execute(
                """
                UPDATE reader_bookmarks SET
                    block_id = ?, block_ordinal = ?, character_offset = ?,
                    content_revision = ?, segment_index = ?, label = ?, note = ?,
                    updated_at = ?, row_version = ?
                WHERE id = ?
                """,
                (
                    updated.cursor.block_id,
                    updated.cursor.block_ordinal,
                    updated.cursor.character_offset,
                    updated.cursor.content_revision,
                    updated.cursor.segment_index,
                    updated.label,
                    updated.note,
                    _time_dump(updated.updated_at),
                    updated.row_version,
                    bookmark_id,
                ),
            )
            return updated

    def delete_bookmark(self, bookmark_id: str, *, expected_row_version: int) -> None:
        with self._write() as connection:
            row = connection.execute(
                "SELECT row_version FROM reader_bookmarks WHERE id = ?", (bookmark_id,)
            ).fetchone()
            if row is None:
                raise ReaderNotFoundError(f"Reader bookmark not found: {bookmark_id}")
            actual = int(row["row_version"])
            if actual != expected_row_version:
                raise ReaderConflictError(
                    bookmark_id,
                    expected=expected_row_version,
                    actual=actual,
                )
            connection.execute("DELETE FROM reader_bookmarks WHERE id = ?", (bookmark_id,))

    def add_queue_item(self, item: QueueItem) -> QueueItem:
        with self._write() as connection:
            document = self._require_document(connection, item.document_id)
            if document.deleted_at is not None:
                raise ReaderValidationError("soft-deleted documents cannot be queued")
            if item.status is QueueStatus.PLAYING:
                playing = connection.execute(
                    "SELECT id FROM reader_queue_items WHERE status = 'playing'"
                ).fetchone()
                if playing is not None:
                    raise ReaderValidationError("only one queue item may be playing")
            connection.execute(
                """
                INSERT INTO reader_queue_items(
                    id, document_id, ordinal, status, added_at, updated_at, row_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.document_id,
                    item.ordinal,
                    item.status.value,
                    _time_dump(item.added_at),
                    _time_dump(item.updated_at),
                    item.row_version,
                ),
            )
            return item

    def list_queue(self) -> tuple[QueueItem, ...]:
        with self._connection() as connection:
            return tuple(
                _queue_from_row(row)
                for row in connection.execute(
                    """
                    SELECT queue.* FROM reader_queue_items AS queue
                    JOIN reader_documents AS document ON document.id = queue.document_id
                    WHERE document.deleted_at IS NULL
                    ORDER BY queue.ordinal
                    """
                )
            )

    def update_queue_item(
        self,
        item_id: str,
        *,
        expected_row_version: int,
        status: QueueStatus,
    ) -> QueueItem:
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM reader_queue_items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise ReaderNotFoundError(f"Reader queue item not found: {item_id}")
            current = _queue_from_row(row)
            if current.row_version != expected_row_version:
                raise ReaderConflictError(
                    item_id,
                    expected=expected_row_version,
                    actual=current.row_version,
                )
            if status is QueueStatus.PLAYING:
                playing = connection.execute(
                    "SELECT id FROM reader_queue_items WHERE status = 'playing' AND id <> ?",
                    (item_id,),
                ).fetchone()
                if playing is not None:
                    raise ReaderValidationError("only one queue item may be playing")
            updated = replace(
                current,
                status=status,
                updated_at=utc_now(),
                row_version=current.row_version + 1,
            )
            connection.execute(
                """
                UPDATE reader_queue_items
                SET status = ?, updated_at = ?, row_version = ? WHERE id = ?
                """,
                (
                    updated.status.value,
                    _time_dump(updated.updated_at),
                    updated.row_version,
                    item_id,
                ),
            )
            return updated

    def remove_queue_item(self, item_id: str, *, expected_row_version: int) -> None:
        with self._write() as connection:
            row = connection.execute(
                "SELECT row_version FROM reader_queue_items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise ReaderNotFoundError(f"Reader queue item not found: {item_id}")
            actual = int(row["row_version"])
            if actual != expected_row_version:
                raise ReaderConflictError(item_id, expected=expected_row_version, actual=actual)
            connection.execute("DELETE FROM reader_queue_items WHERE id = ?", (item_id,))
            self._compact_queue(connection)

    def reorder_queue(self, item_ids: tuple[str, ...]) -> tuple[QueueItem, ...]:
        if len(set(item_ids)) != len(item_ids):
            raise ReaderValidationError("queue reorder contains duplicate item IDs")
        with self._write() as connection:
            existing = tuple(
                row["id"]
                for row in connection.execute("SELECT id FROM reader_queue_items ORDER BY ordinal")
            )
            if set(existing) != set(item_ids) or len(existing) != len(item_ids):
                raise ReaderValidationError(
                    "queue reorder must contain every current item exactly once"
                )
            shift = len(item_ids) + 1
            connection.execute(
                """
                UPDATE reader_queue_items
                SET ordinal = ordinal + ?, row_version = row_version + 1
                """,
                (shift,),
            )
            now = _time_dump(utc_now())
            for ordinal, item_id in enumerate(item_ids):
                connection.execute(
                    "UPDATE reader_queue_items SET ordinal = ?, updated_at = ? WHERE id = ?",
                    (ordinal, now, item_id),
                )
            return tuple(
                _queue_from_row(row)
                for row in connection.execute("SELECT * FROM reader_queue_items ORDER BY ordinal")
            )

    def report(self) -> ReaderDatabaseReport:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            schema_version = int(row["version"])
            integrity_rows = [str(item[0]) for item in connection.execute("PRAGMA integrity_check")]
            integrity_message = "; ".join(integrity_rows)
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            return ReaderDatabaseReport(
                ready=integrity_rows == ["ok"],
                schema_version=schema_version,
                integrity_ok=integrity_rows == ["ok"],
                integrity_message=integrity_message,
                journal_mode=journal_mode,
                database_path=str(self.database_path),
            )

    def backup_to(self, destination: Path, *, overwrite: bool = False) -> Path:
        target = destination.resolve()
        if target == self.database_path:
            raise ReaderValidationError(
                "Reader backup destination must differ from the live database"
            )
        if target.exists() and not overwrite:
            raise FileExistsError(f"Reader backup already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            backup = sqlite3.connect(temporary)
            try:
                with self._connection() as source:
                    source.backup(backup)
                backup.commit()
            finally:
                backup.close()
            if target.exists() and not overwrite:
                raise FileExistsError(f"Reader backup already exists: {target}")
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
        return target

    def _require_document(
        self,
        connection: sqlite3.Connection,
        document_id: str,
    ) -> ReaderDocument:
        row = connection.execute(
            "SELECT * FROM reader_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            raise ReaderNotFoundError(f"Reader document not found: {document_id}")
        return _document_from_row(row)

    def _require_editable_document(
        self,
        connection: sqlite3.Connection,
        document_id: str,
    ) -> ReaderDocument:
        document = self._require_document(connection, document_id)
        if document.deleted_at is not None:
            raise ReaderValidationError("soft-deleted documents cannot be edited")
        if document.source_type not in {
            SourceType.PLAIN_TEXT,
            SourceType.CLIPBOARD,
            SourceType.SELECTION,
            SourceType.TEXT_FILE,
        }:
            raise ReaderValidationError("this document source type is not directly editable")
        return document

    def _insert_document(self, connection: sqlite3.Connection, document: ReaderDocument) -> None:
        connection.execute(
            """
            INSERT INTO reader_documents(
                id, title, source_type, source_name, source_uri, source_sha256,
                language_hint, state, created_at, updated_at, imported_at,
                deleted_at, content_revision, row_version, total_sections,
                total_blocks, total_characters, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.id,
                document.title,
                document.source_type.value,
                document.source_name,
                document.source_uri,
                document.source_sha256,
                document.language_hint,
                document.state.value,
                _time_dump(document.created_at),
                _time_dump(document.updated_at),
                _time_dump(document.imported_at),
                _time_dump(document.deleted_at) if document.deleted_at else None,
                document.content_revision,
                document.row_version,
                document.total_sections,
                document.total_blocks,
                document.total_characters,
                _json_dump(document.metadata),
            ),
        )

    def _update_document_content(
        self,
        connection: sqlite3.Connection,
        document: ReaderDocument,
        *,
        new_revision: int,
        block_delta: int,
        character_delta: int,
        now: datetime,
    ) -> None:
        connection.execute(
            """
            UPDATE reader_documents SET
                content_revision = ?, row_version = row_version + 1, updated_at = ?,
                total_blocks = total_blocks + ?, total_characters = total_characters + ?
            WHERE id = ?
            """,
            (new_revision, _time_dump(now), block_delta, character_delta, document.id),
        )

    def _insert_edit(self, connection: sqlite3.Connection, edit: DocumentEdit) -> None:
        connection.execute(
            """
            INSERT INTO reader_document_edits(
                id, document_id, sequence, base_content_revision,
                result_content_revision, block_id, start_offset, end_offset,
                original_text, replacement_text, operation_type, created_at,
                applied, undone_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edit.id,
                edit.document_id,
                edit.sequence,
                edit.base_content_revision,
                edit.result_content_revision,
                edit.block_id,
                edit.start_offset,
                edit.end_offset,
                edit.original_text,
                edit.replacement_text,
                edit.operation_type.value,
                _time_dump(edit.created_at),
                int(edit.applied),
                _time_dump(edit.undone_at) if edit.undone_at else None,
                _json_dump(edit.metadata),
            ),
        )

    def _discard_redo(self, connection: sqlite3.Connection, document_id: str) -> None:
        connection.execute(
            "DELETE FROM reader_document_edits WHERE document_id = ? AND applied = 0",
            (document_id,),
        )

    def _next_edit_sequence(self, connection: sqlite3.Connection, document_id: str) -> int:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence
            FROM reader_document_edits WHERE document_id = ?
            """,
            (document_id,),
        ).fetchone()
        return int(row["sequence"])

    def _compact_queue(self, connection: sqlite3.Connection) -> None:
        rows = list(
            connection.execute("SELECT id, ordinal FROM reader_queue_items ORDER BY ordinal")
        )
        if all(int(row["ordinal"]) == ordinal for ordinal, row in enumerate(rows)):
            return
        shift = len(rows) + 1
        connection.execute("UPDATE reader_queue_items SET ordinal = ordinal + ?", (shift,))
        now = _time_dump(utc_now())
        for ordinal, row in enumerate(rows):
            connection.execute(
                """
                UPDATE reader_queue_items SET ordinal = ?, updated_at = ?,
                    row_version = row_version + 1 WHERE id = ?
                """,
                (ordinal, now, row["id"]),
            )

    def _trim_history(self, connection: sqlite3.Connection, document_id: str) -> None:
        rows = list(
            connection.execute(
                """
                SELECT id, length(CAST(original_text AS BLOB))
                    + length(CAST(replacement_text AS BLOB)) AS text_bytes
                FROM reader_document_edits WHERE document_id = ? ORDER BY sequence DESC
                """,
                (document_id,),
            )
        )
        retained = 0
        retained_bytes = 0
        delete_ids: list[str] = []
        for row in rows:
            size = int(row["text_bytes"] or 0)
            if (
                retained >= self.max_edit_history_operations
                or retained_bytes + size > self.max_edit_history_bytes
            ):
                delete_ids.append(str(row["id"]))
            else:
                retained += 1
                retained_bytes += size
        connection.executemany(
            "DELETE FROM reader_document_edits WHERE id = ?",
            [(edit_id,) for edit_id in delete_ids],
        )

    def _advance_saved_cursor_revisions(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        new_revision: int,
    ) -> None:
        connection.execute(
            """
            UPDATE reader_playback_positions
            SET content_revision = ?, segment_index = NULL, row_version = row_version + 1
            WHERE document_id = ?
            """,
            (new_revision, document_id),
        )
        connection.execute(
            """
            UPDATE reader_bookmarks
            SET content_revision = ?, segment_index = NULL, row_version = row_version + 1,
                updated_at = ?
            WHERE document_id = ?
            """,
            (new_revision, _time_dump(utc_now()), document_id),
        )

    def _remap_saved_cursors(
        self,
        connection: sqlite3.Connection,
        *,
        document_id: str,
        edited_block_id: str,
        start_offset: int,
        end_offset: int,
        replacement_length: int,
        new_revision: int,
    ) -> None:
        position = connection.execute(
            "SELECT * FROM reader_playback_positions WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if position is not None:
            remapped = remap_cursor_for_edit(
                _cursor_from_row(position),
                edited_block_id=edited_block_id,
                start_offset=start_offset,
                end_offset=end_offset,
                replacement_length=replacement_length,
                new_content_revision=new_revision,
            )
            connection.execute(
                """
                UPDATE reader_playback_positions SET character_offset = ?, content_revision = ?,
                    segment_index = NULL, row_version = row_version + 1
                WHERE document_id = ?
                """,
                (remapped.character_offset, new_revision, document_id),
            )
        bookmarks = list(
            connection.execute(
                "SELECT * FROM reader_bookmarks WHERE document_id = ?", (document_id,)
            )
        )
        now = _time_dump(utc_now())
        for bookmark in bookmarks:
            remapped = remap_cursor_for_edit(
                _cursor_from_row(bookmark),
                edited_block_id=edited_block_id,
                start_offset=start_offset,
                end_offset=end_offset,
                replacement_length=replacement_length,
                new_content_revision=new_revision,
            )
            connection.execute(
                """
                UPDATE reader_bookmarks SET character_offset = ?, content_revision = ?,
                    segment_index = NULL, updated_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (remapped.character_offset, new_revision, now, bookmark["id"]),
            )

    def _apply_replace_inverse(
        self,
        connection: sqlite3.Connection,
        edit: DocumentEdit,
        new_revision: int,
    ) -> None:
        row = connection.execute(
            "SELECT text FROM reader_blocks WHERE id = ?", (edit.block_id,)
        ).fetchone()
        if row is None:
            raise ReaderStaleCursorError("edited block no longer exists")
        text = str(row["text"])
        end = edit.start_offset + len(edit.replacement_text)
        if text[edit.start_offset : end] != edit.replacement_text:
            raise ReaderStaleCursorError("edited block no longer matches undo history")
        updated = text[: edit.start_offset] + edit.original_text + text[end:]
        connection.execute(
            """
            UPDATE reader_blocks SET text = ?, character_count = ?, content_sha256 = ?,
                row_version = row_version + 1 WHERE id = ?
            """,
            (updated, len(updated), _sha256(updated), edit.block_id),
        )
        self._remap_saved_cursors(
            connection,
            document_id=edit.document_id,
            edited_block_id=edit.block_id,
            start_offset=edit.start_offset,
            end_offset=end,
            replacement_length=len(edit.original_text),
            new_revision=new_revision,
        )

    def _apply_replace_forward(
        self,
        connection: sqlite3.Connection,
        edit: DocumentEdit,
        new_revision: int,
    ) -> None:
        row = connection.execute(
            "SELECT text FROM reader_blocks WHERE id = ?", (edit.block_id,)
        ).fetchone()
        if row is None:
            raise ReaderStaleCursorError("edited block no longer exists")
        text = str(row["text"])
        end = edit.start_offset + len(edit.original_text)
        if text[edit.start_offset : end] != edit.original_text:
            raise ReaderStaleCursorError("edited block no longer matches redo history")
        updated = text[: edit.start_offset] + edit.replacement_text + text[end:]
        connection.execute(
            """
            UPDATE reader_blocks SET text = ?, character_count = ?, content_sha256 = ?,
                row_version = row_version + 1 WHERE id = ?
            """,
            (updated, len(updated), _sha256(updated), edit.block_id),
        )
        self._remap_saved_cursors(
            connection,
            document_id=edit.document_id,
            edited_block_id=edit.block_id,
            start_offset=edit.start_offset,
            end_offset=end,
            replacement_length=len(edit.replacement_text),
            new_revision=new_revision,
        )

    def _remove_appended_block(
        self,
        connection: sqlite3.Connection,
        edit: DocumentEdit,
        new_revision: int,
    ) -> None:
        row = connection.execute(
            "SELECT ordinal, text FROM reader_blocks WHERE id = ? AND document_id = ?",
            (edit.block_id, edit.document_id),
        ).fetchone()
        if row is None or row["text"] != edit.replacement_text:
            raise ReaderStaleCursorError("appended block no longer matches undo history")
        previous = connection.execute(
            """
            SELECT id, ordinal, character_count FROM reader_blocks
            WHERE document_id = ? AND ordinal < ? ORDER BY ordinal DESC LIMIT 1
            """,
            (edit.document_id, row["ordinal"]),
        ).fetchone()
        if previous is None:
            raise ReaderStaleCursorError("appended block has no stable predecessor")
        connection.execute(
            """
            UPDATE reader_playback_positions SET block_id = ?, block_ordinal = ?,
                character_offset = ?
            WHERE document_id = ? AND block_id = ?
            """,
            (
                previous["id"],
                previous["ordinal"],
                previous["character_count"],
                edit.document_id,
                edit.block_id,
            ),
        )
        connection.execute(
            """
            UPDATE reader_bookmarks SET block_id = ?, block_ordinal = ?, character_offset = ?,
                updated_at = ?
            WHERE document_id = ? AND block_id = ?
            """,
            (
                previous["id"],
                previous["ordinal"],
                previous["character_count"],
                _time_dump(utc_now()),
                edit.document_id,
                edit.block_id,
            ),
        )
        self._advance_saved_cursor_revisions(connection, edit.document_id, new_revision)
        connection.execute("DELETE FROM reader_blocks WHERE id = ?", (edit.block_id,))

    def _restore_appended_block(self, connection: sqlite3.Connection, edit: DocumentEdit) -> None:
        metadata = dict(edit.metadata)
        connection.execute(
            """
            INSERT INTO reader_blocks(
                id, document_id, section_id, ordinal, kind, text,
                character_count, content_sha256, row_version, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, '{}')
            """,
            (
                edit.block_id,
                edit.document_id,
                metadata.get("section_id"),
                int(metadata["ordinal"]),
                str(metadata.get("kind", BlockKind.PARAGRAPH.value)),
                edit.replacement_text,
                len(edit.replacement_text),
                _sha256(edit.replacement_text),
            ),
        )

    def _resolve_cursor(
        self,
        connection: sqlite3.Connection,
        cursor: ReaderCursor,
    ) -> ReaderCursor:
        document = self._require_document(connection, cursor.document_id)
        if cursor.content_revision > document.content_revision:
            raise ReaderStaleCursorError("cursor revision is newer than the document")
        remapped = cursor
        if cursor.content_revision < document.content_revision:
            rows = list(
                connection.execute(
                    """
                    SELECT * FROM reader_document_edits
                    WHERE document_id = ? AND base_content_revision >= ? AND applied = 1
                    ORDER BY base_content_revision
                    """,
                    (cursor.document_id, cursor.content_revision),
                )
            )
            revision = cursor.content_revision
            for row in rows:
                edit = _edit_from_row(row)
                if edit.base_content_revision != revision:
                    raise ReaderStaleCursorError("cursor edit history is incomplete or branched")
                if edit.operation_type is EditOperation.REPLACE:
                    remapped = remap_cursor_for_edit(
                        remapped,
                        edited_block_id=edit.block_id,
                        start_offset=edit.start_offset,
                        end_offset=edit.end_offset,
                        replacement_length=len(edit.replacement_text),
                        new_content_revision=edit.result_content_revision,
                    )
                else:
                    remapped = replace(
                        remapped,
                        content_revision=edit.result_content_revision,
                        segment_index=None,
                    )
                revision = edit.result_content_revision
            if revision != document.content_revision:
                raise ReaderStaleCursorError("cursor cannot be mapped to the current revision")
        block = connection.execute(
            "SELECT ordinal, character_count FROM reader_blocks WHERE id = ? AND document_id = ?",
            (remapped.block_id, remapped.document_id),
        ).fetchone()
        if block is None or remapped.character_offset > int(block["character_count"]):
            raise ReaderStaleCursorError("cursor block or offset is no longer valid")
        return replace(
            remapped,
            block_ordinal=int(block["ordinal"]),
            content_revision=document.content_revision,
        )


def initialize_reader_repository(
    *,
    enabled: bool,
    database_path: str | Path,
    max_edit_history_operations: int = 1000,
    max_edit_history_bytes: int = 10_485_760,
) -> SqliteReaderRepository | None:
    if not enabled:
        return None
    return SqliteReaderRepository(
        database_path,
        max_edit_history_operations=max_edit_history_operations,
        max_edit_history_bytes=max_edit_history_bytes,
    )


def _validate_bundle(bundle: ReaderDocumentBundle) -> None:
    document = bundle.document
    if any(section.document_id != document.id for section in bundle.sections):
        raise ReaderValidationError("all sections must belong to the document")
    if any(block.document_id != document.id for block in bundle.blocks):
        raise ReaderValidationError("all blocks must belong to the document")
    if [section.ordinal for section in bundle.sections] != list(range(len(bundle.sections))):
        raise ReaderValidationError("section ordinals must be contiguous")
    if [block.ordinal for block in bundle.blocks] != list(range(len(bundle.blocks))):
        raise ReaderValidationError("block ordinals must be contiguous")
    section_ids = {section.id for section in bundle.sections}
    if any(block.section_id not in section_ids for block in bundle.blocks):
        raise ReaderValidationError("block section IDs must belong to the document")
    if document.total_sections != len(bundle.sections) or document.total_blocks != len(
        bundle.blocks
    ):
        raise ReaderValidationError("document totals must match its structure")
    if document.total_characters != sum(block.character_count for block in bundle.blocks):
        raise ReaderValidationError("document character total must match its blocks")
    if any(block.content_sha256 != _sha256(block.text) for block in bundle.blocks):
        raise ReaderValidationError("block content hashes must match their text")


def _check_version(document: ReaderDocument, expected: int) -> None:
    if expected != document.row_version:
        raise ReaderConflictError(document.id, expected=expected, actual=document.row_version)


def _document_from_row(row: sqlite3.Row) -> ReaderDocument:
    return ReaderDocument(
        id=str(row["id"]),
        title=str(row["title"]),
        source_type=SourceType(row["source_type"]),
        source_name=row["source_name"],
        source_uri=row["source_uri"],
        source_sha256=row["source_sha256"],
        language_hint=row["language_hint"],
        state=DocumentState(row["state"]),
        created_at=_time_load(row["created_at"]),
        updated_at=_time_load(row["updated_at"]),
        imported_at=_time_load(row["imported_at"]),
        deleted_at=_time_load(row["deleted_at"]) if row["deleted_at"] else None,
        content_revision=int(row["content_revision"]),
        row_version=int(row["row_version"]),
        total_sections=int(row["total_sections"]),
        total_blocks=int(row["total_blocks"]),
        total_characters=int(row["total_characters"]),
        metadata=_json_load(row["metadata_json"]),
    )


def _section_from_row(row: sqlite3.Row) -> ReaderSection:
    return ReaderSection(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        parent_section_id=row["parent_section_id"],
        ordinal=int(row["ordinal"]),
        level=int(row["level"]),
        heading=row["heading"],
        first_block_ordinal=int(row["first_block_ordinal"]),
        metadata=_json_load(row["metadata_json"]),
    )


def _block_from_row(row: sqlite3.Row) -> ReaderBlock:
    return ReaderBlock(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        section_id=row["section_id"],
        ordinal=int(row["ordinal"]),
        kind=BlockKind(row["kind"]),
        text=str(row["text"]),
        character_count=int(row["character_count"]),
        content_sha256=str(row["content_sha256"]),
        row_version=int(row["row_version"]),
        metadata=_json_load(row["metadata_json"]),
    )


def _edit_from_row(row: sqlite3.Row) -> DocumentEdit:
    return DocumentEdit(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        sequence=int(row["sequence"]),
        base_content_revision=int(row["base_content_revision"]),
        result_content_revision=int(row["result_content_revision"]),
        block_id=str(row["block_id"]),
        start_offset=int(row["start_offset"]),
        end_offset=int(row["end_offset"]),
        original_text=str(row["original_text"]),
        replacement_text=str(row["replacement_text"]),
        operation_type=EditOperation(row["operation_type"]),
        created_at=_time_load(row["created_at"]),
        applied=bool(row["applied"]),
        undone_at=_time_load(row["undone_at"]) if row["undone_at"] else None,
        metadata=_json_load(row["metadata_json"]),
    )


def _cursor_from_row(row: sqlite3.Row) -> ReaderCursor:
    return ReaderCursor(
        document_id=str(row["document_id"]),
        block_id=str(row["block_id"]),
        block_ordinal=int(row["block_ordinal"]),
        character_offset=int(row["character_offset"]),
        content_revision=int(row["content_revision"]),
        segment_index=int(row["segment_index"]) if row["segment_index"] is not None else None,
    )


def _position_from_row(row: sqlite3.Row) -> PlaybackPosition:
    return PlaybackPosition(
        document_id=str(row["document_id"]),
        cursor=_cursor_from_row(row),
        voice_profile_id=row["voice_profile_id"],
        pipeline_version=int(row["pipeline_version"]),
        rules_version=int(row["rules_version"]),
        updated_at=_time_load(row["updated_at"]),
        completed=bool(row["completed"]),
        row_version=int(row["row_version"]),
    )


def _bookmark_from_row(row: sqlite3.Row) -> Bookmark:
    return Bookmark(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        cursor=_cursor_from_row(row),
        label=str(row["label"]),
        note=str(row["note"]),
        created_at=_time_load(row["created_at"]),
        updated_at=_time_load(row["updated_at"]),
        row_version=int(row["row_version"]),
    )


def _queue_from_row(row: sqlite3.Row) -> QueueItem:
    return QueueItem(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        ordinal=int(row["ordinal"]),
        status=QueueStatus(row["status"]),
        added_at=_time_load(row["added_at"]),
        updated_at=_time_load(row["updated_at"]),
        row_version=int(row["row_version"]),
    )


def _block_values(block: ReaderBlock) -> tuple[Any, ...]:
    return (
        block.id,
        block.document_id,
        block.section_id,
        block.ordinal,
        block.kind.value,
        block.text,
        block.character_count,
        block.content_sha256,
        block.row_version,
        _json_dump(block.metadata),
    )


def _position_values(position: PlaybackPosition) -> tuple[Any, ...]:
    return (
        position.document_id,
        position.cursor.block_id,
        position.cursor.block_ordinal,
        position.cursor.character_offset,
        position.cursor.content_revision,
        position.cursor.segment_index,
        position.voice_profile_id,
        position.pipeline_version,
        position.rules_version,
        _time_dump(position.updated_at),
        int(position.completed),
        position.row_version,
    )


def _position_update_values(position: PlaybackPosition) -> tuple[Any, ...]:
    values = _position_values(position)
    return values[1:] + (position.document_id,)


def _bookmark_values(bookmark: Bookmark) -> tuple[Any, ...]:
    return (
        bookmark.id,
        bookmark.document_id,
        bookmark.cursor.block_id,
        bookmark.cursor.block_ordinal,
        bookmark.cursor.character_offset,
        bookmark.cursor.content_revision,
        bookmark.cursor.segment_index,
        bookmark.label,
        bookmark.note,
        _time_dump(bookmark.created_at),
        _time_dump(bookmark.updated_at),
        bookmark.row_version,
    )


def _encode_page_cursor(updated_at: str, document_id: str) -> str:
    payload = json.dumps([updated_at, document_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_page_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(v, str) for v in value)
        ):
            raise ValueError
        return value[0], value[1]
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ReaderValidationError("document page cursor is invalid") from exc


def _json_dump(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ReaderValidationError("Reader metadata must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > 65_536:
        raise ReaderValidationError("Reader metadata must not exceed 64 KiB")
    return encoded


def _json_load(value: str) -> Mapping[str, Any]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ReaderDatabaseError("Reader metadata JSON must contain an object")
    return decoded


def _time_dump(value: datetime) -> str:
    if value.tzinfo is None:
        raise ReaderValidationError("Reader timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat()


def _time_load(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ReaderDatabaseError("Reader timestamp is missing its timezone")
    return result.astimezone(timezone.utc)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
