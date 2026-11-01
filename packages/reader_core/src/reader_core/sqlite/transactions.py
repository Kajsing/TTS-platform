"""Private facade for composing normal repository operations in one transaction."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .repository import SqliteReaderRepository


class TransactionRepository(SqliteReaderRepository):
    """Nested methods reuse the caller's transaction and never commit independently."""

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
            raise RuntimeError("Reader transaction has ended")
        yield self._transaction_connection

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            yield connection
