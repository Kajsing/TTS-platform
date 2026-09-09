"""Transactional, owner-authorized desktop capture delivery receipts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from typing import Callable, Iterator

from ..errors import CapturePayloadConflictError, ReaderNotFoundError, ReaderValidationError
from ..models import SourceType, utc_now
from ..services import ReaderLibrary
from .repository import SqliteReaderRepository


class _CaptureRejection(Exception):
    """Carry application errors through generator contexts without mutating them."""

    def __init__(self, error: Exception):
        self.error = error
        super().__init__(str(error))


class _CaptureTransaction(SqliteReaderRepository):
    def __init__(self, source: SqliteReaderRepository, connection: sqlite3.Connection):
        super().__init__(
            source.database_path,
            initialize=False,
            max_edit_history_operations=source.max_edit_history_operations,
            max_edit_history_bytes=source.max_edit_history_bytes,
        )
        self._transaction = connection
        self._search_available = source.search_available

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if not self._transaction.in_transaction:
            raise RuntimeError("Capture transaction has ended")
        yield self._transaction

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            yield connection


class CaptureRepository:
    def __init__(self, repository: SqliteReaderRepository):
        self.repository = repository

    def target(self, request: dict) -> str | None:
        if request["action"] == "create":
            return None
        if request.get("document_id"):
            return request["document_id"]
        with self.repository._connection() as connection:
            row = connection.execute(
                "SELECT document_id FROM reader_capture_receipts WHERE operation_id = ?",
                (request.get("target_operation_id"),),
            ).fetchone()
        if row is None:
            raise ReaderValidationError("The earlier capture has not been delivered yet")
        return str(row["document_id"])

    def deliver(
        self,
        operation_id: str,
        request: dict,
        *,
        authorize_folder: Callable[[str | None], None],
        duplicate_error: Callable[[str], Exception],
    ) -> dict:
        def authorize(folder_id):
            try:
                authorize_folder(folder_id)
            except Exception as error:
                raise _CaptureRejection(error) from error

        try:
            return self._deliver(operation_id, request, authorize, duplicate_error)
        except _CaptureRejection as rejected:
            # Frozen application exceptions cannot cross contextlib generators:
            # contextlib assigns __traceback__. Raise only after rollback/close.
            raise rejected.error from None

    def _deliver(self, operation_id, request, authorize_folder, duplicate_error) -> dict:
        fingerprint = hashlib.sha256(
            json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        with self.repository._write() as connection:
            bound = _CaptureTransaction(self.repository, connection)
            receipt = connection.execute(
                "SELECT * FROM reader_capture_receipts WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if receipt is not None:
                if receipt["payload_sha256"] != fingerprint:
                    raise CapturePayloadConflictError(
                        "Capture ID was reused with different content"
                    )
                document = bound.get_document(receipt["document_id"])
                authorize_folder(document.folder_id)
                return {
                    "operation_id": operation_id,
                    "document_id": document.id,
                    "outcome": "already_delivered",
                }
            if request["action"] == "create":
                authorize_folder(request.get("folder_id"))
                if not request.get("allow_duplicate"):
                    duplicate = bound.find_document_by_source_hash(
                        hashlib.sha256(request["text"].encode()).hexdigest()
                    )
                    if duplicate is not None:
                        raise _CaptureRejection(duplicate_error(duplicate.id))
                document = ReaderLibrary(bound).create_plain_text_document(
                    title=request["title"],
                    text=request["text"],
                    source_type=SourceType.CLIPBOARD,
                    folder_id=request.get("folder_id"),
                )
            else:
                target = request.get("document_id")
                if not target:
                    row = connection.execute(
                        "SELECT document_id FROM reader_capture_receipts WHERE operation_id = ?",
                        (request.get("target_operation_id"),),
                    ).fetchone()
                    if row is None:
                        raise ReaderValidationError(
                            "The earlier capture has not been delivered yet"
                        )
                    target = row["document_id"]
                document = bound.get_document(target)
                authorize_folder(document.folder_id)
                if document.deleted_at is not None:
                    raise ReaderNotFoundError("The target article was deleted")
                # Append has an explicit end-of-article intention, not a stale
                # character range. Resolve its current version inside the write.
                document, _ = bound.append_text(
                    document.id,
                    request["text"],
                    expected_row_version=document.row_version,
                    new_chapter=request["new_chapter"],
                )
            connection.execute(
                "INSERT INTO reader_capture_receipts VALUES (?, ?, ?, ?)",
                (operation_id, fingerprint, document.id, utc_now().isoformat()),
            )
            return {
                "operation_id": operation_id,
                "document_id": document.id,
                "outcome": "delivered",
            }
