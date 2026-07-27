from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from typing import Iterable

from ..errors import ReaderMigrationError

_MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{3})_[a-z0-9_]+\.sql$")

# A development Milestone 7 database could apply the first rule migration
# before its pattern, replacement, and timeout constraints were tightened in
# the canonical SQL. The service layer enforced those same bounds already.
# Accept only that exact known predecessor so existing local libraries can
# continue to later migrations while arbitrary checksum drift still fails.
_COMPATIBLE_APPLIED_CHECKSUMS = {
    (
        2,
        "002_rules_and_profiles.sql",
        "8d7727ae6ff923f5fcc0831204f53b8ee04cadba82a2422581f1d97e8bb7c18c",
    ): frozenset(
        {"b952d4ff98accea6f6a5df1fa7ed628737d141b076a195edb17c090eba8a3da3"}
    ),
}


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


def load_migrations() -> tuple[Migration, ...]:
    root = resources.files("reader_core.migrations")
    migrations: list[Migration] = []
    for item in root.iterdir():
        match = _MIGRATION_NAME.match(item.name)
        if match is None:
            continue
        sql = item.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=item.name,
                sql=sql,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )
    ordered = tuple(sorted(migrations, key=lambda migration: migration.version))
    versions = [migration.version for migration in ordered]
    if versions != list(range(1, len(versions) + 1)):
        raise ReaderMigrationError("Reader migrations must be contiguous and start at 001")
    return ordered


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: Iterable[Migration] | None = None,
) -> int:
    selected = tuple(migrations) if migrations is not None else load_migrations()
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            int(row["version"]): (str(row["name"]), str(row["checksum"]))
            for row in connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            )
        }
        known_versions = {migration.version for migration in selected}
        unexpected = sorted(set(applied) - known_versions)
        if unexpected:
            raise ReaderMigrationError(
                f"Database contains unknown Reader migration versions: {unexpected}"
            )

        for migration in selected:
            previous = applied.get(migration.version)
            if previous is not None:
                if previous != (migration.name, migration.checksum):
                    compatible = _COMPATIBLE_APPLIED_CHECKSUMS.get(
                        (migration.version, migration.name, migration.checksum),
                        frozenset(),
                    )
                    if previous[0] != migration.name or previous[1] not in compatible:
                        raise ReaderMigrationError(
                            f"Reader migration {migration.name} does not match its applied checksum"
                        )
                continue
            applied_at = datetime.now(timezone.utc).isoformat()
            try:
                connection.execute("BEGIN IMMEDIATE")
                for statement in _migration_statements(migration.sql):
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO schema_migrations(version, name, checksum, applied_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (migration.version, migration.name, migration.checksum, applied_at),
                )
                connection.commit()
            except ReaderMigrationError:
                if connection.in_transaction:
                    connection.rollback()
                raise
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.rollback()
                raise ReaderMigrationError(
                    f"Reader migration {migration.name} failed: {exc}"
                ) from exc
        return max((migration.version for migration in selected), default=0)
    except ReaderMigrationError:
        raise
    except sqlite3.DatabaseError as exc:
        raise ReaderMigrationError(f"Reader migration state could not be read: {exc}") from exc


def _migration_statements(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    pending: list[str] = []
    for line in sql.splitlines(keepends=True):
        pending.append(line)
        candidate = "".join(pending).strip()
        if candidate and sqlite3.complete_statement(candidate):
            statements.append(candidate)
            pending.clear()
    if "".join(pending).strip():
        raise ReaderMigrationError("Reader migration contains an incomplete SQL statement")
    return tuple(statements)
