from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reader_core.sqlite.connection import connect_sqlite


def populate_synthetic_documents(database_path: Path, *, count: int) -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        timestamp = (created + timedelta(seconds=index)).isoformat()
        rows.append(
            (
                str(uuid.uuid5(uuid.NAMESPACE_URL, f"tts-platform:synthetic:{index}")),
                f"Synthetic document {index:05d}",
                "plain_text",
                "inbox",
                timestamp,
                timestamp,
                timestamp,
                1,
                1,
                0,
                0,
                0,
            )
        )
    with connect_sqlite(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            """
            INSERT INTO reader_documents(
                id, title, source_type, state, created_at, updated_at, imported_at,
                content_revision, row_version, total_sections, total_blocks,
                total_characters
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
