from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
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
    ExportAudioFormat,
    ExportPhase,
    ExportStatus,
    HighlighterConfiguration,
    HighlighterTerm,
    PlaybackPosition,
    QueueItem,
    QueueStatus,
    ReaderBlock,
    ReaderCursor,
    ReaderDatabaseReport,
    ReaderDesktopOpenRequest,
    ReaderDocument,
    ReaderDocumentBundle,
    ReaderExportJob,
    ReaderSection,
    RuleScope,
    RuleStage,
    RuleType,
    SourceType,
    SpeechRule,
    SpeechRuleSet,
    utc_now,
)
from ..plain_text import split_plain_text_paragraphs
from .connection import connect_sqlite
from .migrations import apply_migrations


@dataclass(frozen=True)
class _AppendedBlockSpec:
    id: str
    ordinal: int
    section_id: str | None
    kind: str
    text: str


@dataclass(frozen=True)
class _RangeBlockSnapshot:
    id: str
    ordinal: int
    section_id: str | None
    kind: str
    text: str
    row_version: int
    metadata: Mapping[str, Any]


def _appended_block_metadata(
    specs: tuple[_AppendedBlockSpec, ...],
) -> list[dict[str, Any]]:
    metadata: list[dict[str, Any]] = []
    text_start = 0
    for spec in specs:
        metadata.append(
            {
                "id": spec.id,
                "ordinal": spec.ordinal,
                "section_id": spec.section_id,
                "kind": spec.kind,
                "text_start": text_start,
                "text_length": len(spec.text),
            }
        )
        text_start += len(spec.text) + 2
    return metadata


