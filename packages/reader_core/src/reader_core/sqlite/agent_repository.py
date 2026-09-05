"""Scoped transactions that reuse Reader edits without bypassing their history.

Every operation authorizes inside the same SQLite transaction as its read/write.
No caller receives a bound repository or connection. Grant revocation, folder
privacy changes, article moves and chapter commits therefore have a single
serialization order, even across separate service connections.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import Iterator

from ..agent_access import (
    AGENT_OPERATIONS,
    MAX_AGENT_PAGE,
    MAX_AGENT_TEXT,
    AgentArticlePage,
    AgentConflictError,
    AgentGrant,
    AgentUnauthorizedError,
    ChapterDelivery,
    ChapterReceipt,
    bounded_text,
    credential_digest,
)
from ..errors import ReaderConflictError, ReaderNotFoundError, ReaderValidationError
from ..models import DocumentPage, ReaderDocument, ReaderFolder, utc_now
from ..services import ReaderLibrary
from .repository import SqliteReaderRepository


class _TransactionRepository(SqliteReaderRepository):
    """Private short-lived facade; nested Reader methods never commit on their own."""

    def __init__(self, source: SqliteReaderRepository, connection: sqlite3.Connection) -> None:
        super().__init__(
            source.database_path,
            max_edit_history_operations=source.max_edit_history_operations,
            max_edit_history_bytes=source.max_edit_history_bytes,
            initialize=False,
        )
        self._search_available = source.search_available
        self._transaction_connection = connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if not self._transaction_connection.in_transaction:
            raise RuntimeError("Agent transaction has ended")
        yield self._transaction_connection

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            yield connection


class SqliteReaderAgentRepository:
    def __init__(self, repository: SqliteReaderRepository) -> None:
        self._repository = repository

    def provision(
        self,
        folder_id: str,
        name: str,
        *,
        operations: tuple[str, ...] | None = None,
    ) -> tuple[AgentGrant, str]:
        """Owner-only entry point. The HTTP layer must require native owner auth."""
        bounded_text(name, "grant name", 80)
        allowed = tuple(sorted(AGENT_OPERATIONS if operations is None else set(operations)))
        if not allowed or not set(allowed) <= AGENT_OPERATIONS:
            raise ReaderValidationError("Agent operations must be a nonempty supported allowlist")
        secret = "rdr_agent_" + secrets.token_urlsafe(32)
        grant = AgentGrant(str(uuid.uuid4()), folder_id, name, allowed, utc_now().isoformat(), None)
        with self._repository._write() as connection:
            bound = _TransactionRepository(self._repository, connection)
            folder = bound.get_folder(folder_id)
            if folder.privacy_locked:
                raise AgentUnauthorizedError()
            connection.execute(
                "INSERT INTO reader_agent_grants VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (
                    grant.id,
                    folder_id,
                    name,
                    credential_digest(secret),
                    json.dumps(allowed),
                    grant.created_at,
                ),
            )
        return grant, secret

    def list_grants(self) -> tuple[AgentGrant, ...]:
        with self._repository._connection() as connection:
            return tuple(
                _grant(row)
                for row in connection.execute(
                    "SELECT * FROM reader_agent_grants ORDER BY created_at, id"
                )
            )

    def revoke(self, grant_id: str) -> None:
        with self._repository._write() as connection:
            changed = connection.execute(
                "UPDATE reader_agent_grants SET revoked_at = COALESCE(revoked_at, ?) WHERE id = ?",
                (utc_now().isoformat(), grant_id),
            )
            if changed.rowcount != 1:
                raise ReaderNotFoundError("Agent grant not found")

    @contextmanager
    def _scope(
        self,
        credential: str,
        operation: str | None,
        document_id: str | None = None,
    ) -> Iterator[tuple[_TransactionRepository, sqlite3.Connection, AgentGrant]]:
        digest = credential_digest(credential)
        # Short bounded read transactions also take the writer reservation so
        # scope cannot change between authorization and returning content.
        with self._repository._write() as connection:
            row = connection.execute(
                "SELECT grant_row.* FROM reader_agent_grants AS grant_row "
                "JOIN reader_folders AS folder ON folder.id = grant_row.folder_id "
                "WHERE credential_hash = ? AND revoked_at IS NULL AND NOT EXISTS "
                "(SELECT 1 FROM reader_folder_privacy WHERE folder_id = folder.id)",
                (digest,),
            ).fetchone()
            if row is None:
                raise AgentUnauthorizedError()
            grant = _grant(row)
            if operation is not None and operation not in grant.operations:
                raise AgentUnauthorizedError()
            bound = _TransactionRepository(self._repository, connection)
            if document_id is not None:
                try:
                    document = bound.get_document(document_id)
                except ReaderNotFoundError:
                    raise AgentUnauthorizedError() from None
                if document.folder_id != grant.folder_id or document.deleted_at is not None:
                    raise AgentUnauthorizedError()
            yield bound, connection, grant

    def authenticate(self, credential: str) -> None:
        with self._scope(credential, None):
            pass

    def authorize(self, credential: str, operation: str, document_id: str | None = None) -> None:
        # Useful for rejecting unauthorized/busy requests before acquisition of
        # an application lease. The actual operation always checks again.
        with self._scope(credential, operation, document_id):
            pass

    def workspace(self, credential: str) -> tuple[AgentGrant, ReaderFolder]:
        with self._scope(credential, "workspace") as (bound, _, grant):
            return grant, bound.get_folder(grant.folder_id)

    def list_articles(
        self,
        credential: str,
        *,
        query: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> DocumentPage:
        if not 1 <= limit <= 100:
            raise ReaderValidationError("Article page limit must be between 1 and 100")
        if query is not None:
            bounded_text(query, "query", 200, empty=True)
        if cursor is not None:
            bounded_text(cursor, "cursor", 512)
        with self._scope(credential, "list") as (bound, _, grant):
            return bound.list_documents(
                folder_id=grant.folder_id,
                query=query,
                limit=limit,
                cursor=cursor,
            )

    def read_article(
        self,
        credential: str,
        document_id: str,
        *,
        offset: int = 0,
        limit: int = MAX_AGENT_PAGE,
        expected_row_version: int | None = None,
    ) -> AgentArticlePage:
        if offset < 0 or not 1 <= limit <= MAX_AGENT_PAGE:
            raise ReaderValidationError("Invalid article page offset or size")
        if offset and expected_row_version is None:
            raise ReaderValidationError("Continuation pages require expected_row_version")
        with self._scope(credential, "read", document_id) as (bound, connection, _):
            document = bound.get_document(document_id)
            if expected_row_version is not None:
                _version(document, expected_row_version)
            length = document.total_characters + max(0, document.total_blocks - 1) * 2
            if offset > length:
                raise ReaderValidationError("Article page offset exceeds text length")
            end = min(length, offset + limit)
            pieces = []
            position = 0
            for index, row in enumerate(
                connection.execute(
                    "SELECT text FROM reader_blocks WHERE document_id = ? ORDER BY ordinal",
                    (document_id,),
                )
            ):
                text = ("\n\n" if index else "") + row["text"]
                following = position + len(text)
                if following > offset:
                    pieces.append(text[max(0, offset - position) : max(0, end - position)])
                position = following
                if position >= end:
                    break
            return AgentArticlePage(
                document,
                "".join(pieces),
                offset,
                end if end < length else None,
                length,
            )

    def create_article(self, credential: str, *, title: str, text: str) -> ReaderDocument:
        bounded_text(title, "title", 500)
        bounded_text(text, "text", MAX_AGENT_TEXT)
        with self._scope(credential, "create") as (bound, _, grant):
            return ReaderLibrary(bound).create_plain_text_document(
                title=title,
                text=text,
                folder_id=grant.folder_id,
            )

    def rename_article(
        self,
        credential: str,
        document_id: str,
        *,
        title: str,
        expected_row_version: int,
    ) -> ReaderDocument:
        bounded_text(title, "title", 500)
        with self._scope(credential, "rename", document_id) as (bound, _, _):
            return bound.update_document(
                document_id,
                title=title,
                expected_row_version=expected_row_version,
            )

    def append_article(
        self,
        credential: str,
        document_id: str,
        *,
        text: str,
        expected_row_version: int,
    ) -> ReaderDocument:
        bounded_text(text, "text", MAX_AGENT_TEXT)
        with self._scope(credential, "append", document_id) as (bound, _, _):
            return bound.append_text(document_id, text, expected_row_version=expected_row_version)[
                0
            ]

    def replace_text(
        self,
        credential: str,
        document_id: str,
        *,
        old_text: str,
        new_text: str,
        expected_row_version: int,
    ) -> ReaderDocument:
        bounded_text(old_text, "old_text", MAX_AGENT_TEXT)
        bounded_text(new_text, "new_text", MAX_AGENT_TEXT, empty=True)
        with self._scope(credential, "replace", document_id) as (bound, _, _):
            bundle = bound.get_document_bundle(document_id)
            _version(bundle.document, expected_row_version)
            match: tuple[str, int] | None = None
            for block in bundle.blocks:
                offset = block.text.find(old_text)
                if offset < 0:
                    continue
                if match is not None or block.text.find(old_text, offset + 1) >= 0:
                    raise AgentConflictError("Text occurs more than once; supply a unique passage.")
                match = (block.id, offset)
            if match is None:
                raise AgentConflictError(
                    "No exact match within one paragraph; read the article again."
                )
            return bound.replace_block_text(
                document_id,
                match[0],
                start_offset=match[1],
                end_offset=match[1] + len(old_text),
                replacement_text=new_text,
                expected_row_version=expected_row_version,
            )[0]

    def list_chapters(
        self,
        credential: str,
        document_id: str,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[ChapterReceipt, ...]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ReaderValidationError("Invalid chapter page offset or size")
        with self._scope(credential, "chapters", document_id) as (_, connection, _):
            return tuple(
                _receipt(row)
                for row in connection.execute(
                    "SELECT * FROM reader_agent_chapters WHERE document_id = ? "
                    "ORDER BY imported_at, id LIMIT ? OFFSET ?",
                    (document_id, limit, offset),
                )
            )

    def deliver_chapter(
        self,
        credential: str,
        document_id: str,
        delivery: ChapterDelivery,
        *,
        expected_row_version: int,
    ) -> ChapterReceipt:
        with self._scope(credential, "deliver", document_id) as (bound, connection, _):
            fingerprint = delivery.fingerprint()
            retried = connection.execute(
                "SELECT chapter.* FROM reader_agent_chapter_retries AS retry "
                "JOIN reader_agent_chapters AS chapter ON chapter.id = retry.chapter_id "
                "WHERE retry.document_id = ? AND retry.retry_key = ?",
                (document_id, delivery.retry_key),
            ).fetchone()
            existing = connection.execute(
                "SELECT * FROM reader_agent_chapters WHERE document_id = ? "
                "AND story_key = ? AND chapter_key = ?",
                (document_id, delivery.story_key, delivery.chapter_key),
            ).fetchone()
            for previous in (retried, existing):
                if previous is not None and previous["payload_hash"] != fingerprint:
                    raise AgentConflictError(
                        "Chapter or retry identity already has a different payload."
                    )
            previous = retried if retried is not None else existing
            if previous is not None:
                # Keep the original committed revision even if the owner has
                # since edited/undone the text. Never resurrect it on a retry.
                self._record_retry(connection, document_id, delivery.retry_key, previous["id"])
                return replace(_receipt(previous), outcome="already_imported")
            warning = None
            if delivery.order_index is not None:
                earlier = connection.execute(
                    "SELECT 1 FROM reader_agent_chapters WHERE document_id = ? AND story_key = ? "
                    "AND order_index >= ? LIMIT 1",
                    (document_id, delivery.story_key, delivery.order_index),
                ).fetchone()
                if earlier is not None:
                    warning = "order_not_after_previous_delivery"
            document, edit = bound.append_text(
                document_id,
                delivery.text,
                expected_row_version=expected_row_version,
            )
            receipt = ChapterReceipt(
                id=str(uuid.uuid4()),
                document_id=document_id,
                story_key=delivery.story_key,
                chapter_key=delivery.chapter_key,
                source_url=delivery.source_url,
                title=delivery.title,
                order_label=delivery.order_label,
                order_index=delivery.order_index,
                order_warning=warning,
                imported_at=utc_now(),
                result_row_version=document.row_version,
                result_content_revision=document.content_revision,
            )
            connection.execute(
                "INSERT INTO reader_agent_chapters VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt.id,
                    document_id,
                    delivery.story_key,
                    delivery.chapter_key,
                    delivery.source_url,
                    delivery.title,
                    delivery.order_label,
                    delivery.order_index,
                    warning,
                    fingerprint,
                    edit.id,
                    receipt.imported_at.isoformat(),
                    document.row_version,
                    document.content_revision,
                ),
            )
            self._record_retry(connection, document_id, delivery.retry_key, receipt.id)
            return receipt

    @staticmethod
    def _record_retry(
        connection: sqlite3.Connection,
        document_id: str,
        retry_key: str,
        chapter_id: str,
    ) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO reader_agent_chapter_retries VALUES (?, ?, ?)",
            (document_id, retry_key, chapter_id),
        )


def _grant(row: sqlite3.Row) -> AgentGrant:
    return AgentGrant(
        row["id"],
        row["folder_id"],
        row["name"],
        tuple(json.loads(row["operations_json"])),
        row["created_at"],
        row["revoked_at"],
    )


def _receipt(row: sqlite3.Row) -> ChapterReceipt:
    values = {name: row[name] for name in ChapterReceipt.__dataclass_fields__ if name != "outcome"}
    values["imported_at"] = datetime.fromisoformat(values["imported_at"])
    return ChapterReceipt(**values)


def _version(document: ReaderDocument, expected: int) -> None:
    if document.row_version != expected:
        raise ReaderConflictError(document.id, expected=expected, actual=document.row_version)
