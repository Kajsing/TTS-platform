from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from reader_core import ReaderMigrationError, SqliteReaderRepository
from reader_core.sqlite.connection import connect_sqlite
from reader_core.sqlite.migrations import Migration, apply_migrations, load_migrations


def test_initial_migration_is_repeatable_and_reported(tmp_path: Path) -> None:
    database = tmp_path / "reader.db"
    repository = SqliteReaderRepository(database)
    SqliteReaderRepository(database)

    report = repository.report()

    assert report.ready is True
    assert report.schema_version == 4
    assert report.integrity_ok is True
    assert report.integrity_message == "ok"
    assert report.journal_mode == "wal"


def test_applied_migration_checksum_mismatch_is_typed(tmp_path: Path) -> None:
    database = tmp_path / "reader.db"
    SqliteReaderRepository(database)
    migrations = load_migrations()
    original = migrations[0]
    changed = Migration(
        version=original.version,
        name=original.name,
        sql=original.sql + "\n-- changed",
        checksum=hashlib.sha256((original.sql + "\n-- changed").encode()).hexdigest(),
    )

    with connect_sqlite(database) as connection:
        with pytest.raises(ReaderMigrationError, match="checksum"):
            apply_migrations(connection, (changed, *migrations[1:]))


def test_invalid_migration_rolls_back_and_is_typed(tmp_path: Path) -> None:
    database = tmp_path / "broken.db"
    bad_sql = "CREATE TABLE should_rollback(id INTEGER);\nTHIS IS INVALID;"
    bad = Migration(
        version=1,
        name="001_broken.sql",
        sql=bad_sql,
        checksum=hashlib.sha256(bad_sql.encode()).hexdigest(),
    )

    with connect_sqlite(database) as connection:
        with pytest.raises(ReaderMigrationError, match="001_broken.sql"):
            apply_migrations(connection, (bad,))
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'should_rollback'"
        ).fetchone()

    assert table is None


def test_incomplete_migration_rolls_back_open_transaction(tmp_path: Path) -> None:
    database = tmp_path / "incomplete.db"
    sql = "CREATE TABLE incomplete(id INTEGER)"
    incomplete = Migration(
        version=1,
        name="001_incomplete.sql",
        sql=sql,
        checksum=hashlib.sha256(sql.encode()).hexdigest(),
    )

    with connect_sqlite(database) as connection:
        with pytest.raises(ReaderMigrationError, match="incomplete"):
            apply_migrations(connection, (incomplete,))
        assert connection.in_transaction is False