def _appended_block_specs(edit: DocumentEdit) -> tuple[_AppendedBlockSpec, ...]:
    metadata = dict(edit.metadata)
    raw_blocks = metadata.get("blocks")
    if raw_blocks is None:
        try:
            kind = BlockKind(str(metadata.get("kind", BlockKind.PARAGRAPH.value))).value
            ordinal = int(metadata["ordinal"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ReaderStaleCursorError("append history metadata is invalid") from exc
        return (
            _AppendedBlockSpec(
                id=edit.block_id,
                ordinal=ordinal,
                section_id=(
                    str(metadata["section_id"])
                    if metadata.get("section_id") is not None
                    else None
                ),
                kind=kind,
                text=edit.replacement_text,
            ),
        )
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ReaderStaleCursorError("append history block metadata is invalid")

    specs: list[_AppendedBlockSpec] = []
    try:
        for raw in raw_blocks:
            if not isinstance(raw, Mapping):
                raise TypeError("block metadata must be an object")
            block_id = str(raw["id"])
            ordinal = int(raw["ordinal"])
            text_start = int(raw["text_start"])
            text_length = int(raw["text_length"])
            kind = BlockKind(str(raw.get("kind", BlockKind.PARAGRAPH.value))).value
            if not block_id or ordinal < 0 or text_start < 0 or text_length <= 0:
                raise ValueError("block metadata is outside its valid range")
            text = edit.replacement_text[text_start : text_start + text_length]
            if len(text) != text_length:
                raise ValueError("block metadata extends past the appended text")
            specs.append(
                _AppendedBlockSpec(
                    id=block_id,
                    ordinal=ordinal,
                    section_id=(
                        str(raw["section_id"])
                        if raw.get("section_id") is not None
                        else None
                    ),
                    kind=kind,
                    text=text,
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReaderStaleCursorError("append history block metadata is invalid") from exc

    result = tuple(specs)
    if (
        result[0].id != edit.block_id
        or len({spec.id for spec in result}) != len(result)
        or any(spec.ordinal != result[0].ordinal + index for index, spec in enumerate(result))
        or "\n\n".join(spec.text for spec in result) != edit.replacement_text
    ):
        raise ReaderStaleCursorError("append history block metadata is inconsistent")
    return result


def _range_delete_metadata(
    snapshots: tuple[_RangeBlockSnapshot, ...],
) -> tuple[str, dict[str, Any]]:
    original_text = "\n\n".join(snapshot.text for snapshot in snapshots)
    text_start = 0
    blocks: list[dict[str, Any]] = []
    for snapshot in snapshots:
        blocks.append(
            {
                "id": snapshot.id,
                "ordinal": snapshot.ordinal,
                "section_id": snapshot.section_id,
                "kind": snapshot.kind,
                "text_start": text_start,
                "text_length": len(snapshot.text),
                "row_version": snapshot.row_version,
                "metadata": dict(snapshot.metadata),
            }
        )
        text_start += len(snapshot.text) + 2
    return original_text, {
        "range_delete": True,
        "end_block_id": snapshots[-1].id,
        "blocks": blocks,
    }


def _is_range_delete(edit: DocumentEdit) -> bool:
    return edit.operation_type is EditOperation.REPLACE and edit.metadata.get(
        "range_delete"
    ) is True


def _range_delete_end_offset(edit: DocumentEdit) -> int:
    try:
        end_offset = int(edit.metadata["range_end_offset"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReaderStaleCursorError("range-delete end offset is invalid") from exc
    if end_offset < 0:
        raise ReaderStaleCursorError("range-delete end offset is invalid")
    return end_offset


def _range_delete_snapshots(edit: DocumentEdit) -> tuple[_RangeBlockSnapshot, ...]:
    raw_blocks = edit.metadata.get("blocks")
    if not _is_range_delete(edit) or not isinstance(raw_blocks, list) or len(raw_blocks) < 2:
        raise ReaderStaleCursorError("range-delete history metadata is invalid")

    snapshots: list[_RangeBlockSnapshot] = []
    try:
        for raw in raw_blocks:
            if not isinstance(raw, Mapping):
                raise TypeError("block snapshot must be an object")
            text_start = int(raw["text_start"])
            text_length = int(raw["text_length"])
            text = edit.original_text[text_start : text_start + text_length]
            metadata = raw.get("metadata", {})
            if (
                text_start < 0
                or text_length < 0
                or len(text) != text_length
                or not isinstance(metadata, Mapping)
            ):
                raise ValueError("block snapshot is outside its valid range")
            snapshots.append(
                _RangeBlockSnapshot(
                    id=str(raw["id"]),
                    ordinal=int(raw["ordinal"]),
                    section_id=(
                        str(raw["section_id"])
                        if raw.get("section_id") is not None
                        else None
                    ),
                    kind=BlockKind(str(raw["kind"])).value,
                    text=text,
                    row_version=int(raw["row_version"]),
                    metadata=dict(metadata),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReaderStaleCursorError("range-delete history metadata is invalid") from exc

    result = tuple(snapshots)
    range_end_offset = _range_delete_end_offset(edit)
    if (
        result[0].id != edit.block_id
        or edit.metadata.get("end_block_id") != result[-1].id
        or len({snapshot.id for snapshot in result}) != len(result)
        or any(
            snapshot.ordinal != result[0].ordinal + index
            for index, snapshot in enumerate(result)
        )
        or any(snapshot.section_id != result[0].section_id for snapshot in result)
        or "\n\n".join(snapshot.text for snapshot in result) != edit.original_text
        or edit.start_offset > len(result[0].text)
        or range_end_offset > len(result[-1].text)
        or edit.replacement_text
        != result[0].text[: edit.start_offset] + result[-1].text[range_end_offset:]
    ):
        raise ReaderStaleCursorError("range-delete history metadata is inconsistent")
    return result


def _remap_cursor_for_range_delete(
    cursor: ReaderCursor,
    edit: DocumentEdit,
    snapshots: tuple[_RangeBlockSnapshot, ...],
    *,
    forward: bool,
    new_revision: int,
) -> ReaderCursor:
    first = snapshots[0]
    last = snapshots[-1]
    range_end_offset = _range_delete_end_offset(edit)
    snapshot_ids = {snapshot.id for snapshot in snapshots}
    if forward:
        if cursor.block_id == first.id:
            offset = min(cursor.character_offset, edit.start_offset)
            mapped = replace(
                cursor,
                block_id=first.id,
                block_ordinal=first.ordinal,
                character_offset=offset,
            )
        elif cursor.block_id == last.id and cursor.character_offset > range_end_offset:
            mapped = replace(
                cursor,
                block_id=first.id,
                block_ordinal=first.ordinal,
                character_offset=(
                    edit.start_offset + cursor.character_offset - range_end_offset
                ),
            )
        elif cursor.block_id in snapshot_ids:
            mapped = replace(
                cursor,
                block_id=first.id,
                block_ordinal=first.ordinal,
                character_offset=edit.start_offset,
            )
        else:
            mapped = cursor
    elif cursor.block_id == first.id and cursor.character_offset > edit.start_offset:
        mapped = replace(
            cursor,
            block_id=last.id,
            block_ordinal=last.ordinal,
            character_offset=(
                range_end_offset + cursor.character_offset - edit.start_offset
            ),
        )
    else:
        mapped = cursor
    return replace(mapped, content_revision=new_revision, segment_index=None)


class SqliteReaderRepository:
    def __init__(
        self,
        database_path: str | Path,
        *,
        max_edit_history_operations: int = 1000,
        max_edit_history_bytes: int = 10_485_760,
        enable_fts: bool = True,
        initialize: bool = True,
    ) -> None:
        if max_edit_history_operations <= 0 or max_edit_history_bytes <= 0:
            raise ReaderValidationError("Reader edit-history limits must be positive")
        self.database_path = Path(database_path).resolve()
        self.max_edit_history_operations = max_edit_history_operations
        self.max_edit_history_bytes = max_edit_history_bytes
        self._search_available = False
        if initialize:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection:
                apply_migrations(connection)
                self._search_available = enable_fts and _initialize_search_index(connection)

    @property
    def search_available(self) -> bool:
        return self._search_available

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
        query: str | None = None,
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
        if query is not None and query.strip():
            cleaned_query = query.strip()
            fts_query = _fts_query(cleaned_query) if self._search_available else None
            if fts_query is not None:
                clauses.append(
                    "id IN (SELECT document_id FROM reader_document_search "
                    "WHERE reader_document_search MATCH ?)"
                )
                parameters.append(fts_query)
            else:
                escaped_query = _escape_like(cleaned_query)
                clauses.append(
                    "(title LIKE ? ESCAPE '\\' OR COALESCE(source_name, '') LIKE ? "
                    "ESCAPE '\\' OR EXISTS (SELECT 1 FROM reader_blocks AS search_block "
                    "WHERE search_block.document_id = reader_documents.id "
                    "AND search_block.text LIKE ? ESCAPE '\\'))"
                )
                pattern = f"%{escaped_query}%"
                parameters.extend((pattern, pattern, pattern))
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

    def find_document_by_source_hash(self, source_sha256: str) -> ReaderDocument | None:
        if not source_sha256.strip():
            raise ReaderValidationError("source hash must not be empty")
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM reader_documents
                WHERE source_sha256 = ? AND deleted_at IS NULL
                ORDER BY created_at, id LIMIT 1
                """,
                (source_sha256,),
            ).fetchone()
            return _document_from_row(row) if row is not None else None

    def document_counts_by_state(self) -> dict[DocumentState, int]:
        counts = {state: 0 for state in DocumentState}
        with self._connection() as connection:
            for row in connection.execute(
                """
                SELECT state, COUNT(*) AS total FROM reader_documents
                WHERE deleted_at IS NULL GROUP BY state
                """
            ):
                counts[DocumentState(row["state"])] = int(row["total"])
        return counts

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

    def delete_block_range(
        self,
        document_id: str,
        start_block_id: str,
        end_block_id: str,
        *,
        start_offset: int,
        end_offset: int,
        expected_row_version: int,
    ) -> tuple[ReaderDocument, DocumentEdit]:
        if start_block_id == end_block_id:
            return self.replace_block_text(
                document_id,
                start_block_id,
                start_offset=start_offset,
                end_offset=end_offset,
                replacement_text="",
                expected_row_version=expected_row_version,
            )

        with self._write() as connection:
            document = self._require_editable_document(connection, document_id)
            _check_version(document, expected_row_version)
            endpoints = list(
                connection.execute(
                    """
                    SELECT * FROM reader_blocks
                    WHERE document_id = ? AND id IN (?, ?)
                    ORDER BY ordinal
                    """,
                    (document_id, start_block_id, end_block_id),
                )
            )
            if len(endpoints) != 2:
                missing = start_block_id if not endpoints else end_block_id
                raise ReaderNotFoundError(f"Reader block not found: {missing}")
            start_block = _block_from_row(endpoints[0])
            end_block = _block_from_row(endpoints[1])
            if start_block.id != start_block_id or end_block.id != end_block_id:
                raise ReaderValidationError("range-delete blocks are in reverse order")
            if start_block.section_id != end_block.section_id:
                raise ReaderValidationError("range deletion cannot cross document sections")
            if start_offset < 0 or start_offset > len(start_block.text):
                raise ReaderValidationError("range-delete start offset exceeds block text")
            if end_offset < 0 or end_offset > len(end_block.text):
                raise ReaderValidationError("range-delete end offset exceeds block text")

            rows = list(
                connection.execute(
                    """
                    SELECT * FROM reader_blocks
                    WHERE document_id = ? AND ordinal BETWEEN ? AND ?
                    ORDER BY ordinal
                    """,
                    (document_id, start_block.ordinal, end_block.ordinal),
                )
            )
            snapshots = tuple(
                _RangeBlockSnapshot(
                    id=block.id,
                    ordinal=block.ordinal,
                    section_id=block.section_id,
                    kind=block.kind.value,
                    text=block.text,
                    row_version=block.row_version,
                    metadata=block.metadata,
                )
                for block in (_block_from_row(row) for row in rows)
            )
            original_text, metadata = _range_delete_metadata(snapshots)
            metadata["range_end_offset"] = end_offset
            merged_text = start_block.text[:start_offset] + end_block.text[end_offset:]
            new_revision = document.content_revision + 1
            now = utc_now()
            self._discard_redo(connection, document_id)
            edit = DocumentEdit(
                id=str(uuid.uuid4()),
                document_id=document_id,
                sequence=self._next_edit_sequence(connection, document_id),
                base_content_revision=document.content_revision,
                result_content_revision=new_revision,
                block_id=start_block_id,
                start_offset=start_offset,
                end_offset=max(start_offset, end_offset),
                original_text=original_text,
                replacement_text=merged_text,
                operation_type=EditOperation.REPLACE,
                created_at=now,
                metadata=metadata,
            )
            block_delta, character_delta = self._apply_range_delete_forward(
                connection,
                edit,
                new_revision,
            )
            self._update_document_content(
                connection,
                document,
                new_revision=new_revision,
                block_delta=block_delta,
                character_delta=character_delta,
                now=now,
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
        try:
            paragraphs = split_plain_text_paragraphs(text)
        except ReaderValidationError:
            raise ReaderValidationError("appended text must not be empty") from None
        normalized = "\n\n".join(paragraphs)
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
            first_ordinal = int(last["ordinal"]) + 1
            section_id = last["section_id"]
            block_specs = tuple(
                _AppendedBlockSpec(
                    id=str(uuid.uuid4()),
                    ordinal=first_ordinal + index,
                    section_id=section_id,
                    kind=BlockKind.PARAGRAPH.value,
                    text=paragraph,
                )
                for index, paragraph in enumerate(paragraphs)
            )
            block_id = block_specs[0].id
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
                    "ordinal": first_ordinal,
                    "kind": BlockKind.PARAGRAPH.value,
                    "blocks": _appended_block_metadata(block_specs),
                },
            )
            connection.executemany(
                """
                INSERT INTO reader_blocks(
                    id, document_id, section_id, ordinal, kind, text,
                    character_count, content_sha256, row_version, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, '{}')
                """,
                [
                    (
                        spec.id,
                        document_id,
                        spec.section_id,
                        spec.ordinal,
                        spec.kind,
                        spec.text,
                        len(spec.text),
                        _sha256(spec.text),
                    )
                    for spec in block_specs
                ],
            )
            self._update_document_content(
                connection,
                document,
                new_revision=new_revision,
                block_delta=len(block_specs),
                character_delta=sum(len(spec.text) for spec in block_specs),
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
                if _is_range_delete(edit):
                    block_delta, character_delta = self._apply_range_delete_inverse(
                        connection,
                        edit,
                        new_revision,
                    )
                else:
                    self._apply_replace_inverse(connection, edit, new_revision)
                    character_delta = len(edit.original_text) - len(edit.replacement_text)
                    block_delta = 0
            else:
                block_count, character_count = self._remove_appended_blocks(
                    connection,
                    edit,
                    new_revision,
                )
                character_delta = -character_count
                block_delta = -block_count
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
                if _is_range_delete(edit):
                    block_delta, character_delta = self._apply_range_delete_forward(
                        connection,
                        edit,
                        new_revision,
                    )
                else:
                    self._apply_replace_forward(connection, edit, new_revision)
                    character_delta = len(edit.replacement_text) - len(edit.original_text)
                    block_delta = 0
            else:
                block_count, character_count = self._restore_appended_blocks(connection, edit)
                self._advance_saved_cursor_revisions(connection, document_id, new_revision)
                character_delta = character_count
                block_delta = block_count
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

    def get_bookmark(self, bookmark_id: str) -> Bookmark:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM reader_bookmarks WHERE id = ?", (bookmark_id,)
            ).fetchone()
            if row is None:
                raise ReaderNotFoundError(f"Reader bookmark not found: {bookmark_id}")
            return _bookmark_from_row(row)

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

    def activate_queue_item(self, item_id: str) -> QueueItem:
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM reader_queue_items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise ReaderNotFoundError(f"Reader queue item not found: {item_id}")
            now = _time_dump(utc_now())
            connection.execute(
                """
                UPDATE reader_queue_items
                SET status = 'queued', updated_at = ?, row_version = row_version + 1
                WHERE status = 'playing' AND id <> ?
                """,
                (now, item_id),
            )
            connection.execute(
                """
                UPDATE reader_queue_items
                SET status = 'playing', updated_at = ?, row_version = row_version + 1
                WHERE id = ? AND status <> 'playing'
                """,
                (now, item_id),
            )
            refreshed = connection.execute(
                "SELECT * FROM reader_queue_items WHERE id = ?", (item_id,)
            ).fetchone()
            assert refreshed is not None
            return _queue_from_row(refreshed)

    def advance_queue(self, document_id: str) -> QueueItem | None:
        with self._write() as connection:
            current_row = connection.execute(
                """
                SELECT * FROM reader_queue_items
                WHERE document_id = ? AND status = 'playing'
                ORDER BY ordinal LIMIT 1
                """,
                (document_id,),
            ).fetchone()
            if current_row is None:
                return None
            current = _queue_from_row(current_row)
            now = _time_dump(utc_now())
            connection.execute(
                """
                UPDATE reader_queue_items
                SET status = 'completed', updated_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (now, current.id),
            )
            next_row = connection.execute(
                """
                SELECT queue.* FROM reader_queue_items AS queue
                JOIN reader_documents AS document ON document.id = queue.document_id
                WHERE queue.ordinal > ? AND queue.status = 'queued'
                  AND document.deleted_at IS NULL
                ORDER BY queue.ordinal LIMIT 1
                """,
                (current.ordinal,),
            ).fetchone()
            if next_row is None:
                return None
            connection.execute(
                """
                UPDATE reader_queue_items
                SET status = 'playing', updated_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (now, next_row["id"]),
            )
            refreshed = connection.execute(
                "SELECT * FROM reader_queue_items WHERE id = ?", (next_row["id"],)
            ).fetchone()
            assert refreshed is not None
            return _queue_from_row(refreshed)

    def request_desktop_open(
        self,
        request: ReaderDesktopOpenRequest,
    ) -> ReaderDesktopOpenRequest:
        with self._write() as connection:
            document = self._require_document(connection, request.document_id)
            if document.deleted_at is not None:
                raise ReaderValidationError("soft-deleted documents cannot be opened")
            existing = connection.execute(
                "SELECT * FROM reader_desktop_open_requests WHERE document_id = ?",
                (request.document_id,),
            ).fetchone()
            if existing is not None:
                return _desktop_open_request_from_row(existing)
            connection.execute(
                """
                INSERT INTO reader_desktop_open_requests(id, document_id, created_at)
                VALUES (?, ?, ?)
                """,
                (request.id, request.document_id, _time_dump(request.created_at)),
            )
            return request

    def peek_desktop_open_request(self) -> ReaderDesktopOpenRequest | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT request.* FROM reader_desktop_open_requests AS request
                JOIN reader_documents AS document ON document.id = request.document_id
                WHERE document.deleted_at IS NULL
                ORDER BY request.created_at, request.id LIMIT 1
                """
            ).fetchone()
            return _desktop_open_request_from_row(row) if row is not None else None

    def acknowledge_desktop_open_request(self, request_id: str) -> None:
        with self._write() as connection:
            deleted = connection.execute(
                "DELETE FROM reader_desktop_open_requests WHERE id = ?",
                (request_id,),
            ).rowcount
            if deleted == 0:
                raise ReaderNotFoundError(
                    f"Reader desktop open request not found: {request_id}"
                )

    def create_export_job(self, job: ReaderExportJob) -> ReaderExportJob:
        with self._write() as connection:
            for document_id in job.document_ids:
                document = self._require_document(connection, document_id)
                if document.deleted_at is not None:
                    raise ReaderValidationError("soft-deleted documents cannot be exported")
            connection.execute(
                """
                INSERT INTO reader_export_jobs(
                    id, status, document_ids_json, section_ids_json,
                    start_cursor_json, end_cursor_json, voice_id, audio_format,
                    progress_phase, progress_percent, output_basename,
                    overwrite_existing, total_documents, completed_documents,
                    current_document_id, output_files_json, error_type,
                    error_message, cancel_requested, created_at, updated_at,
                    completed_at, row_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _export_values(job),
            )
        return job

    def get_export_job(self, job_id: str) -> ReaderExportJob:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM reader_export_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise ReaderNotFoundError(f"Reader export job not found: {job_id}")
            return _export_from_row(row)

    def list_export_jobs(
        self,
        statuses: tuple[ExportStatus, ...] | None = None,
        *,
        limit: int = 100,
    ) -> tuple[ReaderExportJob, ...]:
        if limit <= 0 or limit > 1000:
            raise ReaderValidationError("export job list limit is invalid")
        parameters: list[object] = []
        where = ""
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where = f"WHERE status IN ({placeholders})"
            parameters.extend(status.value for status in statuses)
        parameters.append(limit)
        with self._connection() as connection:
            return tuple(
                _export_from_row(row)
                for row in connection.execute(
                    f"SELECT * FROM reader_export_jobs {where} "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    parameters,
                )
            )

    def claim_export_job(self, job_id: str) -> ReaderExportJob:
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM reader_export_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise ReaderNotFoundError(f"Reader export job not found: {job_id}")
            current = _export_from_row(row)
            if current.status is not ExportStatus.QUEUED or current.cancel_requested:
                return current
            connection.execute(
                """
                UPDATE reader_export_jobs
                SET status = 'running', progress_phase = 'preparing',
                    progress_percent = 0, completed_documents = 0,
                    current_document_id = NULL, output_files_json = '[]',
                    updated_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (_time_dump(utc_now()), job_id),
            )
            return _require_export_job(connection, job_id)

    def update_export_progress(
        self,
        job_id: str,
        *,
        completed_documents: int,
        current_document_id: str | None,
        output_files: tuple[str, ...],
        progress_phase: ExportPhase,
        progress_percent: int,
    ) -> ReaderExportJob:
        with self._write() as connection:
            current = _require_export_job(connection, job_id)
            if current.status is not ExportStatus.RUNNING:
                return current
            if not 0 <= completed_documents <= current.total_documents:
                raise ReaderValidationError("export progress is invalid")
            if not current.progress_percent <= progress_percent <= 100:
                raise ReaderValidationError("export percentage must be monotonic")
            connection.execute(
                """
                UPDATE reader_export_jobs
                SET completed_documents = ?, current_document_id = ?,
                    output_files_json = ?, progress_phase = ?, progress_percent = ?,
                    updated_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (
                    completed_documents,
                    current_document_id,
                    _json_dump(output_files),
                    progress_phase.value,
                    progress_percent,
                    _time_dump(utc_now()),
                    job_id,
                ),
            )
            return _require_export_job(connection, job_id)

    def finish_export_job(
        self,
        job_id: str,
        *,
        status: ExportStatus,
        output_files: tuple[str, ...] = (),
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> ReaderExportJob:
        if status not in {
            ExportStatus.COMPLETED,
            ExportStatus.FAILED,
            ExportStatus.CANCELLED,
        }:
            raise ReaderValidationError("export terminal status is invalid")
        with self._write() as connection:
            current = _require_export_job(connection, job_id)
            if current.status in {
                ExportStatus.COMPLETED,
                ExportStatus.FAILED,
                ExportStatus.CANCELLED,
            }:
                return current
            now = utc_now()
            connection.execute(
                """
                UPDATE reader_export_jobs
                SET status = ?, completed_documents = ?, current_document_id = NULL,
                    output_files_json = ?, error_type = ?, error_message = ?,
                    progress_phase = ?, progress_percent = ?, updated_at = ?,
                    completed_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (
                    status.value,
                    (
                        len(output_files)
                        if status is ExportStatus.COMPLETED
                        else current.completed_documents
                    ),
                    _json_dump(output_files),
                    error_type,
                    error_message,
                    status.value,
                    100 if status is ExportStatus.COMPLETED else current.progress_percent,
                    _time_dump(now),
                    _time_dump(now),
                    job_id,
                ),
            )
            return _require_export_job(connection, job_id)

    def request_export_cancel(self, job_id: str) -> ReaderExportJob:
        with self._write() as connection:
            current = _require_export_job(connection, job_id)
            if current.status in {
                ExportStatus.COMPLETED,
                ExportStatus.FAILED,
                ExportStatus.CANCELLED,
            }:
                return current
            now = utc_now()
            if current.status is ExportStatus.QUEUED:
                connection.execute(
                    """
                    UPDATE reader_export_jobs
                    SET status = 'cancelled', cancel_requested = 1,
                        progress_phase = 'cancelled',
                        updated_at = ?, completed_at = ?, row_version = row_version + 1
                    WHERE id = ?
                    """,
                    (_time_dump(now), _time_dump(now), job_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE reader_export_jobs
                    SET cancel_requested = 1, updated_at = ?, row_version = row_version + 1
                    WHERE id = ?
                    """,
                    (_time_dump(now), job_id),
                )
            return _require_export_job(connection, job_id)

    def delete_export_job(self, job_id: str) -> None:
        with self._write() as connection:
            current = _require_export_job(connection, job_id)
            if current.status in {ExportStatus.QUEUED, ExportStatus.RUNNING}:
                raise ReaderValidationError(
                    "active exports must be cancelled before deletion"
                )
            connection.execute(
                "DELETE FROM reader_export_jobs WHERE id = ?",
                (job_id,),
            )

    def recover_export_jobs(self) -> tuple[ReaderExportJob, ...]:
        with self._write() as connection:
            connection.execute(
                """
                UPDATE reader_export_jobs
                SET status = 'queued', completed_documents = 0,
                    current_document_id = NULL, output_files_json = '[]',
                    progress_phase = 'queued', progress_percent = 0,
                    updated_at = ?, row_version = row_version + 1
                WHERE status = 'running' AND cancel_requested = 0
                """,
                (_time_dump(utc_now()),),
            )
            connection.execute(
                """
                UPDATE reader_export_jobs
                SET status = 'cancelled', current_document_id = NULL,
                    progress_phase = 'cancelled',
                    completed_at = ?, updated_at = ?, row_version = row_version + 1
                WHERE status IN ('queued', 'running') AND cancel_requested = 1
                """,
                (_time_dump(utc_now()), _time_dump(utc_now())),
            )
            return tuple(
                _export_from_row(row)
                for row in connection.execute(
                    "SELECT * FROM reader_export_jobs WHERE status = 'queued' ORDER BY created_at"
                )
            )

    def create_rule_set(self, rule_set: SpeechRuleSet) -> SpeechRuleSet:
        with self._write() as connection:
            connection.execute(
                """
                INSERT INTO reader_rule_sets(
                    id, name, description, enabled, scope, source_sha256,
                    version, row_version, created_at, updated_at,
                    raw_import_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _rule_set_values(rule_set),
            )
            self._bump_rules_version(connection)
        return rule_set

    def get_rule_set(self, rule_set_id: str) -> SpeechRuleSet:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM reader_rule_sets WHERE id = ?",
                (rule_set_id,),
            ).fetchone()
            if row is None:
                raise ReaderNotFoundError("rule set", rule_set_id)
            return _rule_set_from_row(row)

    def list_rule_sets(self) -> tuple[SpeechRuleSet, ...]:
        with self._connection() as connection:
            return tuple(
                _rule_set_from_row(row)
                for row in connection.execute(
                    "SELECT * FROM reader_rule_sets ORDER BY scope, created_at, id"
                )
            )

    def update_rule_set(
        self,
        rule_set: SpeechRuleSet,
        *,
        expected_row_version: int,
    ) -> SpeechRuleSet:
        with self._write() as connection:
            current = connection.execute(
                "SELECT * FROM reader_rule_sets WHERE id = ?",
                (rule_set.id,),
            ).fetchone()
            if current is None:
                raise ReaderNotFoundError("rule set", rule_set.id)
            if int(current["row_version"]) != expected_row_version:
                raise ReaderConflictError(
                    rule_set.id,
                    expected=expected_row_version,
                    actual=int(current["row_version"]),
                )
            updated = replace(
                rule_set,
                created_at=_time_load(current["created_at"]),
                version=int(current["version"]) + 1,
                row_version=expected_row_version + 1,
                updated_at=utc_now(),
            )
            connection.execute(
                """
                UPDATE reader_rule_sets SET
                    name = ?, description = ?, enabled = ?, scope = ?,
                    source_sha256 = ?, version = ?, row_version = ?,
                    updated_at = ?, raw_import_metadata_json = ?
                WHERE id = ?
                """,
                (
                    updated.name,
                    updated.description,
                    int(updated.enabled),
                    updated.scope.value,
                    updated.source_sha256,
                    updated.version,
                    updated.row_version,
                    _time_dump(updated.updated_at),
                    _json_dump(updated.raw_import_metadata),
                    updated.id,
                ),
            )
            self._bump_rules_version(connection)
            return updated

    def delete_rule_set(self, rule_set_id: str, *, expected_row_version: int) -> None:
        with self._write() as connection:
            result = connection.execute(
                "DELETE FROM reader_rule_sets WHERE id = ? AND row_version = ?",
                (rule_set_id, expected_row_version),
            )
            if result.rowcount == 0:
                exists = connection.execute(
                    "SELECT 1 FROM reader_rule_sets WHERE id = ?", (rule_set_id,)
                ).fetchone()
                if exists is None:
                    raise ReaderNotFoundError("rule set", rule_set_id)
                actual = connection.execute(
                    "SELECT row_version FROM reader_rule_sets WHERE id = ?", (rule_set_id,)
                ).fetchone()
                raise ReaderConflictError(
                    rule_set_id,
                    expected=expected_row_version,
                    actual=int(actual["row_version"]),
                )
            self._bump_rules_version(connection)

    def create_rule(self, rule: SpeechRule) -> SpeechRule:
        with self._write() as connection:
            connection.execute(
                """
                INSERT INTO reader_speech_rules(
                    id, rule_set_id, name, enabled, stage, rule_type, pattern,
                    replacement, case_sensitive, whole_word, language_filter,
                    engine_filter, voice_filter, document_filter, priority,
                    regex_timeout_ms, row_version, created_at, updated_at,
                    raw_import_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _rule_values(rule),
            )
            self._touch_rule_set(connection, rule.rule_set_id)
            self._bump_rules_version(connection)
        return rule

    def get_rule(self, rule_id: str) -> SpeechRule:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM reader_speech_rules WHERE id = ?", (rule_id,)
            ).fetchone()
            if row is None:
                raise ReaderNotFoundError("speech rule", rule_id)
            return _rule_from_row(row)

    def list_rules(self, rule_set_ids: tuple[str, ...] | None = None) -> tuple[SpeechRule, ...]:
        with self._connection() as connection:
            if rule_set_ids is None:
                rows = connection.execute(
                    """
                    SELECT r.* FROM reader_speech_rules r
                    JOIN reader_rule_sets s ON s.id = r.rule_set_id
                    ORDER BY CASE s.scope
                        WHEN 'system' THEN 0 WHEN 'global' THEN 1
                        WHEN 'language' THEN 2 WHEN 'voice_engine' THEN 3 ELSE 4 END,
                        r.stage, r.priority, r.created_at, r.id
                    """
                )
            elif not rule_set_ids:
                return ()
            else:
                placeholders = ",".join("?" for _ in rule_set_ids)
                rows = connection.execute(
                    f"""
                    SELECT r.* FROM reader_speech_rules r
                    JOIN reader_rule_sets s ON s.id = r.rule_set_id
                    WHERE r.rule_set_id IN ({placeholders}) AND s.enabled = 1
                    ORDER BY CASE s.scope
                        WHEN 'system' THEN 0 WHEN 'global' THEN 1
                        WHEN 'language' THEN 2 WHEN 'voice_engine' THEN 3 ELSE 4 END,
                        r.stage, r.priority, r.created_at, r.id
                    """,
                    rule_set_ids,
                )
            return tuple(_rule_from_row(row) for row in rows)

    def update_rule(
        self,
        rule: SpeechRule,
        *,
        expected_row_version: int,
    ) -> SpeechRule:
        with self._write() as connection:
            current = connection.execute(
                "SELECT * FROM reader_speech_rules WHERE id = ?", (rule.id,)
            ).fetchone()
            if current is None:
                raise ReaderNotFoundError("speech rule", rule.id)
            if int(current["row_version"]) != expected_row_version:
                raise ReaderConflictError(
                    rule.id,
                    expected=expected_row_version,
                    actual=int(current["row_version"]),
                )
            updated = replace(
                rule,
                rule_set_id=str(current["rule_set_id"]),
                created_at=_time_load(current["created_at"]),
                updated_at=utc_now(),
                row_version=expected_row_version + 1,
            )
            connection.execute(
                """
                UPDATE reader_speech_rules SET
                    name = ?, enabled = ?, stage = ?, rule_type = ?, pattern = ?,
                    replacement = ?, case_sensitive = ?, whole_word = ?,
                    language_filter = ?, engine_filter = ?, voice_filter = ?,
                    document_filter = ?, priority = ?, regex_timeout_ms = ?,
                    row_version = ?, updated_at = ?, raw_import_metadata_json = ?
                WHERE id = ?
                """,
                (
                    updated.name,
                    int(updated.enabled),
                    updated.stage.value,
                    updated.rule_type.value,
                    updated.pattern,
                    updated.replacement,
                    int(updated.case_sensitive),
                    int(updated.whole_word),
                    updated.language_filter,
                    updated.engine_filter,
                    updated.voice_filter,
                    updated.document_filter,
                    updated.priority,
                    updated.regex_timeout_ms,
                    updated.row_version,
                    _time_dump(updated.updated_at),
                    _json_dump(updated.raw_import_metadata),
                    updated.id,
                ),
            )
            self._touch_rule_set(connection, updated.rule_set_id)
            self._bump_rules_version(connection)
            return updated

    def delete_rule(self, rule_id: str, *, expected_row_version: int) -> None:
        with self._write() as connection:
            current = connection.execute(
                "SELECT rule_set_id, row_version FROM reader_speech_rules WHERE id = ?",
                (rule_id,),
            ).fetchone()
            if current is None:
                raise ReaderNotFoundError("speech rule", rule_id)
            if int(current["row_version"]) != expected_row_version:
                raise ReaderConflictError(
                    rule_id,
                    expected=expected_row_version,
                    actual=int(current["row_version"]),
                )
            connection.execute("DELETE FROM reader_speech_rules WHERE id = ?", (rule_id,))
            self._touch_rule_set(connection, str(current["rule_set_id"]))
            self._bump_rules_version(connection)

    def get_rules_version(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT rules_version FROM reader_rule_state WHERE singleton_id = 1"
            ).fetchone()
            return int(row["rules_version"])

    def get_highlighter_configuration(self) -> HighlighterConfiguration:
        with self._connection() as connection:
            config = connection.execute(
                "SELECT * FROM reader_highlighter_config WHERE id = 'global'"
            ).fetchone()
            if config is None:
                raise ReaderDatabaseError("Reader highlighter configuration is missing")
            rows = connection.execute(
                """
                SELECT * FROM reader_highlighter_terms
                WHERE config_id = 'global'
                ORDER BY ordinal, id
                """
            )
            return HighlighterConfiguration(
                id=str(config["id"]),
                terms=tuple(_highlighter_term_from_row(row) for row in rows),
                row_version=int(config["row_version"]),
                updated_at=_time_load(config["updated_at"]),
            )

    def replace_highlighter_terms(
        self,
        terms: tuple[HighlighterTerm, ...],
        *,
        expected_row_version: int,
    ) -> HighlighterConfiguration:
        if len(terms) > 200:
            raise ReaderValidationError("highlighter configuration exceeds 200 terms")
        if len({term.normalized_term for term in terms}) != len(terms):
            raise ReaderValidationError("highlighter terms must be unique")
        if any(term.ordinal != index for index, term in enumerate(terms)):
            raise ReaderValidationError("highlighter term order must be contiguous")

        updated_at = utc_now()
        with self._write() as connection:
            config = connection.execute(
                "SELECT row_version FROM reader_highlighter_config WHERE id = 'global'"
            ).fetchone()
            if config is None:
                raise ReaderDatabaseError("Reader highlighter configuration is missing")
            actual_version = int(config["row_version"])
            if actual_version != expected_row_version:
                raise ReaderConflictError(
                    "highlighter-global",
                    expected=expected_row_version,
                    actual=actual_version,
                )
            connection.execute(
                "DELETE FROM reader_highlighter_terms WHERE config_id = 'global'"
            )
            connection.executemany(
                """
                INSERT INTO reader_highlighter_terms(
                    id, config_id, term, normalized_term, active, color,
                    ordinal, created_at, updated_at
                ) VALUES (?, 'global', ?, ?, ?, ?, ?, ?, ?)
                """,
                (_highlighter_term_values(term) for term in terms),
            )
            next_version = actual_version + 1
            connection.execute(
                """
                UPDATE reader_highlighter_config
                SET row_version = ?, updated_at = ?
                WHERE id = 'global'
                """,
                (next_version, _time_dump(updated_at)),
            )
        return HighlighterConfiguration(
            terms=terms,
            row_version=next_version,
            updated_at=updated_at,
        )

    def get_rule_import_report(
        self, target_rule_set_id: str, source_sha256: str
    ) -> Mapping[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT report_json FROM reader_rule_imports
                WHERE target_rule_set_id = ? AND source_sha256 = ?
                """,
                (target_rule_set_id, source_sha256),
            ).fetchone()
            return _json_load(row["report_json"]) if row is not None else None

    def record_rule_import(
        self,
        target_rule_set_id: str,
        source_sha256: str,
        report: Mapping[str, Any],
    ) -> None:
        with self._write() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO reader_rule_imports(
                    id, target_rule_set_id, source_sha256, imported_at, report_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    target_rule_set_id,
                    source_sha256,
                    _time_dump(utc_now()),
                    _json_dump(report),
                ),
            )

    @staticmethod
    def _touch_rule_set(connection: sqlite3.Connection, rule_set_id: str) -> None:
        result = connection.execute(
            """
            UPDATE reader_rule_sets
            SET version = version + 1, row_version = row_version + 1, updated_at = ?
            WHERE id = ?
            """,
            (_time_dump(utc_now()), rule_set_id),
        )
        if result.rowcount == 0:
            raise ReaderNotFoundError("rule set", rule_set_id)

    @staticmethod
    def _bump_rules_version(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            UPDATE reader_rule_state
            SET rules_version = rules_version + 1, updated_at = ?
            WHERE singleton_id = 1
            """,
            (_time_dump(utc_now()),),
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

    def _apply_range_delete_forward(
        self,
        connection: sqlite3.Connection,
        edit: DocumentEdit,
        new_revision: int,
    ) -> tuple[int, int]:
        snapshots = _range_delete_snapshots(edit)
        first_ordinal = snapshots[0].ordinal
        last_ordinal = snapshots[-1].ordinal
        rows = list(
            connection.execute(
                """
                SELECT id, ordinal, text FROM reader_blocks
                WHERE document_id = ? AND ordinal BETWEEN ? AND ?
                ORDER BY ordinal
                """,
                (edit.document_id, first_ordinal, last_ordinal),
            )
        )
        if len(rows) != len(snapshots) or any(
            str(row["id"]) != snapshot.id
            or int(row["ordinal"]) != snapshot.ordinal
            or str(row["text"]) != snapshot.text
            for row, snapshot in zip(rows, snapshots, strict=True)
        ):
            raise ReaderStaleCursorError("range-delete blocks no longer match edit history")

        self._remap_saved_cursors_for_range_delete(
            connection,
            edit,
            snapshots,
            forward=True,
            new_revision=new_revision,
        )
        connection.execute(
            """
            UPDATE reader_blocks
            SET text = ?, character_count = ?, content_sha256 = ?,
                row_version = row_version + 1
            WHERE id = ? AND document_id = ?
            """,
            (
                edit.replacement_text,
                len(edit.replacement_text),
                _sha256(edit.replacement_text),
                edit.block_id,
                edit.document_id,
            ),
        )
        connection.execute(
            """
            DELETE FROM reader_blocks
            WHERE document_id = ? AND ordinal > ? AND ordinal <= ?
            """,
            (edit.document_id, first_ordinal, last_ordinal),
        )
        removed_count = len(snapshots) - 1
        self._shift_following_block_ordinals(
            connection,
            edit.document_id,
            after_ordinal=last_ordinal,
            delta=-removed_count,
        )
        connection.execute(
            """
            UPDATE reader_sections
            SET first_block_ordinal = first_block_ordinal - ?
            WHERE document_id = ? AND first_block_ordinal > ?
            """,
            (removed_count, edit.document_id, last_ordinal),
        )
        return 1 - len(snapshots), len(edit.replacement_text) - sum(
            len(snapshot.text) for snapshot in snapshots
        )

    def _apply_range_delete_inverse(
        self,
        connection: sqlite3.Connection,
        edit: DocumentEdit,
        new_revision: int,
    ) -> tuple[int, int]:
        snapshots = _range_delete_snapshots(edit)
        first = snapshots[0]
        row = connection.execute(
            """
            SELECT text FROM reader_blocks
            WHERE id = ? AND document_id = ? AND ordinal = ?
            """,
            (first.id, edit.document_id, first.ordinal),
        ).fetchone()
        if row is None or str(row["text"]) != edit.replacement_text:
            raise ReaderStaleCursorError("range-delete result no longer matches undo history")
        for snapshot in snapshots[1:]:
            if connection.execute(
                "SELECT 1 FROM reader_blocks WHERE id = ? AND document_id = ?",
                (snapshot.id, edit.document_id),
            ).fetchone() is not None:
                raise ReaderStaleCursorError("range-delete blocks already exist during undo")

        restored_count = len(snapshots) - 1
        self._shift_following_block_ordinals(
            connection,
            edit.document_id,
            after_ordinal=first.ordinal,
            delta=restored_count,
        )
        connection.execute(
            """
            UPDATE reader_sections
            SET first_block_ordinal = first_block_ordinal + ?
            WHERE document_id = ? AND first_block_ordinal > ?
            """,
            (restored_count, edit.document_id, first.ordinal),
        )
        connection.execute(
            """
            UPDATE reader_blocks
            SET text = ?, character_count = ?, content_sha256 = ?,
                row_version = row_version + 1
            WHERE id = ? AND document_id = ?
            """,
            (
                first.text,
                len(first.text),
                _sha256(first.text),
                first.id,
                edit.document_id,
            ),
        )
        connection.executemany(
            """
            INSERT INTO reader_blocks(
                id, document_id, section_id, ordinal, kind, text,
                character_count, content_sha256, row_version, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    snapshot.id,
                    edit.document_id,
                    snapshot.section_id,
                    snapshot.ordinal,
                    snapshot.kind,
                    snapshot.text,
                    len(snapshot.text),
                    _sha256(snapshot.text),
                    snapshot.row_version + 1,
                    _json_dump(snapshot.metadata),
                )
                for snapshot in snapshots[1:]
            ],
        )
        self._remap_saved_cursors_for_range_delete(
            connection,
            edit,
            snapshots,
            forward=False,
            new_revision=new_revision,
        )
        return restored_count, sum(len(snapshot.text) for snapshot in snapshots) - len(
            edit.replacement_text
        )

    @staticmethod
    def _shift_following_block_ordinals(
        connection: sqlite3.Connection,
        document_id: str,
        *,
        after_ordinal: int,
        delta: int,
    ) -> None:
        if delta == 0:
            return
        temporary_offset = 1_000_000_000
        connection.execute(
            """
            UPDATE reader_blocks SET ordinal = ordinal + ?
            WHERE document_id = ? AND ordinal > ?
            """,
            (temporary_offset, document_id, after_ordinal),
        )
        connection.execute(
            """
            UPDATE reader_blocks SET ordinal = ordinal - ? + ?
            WHERE document_id = ? AND ordinal > ?
            """,
            (
                temporary_offset,
                delta,
                document_id,
                after_ordinal + temporary_offset,
            ),
        )

    def _remap_saved_cursors_for_range_delete(
        self,
        connection: sqlite3.Connection,
        edit: DocumentEdit,
        snapshots: tuple[_RangeBlockSnapshot, ...],
        *,
        forward: bool,
        new_revision: int,
    ) -> None:
        removed_count = len(snapshots) - 1
        snapshot_ids = {snapshot.id for snapshot in snapshots}

        def remap(cursor: ReaderCursor) -> ReaderCursor:
            mapped = _remap_cursor_for_range_delete(
                cursor,
                edit,
                snapshots,
                forward=forward,
                new_revision=new_revision,
            )
            if mapped.block_id not in snapshot_ids:
                if forward and mapped.block_ordinal > snapshots[-1].ordinal:
                    mapped = replace(mapped, block_ordinal=mapped.block_ordinal - removed_count)
                elif not forward and mapped.block_ordinal > snapshots[0].ordinal:
                    mapped = replace(mapped, block_ordinal=mapped.block_ordinal + removed_count)
            return mapped

        position = connection.execute(
            "SELECT * FROM reader_playback_positions WHERE document_id = ?",
            (edit.document_id,),
        ).fetchone()
        if position is not None:
            mapped = remap(_cursor_from_row(position))
            connection.execute(
                """
                UPDATE reader_playback_positions SET block_id = ?, block_ordinal = ?,
                    character_offset = ?, content_revision = ?, segment_index = NULL,
                    row_version = row_version + 1
                WHERE document_id = ?
                """,
                (
                    mapped.block_id,
                    mapped.block_ordinal,
                    mapped.character_offset,
                    new_revision,
                    edit.document_id,
                ),
            )

        now = _time_dump(utc_now())
        bookmark_rows = list(
            connection.execute(
                "SELECT * FROM reader_bookmarks WHERE document_id = ?",
                (edit.document_id,),
            )
        )
        for row in bookmark_rows:
            mapped = remap(_cursor_from_row(row))
            connection.execute(
                """
                UPDATE reader_bookmarks SET block_id = ?, block_ordinal = ?,
                    character_offset = ?, content_revision = ?, segment_index = NULL,
                    updated_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (
                    mapped.block_id,
                    mapped.block_ordinal,
                    mapped.character_offset,
                    new_revision,
                    now,
                    row["id"],
                ),
            )

    def _remove_appended_blocks(
        self,
        connection: sqlite3.Connection,
        edit: DocumentEdit,
        new_revision: int,
    ) -> tuple[int, int]:
        specs = _appended_block_specs(edit)
        first_ordinal = specs[0].ordinal
        last_ordinal = specs[-1].ordinal
        rows = list(
            connection.execute(
                """
                SELECT id, ordinal, text FROM reader_blocks
                WHERE document_id = ? AND ordinal BETWEEN ? AND ? ORDER BY ordinal
                """,
                (edit.document_id, first_ordinal, last_ordinal),
            )
        )
        if len(rows) != len(specs) or any(
            str(row["id"]) != spec.id
            or int(row["ordinal"]) != spec.ordinal
            or str(row["text"]) != spec.text
            for row, spec in zip(rows, specs, strict=True)
        ):
            raise ReaderStaleCursorError("appended blocks no longer match undo history")
        previous = connection.execute(
            """
            SELECT id, ordinal, character_count FROM reader_blocks
            WHERE document_id = ? AND ordinal < ? ORDER BY ordinal DESC LIMIT 1
            """,
            (edit.document_id, first_ordinal),
        ).fetchone()
        if previous is None:
            raise ReaderStaleCursorError("appended blocks have no stable predecessor")
        connection.execute(
            """
            UPDATE reader_playback_positions SET block_id = ?, block_ordinal = ?,
                character_offset = ?
            WHERE document_id = ? AND block_ordinal BETWEEN ? AND ?
            """,
            (
                previous["id"],
                previous["ordinal"],
                previous["character_count"],
                edit.document_id,
                first_ordinal,
                last_ordinal,
            ),
        )
        connection.execute(
            """
            UPDATE reader_bookmarks SET block_id = ?, block_ordinal = ?, character_offset = ?,
                updated_at = ?
            WHERE document_id = ? AND block_ordinal BETWEEN ? AND ?
            """,
            (
                previous["id"],
                previous["ordinal"],
                previous["character_count"],
                _time_dump(utc_now()),
                edit.document_id,
                first_ordinal,
                last_ordinal,
            ),
        )
        self._advance_saved_cursor_revisions(connection, edit.document_id, new_revision)
        connection.execute(
            """
            DELETE FROM reader_blocks
            WHERE document_id = ? AND ordinal BETWEEN ? AND ?
            """,
            (edit.document_id, first_ordinal, last_ordinal),
        )
        return len(specs), sum(len(spec.text) for spec in specs)

    def _restore_appended_blocks(
        self,
        connection: sqlite3.Connection,
        edit: DocumentEdit,
    ) -> tuple[int, int]:
        specs = _appended_block_specs(edit)
        connection.executemany(
            """
            INSERT INTO reader_blocks(
                id, document_id, section_id, ordinal, kind, text,
                character_count, content_sha256, row_version, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, '{}')
            """,
            [
                (
                    spec.id,
                    edit.document_id,
                    spec.section_id,
                    spec.ordinal,
                    spec.kind,
                    spec.text,
                    len(spec.text),
                    _sha256(spec.text),
                )
                for spec in specs
            ],
        )
        return len(specs), sum(len(spec.text) for spec in specs)

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
                    if _is_range_delete(edit):
                        remapped = _remap_cursor_for_range_delete(
                            remapped,
                            edit,
                            _range_delete_snapshots(edit),
                            forward=True,
                            new_revision=edit.result_content_revision,
                        )
                    else:
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


def _desktop_open_request_from_row(row: sqlite3.Row) -> ReaderDesktopOpenRequest:
    return ReaderDesktopOpenRequest(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        created_at=_time_load(row["created_at"]),
    )


def _cursor_dump(cursor: ReaderCursor | None) -> str | None:
    if cursor is None:
        return None
    return _json_dump(
        {
            "document_id": cursor.document_id,
            "block_id": cursor.block_id,
            "block_ordinal": cursor.block_ordinal,
            "character_offset": cursor.character_offset,
            "content_revision": cursor.content_revision,
            "segment_index": cursor.segment_index,
        }
    )


def _cursor_load(value: str | None) -> ReaderCursor | None:
    if value is None:
        return None
    payload = _json_load(value)
    try:
        return ReaderCursor(
            document_id=str(payload["document_id"]),
            block_id=str(payload["block_id"]),
            block_ordinal=int(payload["block_ordinal"]),
            character_offset=int(payload["character_offset"]),
            content_revision=int(payload["content_revision"]),
            segment_index=(
                int(payload["segment_index"])
                if payload.get("segment_index") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReaderDatabaseError("Reader export cursor JSON is invalid") from exc


def _export_from_row(row: sqlite3.Row) -> ReaderExportJob:
    return ReaderExportJob(
        id=str(row["id"]),
        status=ExportStatus(row["status"]),
        document_ids=_json_string_tuple_load(row["document_ids_json"]),
        section_ids=_json_string_tuple_load(row["section_ids_json"]),
        start_cursor=_cursor_load(row["start_cursor_json"]),
        end_cursor=_cursor_load(row["end_cursor_json"]),
        voice_id=row["voice_id"],
        audio_format=ExportAudioFormat(row["audio_format"]),
        progress_phase=ExportPhase(row["progress_phase"]),
        progress_percent=int(row["progress_percent"]),
        output_basename=row["output_basename"],
        overwrite_existing=bool(row["overwrite_existing"]),
        total_documents=int(row["total_documents"]),
        completed_documents=int(row["completed_documents"]),
        current_document_id=row["current_document_id"],
        output_files=_json_string_tuple_load(row["output_files_json"]),
        error_type=row["error_type"],
        error_message=row["error_message"],
        cancel_requested=bool(row["cancel_requested"]),
        created_at=_time_load(row["created_at"]),
        updated_at=_time_load(row["updated_at"]),
        completed_at=(
            _time_load(row["completed_at"]) if row["completed_at"] is not None else None
        ),
        row_version=int(row["row_version"]),
    )


def _export_values(job: ReaderExportJob) -> tuple[Any, ...]:
    return (
        job.id,
        job.status.value,
        _json_dump(job.document_ids),
        _json_dump(job.section_ids),
        _cursor_dump(job.start_cursor),
        _cursor_dump(job.end_cursor),
        job.voice_id,
        job.audio_format.value,
        job.progress_phase.value,
        job.progress_percent,
        job.output_basename,
        int(job.overwrite_existing),
        job.total_documents,
        job.completed_documents,
        job.current_document_id,
        _json_dump(job.output_files),
        job.error_type,
        job.error_message,
        int(job.cancel_requested),
        _time_dump(job.created_at),
        _time_dump(job.updated_at),
        _time_dump(job.completed_at) if job.completed_at is not None else None,
        job.row_version,
    )


def _require_export_job(connection: sqlite3.Connection, job_id: str) -> ReaderExportJob:
    row = connection.execute(
        "SELECT * FROM reader_export_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if row is None:
        raise ReaderNotFoundError(f"Reader export job not found: {job_id}")
    return _export_from_row(row)


def _rule_set_from_row(row: sqlite3.Row) -> SpeechRuleSet:
    return SpeechRuleSet(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        enabled=bool(row["enabled"]),
        scope=RuleScope(row["scope"]),
        source_sha256=row["source_sha256"],
        version=int(row["version"]),
        row_version=int(row["row_version"]),
        created_at=_time_load(row["created_at"]),
        updated_at=_time_load(row["updated_at"]),
        raw_import_metadata=_json_load(row["raw_import_metadata_json"]),
    )


def _rule_set_values(rule_set: SpeechRuleSet) -> tuple[Any, ...]:
    return (
        rule_set.id,
        rule_set.name,
        rule_set.description,
        int(rule_set.enabled),
        rule_set.scope.value,
        rule_set.source_sha256,
        rule_set.version,
        rule_set.row_version,
        _time_dump(rule_set.created_at),
        _time_dump(rule_set.updated_at),
        _json_dump(rule_set.raw_import_metadata),
    )


def _rule_from_row(row: sqlite3.Row) -> SpeechRule:
    return SpeechRule(
        id=str(row["id"]),
        rule_set_id=str(row["rule_set_id"]),
        name=str(row["name"]),
        enabled=bool(row["enabled"]),
        stage=RuleStage(row["stage"]),
        rule_type=RuleType(row["rule_type"]),
        pattern=str(row["pattern"]),
        replacement=str(row["replacement"]),
        case_sensitive=bool(row["case_sensitive"]),
        whole_word=bool(row["whole_word"]),
        language_filter=row["language_filter"],
        engine_filter=row["engine_filter"],
        voice_filter=row["voice_filter"],
        document_filter=row["document_filter"],
        priority=int(row["priority"]),
        regex_timeout_ms=int(row["regex_timeout_ms"]),
        row_version=int(row["row_version"]),
        created_at=_time_load(row["created_at"]),
        updated_at=_time_load(row["updated_at"]),
        raw_import_metadata=_json_load(row["raw_import_metadata_json"]),
    )


def _rule_values(rule: SpeechRule) -> tuple[Any, ...]:
    return (
        rule.id,
        rule.rule_set_id,
        rule.name,
        int(rule.enabled),
        rule.stage.value,
        rule.rule_type.value,
        rule.pattern,
        rule.replacement,
        int(rule.case_sensitive),
        int(rule.whole_word),
        rule.language_filter,
        rule.engine_filter,
        rule.voice_filter,
        rule.document_filter,
        rule.priority,
        rule.regex_timeout_ms,
        rule.row_version,
        _time_dump(rule.created_at),
        _time_dump(rule.updated_at),
        _json_dump(rule.raw_import_metadata),
    )


def _highlighter_term_from_row(row: sqlite3.Row) -> HighlighterTerm:
    return HighlighterTerm(
        id=str(row["id"]),
        term=str(row["term"]),
        normalized_term=str(row["normalized_term"]),
        active=bool(row["active"]),
        color=str(row["color"]),
        ordinal=int(row["ordinal"]),
        created_at=_time_load(row["created_at"]),
        updated_at=_time_load(row["updated_at"]),
    )


def _highlighter_term_values(term: HighlighterTerm) -> tuple[Any, ...]:
    return (
        term.id,
        term.term,
        term.normalized_term,
        int(term.active),
        term.color,
        term.ordinal,
        _time_dump(term.created_at),
        _time_dump(term.updated_at),
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


def _json_dump(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
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


def _json_string_tuple_load(value: str) -> tuple[str, ...]:
    decoded = json.loads(value)
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise ReaderDatabaseError("Reader string-list JSON is invalid")
    return tuple(decoded)


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


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fts_query(value: str) -> str | None:
    tokens = re.findall(r"[^\W_]+", value, flags=re.UNICODE)
    if not tokens:
        return None
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens[:32])


def _initialize_search_index(connection: sqlite3.Connection) -> bool:
    try:
        existed = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("reader_document_search",),
        ).fetchone() is not None
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS reader_document_search USING fts5(
                document_id UNINDEXED,
                title,
                source_name,
                content,
                tokenize = 'unicode61'
            )
            """
        )
        connection.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS reader_search_document_insert
            AFTER INSERT ON reader_documents BEGIN
                INSERT INTO reader_document_search(document_id, title, source_name, content)
                VALUES (NEW.id, NEW.title, COALESCE(NEW.source_name, ''), '');
            END;

            CREATE TRIGGER IF NOT EXISTS reader_search_document_update
            AFTER UPDATE OF title, source_name ON reader_documents BEGIN
                DELETE FROM reader_document_search WHERE document_id = NEW.id;
                INSERT INTO reader_document_search(document_id, title, source_name, content)
                SELECT NEW.id, NEW.title, COALESCE(NEW.source_name, ''),
                       COALESCE(group_concat(block.text, ' '), '')
                FROM reader_blocks AS block WHERE block.document_id = NEW.id;
            END;

            CREATE TRIGGER IF NOT EXISTS reader_search_document_delete
            AFTER DELETE ON reader_documents BEGIN
                DELETE FROM reader_document_search WHERE document_id = OLD.id;
            END;

            CREATE TRIGGER IF NOT EXISTS reader_search_block_insert
            AFTER INSERT ON reader_blocks BEGIN
                DELETE FROM reader_document_search WHERE document_id = NEW.document_id;
                INSERT INTO reader_document_search(document_id, title, source_name, content)
                SELECT document.id, document.title, COALESCE(document.source_name, ''),
                       COALESCE(group_concat(block.text, ' '), '')
                FROM reader_documents AS document
                LEFT JOIN reader_blocks AS block ON block.document_id = document.id
                WHERE document.id = NEW.document_id GROUP BY document.id;
            END;

            CREATE TRIGGER IF NOT EXISTS reader_search_block_update
            AFTER UPDATE OF text ON reader_blocks BEGIN
                DELETE FROM reader_document_search WHERE document_id = NEW.document_id;
                INSERT INTO reader_document_search(document_id, title, source_name, content)
                SELECT document.id, document.title, COALESCE(document.source_name, ''),
                       COALESCE(group_concat(block.text, ' '), '')
                FROM reader_documents AS document
                LEFT JOIN reader_blocks AS block ON block.document_id = document.id
                WHERE document.id = NEW.document_id GROUP BY document.id;
            END;

            CREATE TRIGGER IF NOT EXISTS reader_search_block_delete
            AFTER DELETE ON reader_blocks BEGIN
                DELETE FROM reader_document_search WHERE document_id = OLD.document_id;
                INSERT INTO reader_document_search(document_id, title, source_name, content)
                SELECT document.id, document.title, COALESCE(document.source_name, ''),
                       COALESCE(group_concat(block.text, ' '), '')
                FROM reader_documents AS document
                LEFT JOIN reader_blocks AS block ON block.document_id = document.id
                WHERE document.id = OLD.document_id GROUP BY document.id;
            END;
            """
        )
        if not existed:
            connection.execute(
                """
                INSERT INTO reader_document_search(document_id, title, source_name, content)
                SELECT document.id, document.title, COALESCE(document.source_name, ''),
                       COALESCE(group_concat(block.text, ' '), '')
                FROM reader_documents AS document
                LEFT JOIN reader_blocks AS block ON block.document_id = document.id
                GROUP BY document.id
                """
            )
        return True
    except sqlite3.OperationalError as exc:
        if "fts5" not in str(exc).lower() and "no such module" not in str(exc).lower():
            raise
        return False
