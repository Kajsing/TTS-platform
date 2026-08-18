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
    assert report.schema_version == 8
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


def test_known_legacy_rule_migration_checksum_upgrades_safely(tmp_path: Path) -> None:
    database = tmp_path / "legacy-reader.db"
    migrations = load_migrations()
    current_rules = migrations[1]
    legacy_sql = (
        current_rules.sql.replace(
            "CHECK (length(pattern) > 0 AND length(pattern) <= 2048)",
            "CHECK (length(pattern) > 0)",
        )
        .replace(
            "DEFAULT '' CHECK (length(replacement) <= 4096)",
            "DEFAULT ''",
        )
        .replace(
            "CHECK (regex_timeout_ms BETWEEN 1 AND 1000)",
            "CHECK (regex_timeout_ms > 0)",
        )
    )
    legacy_checksum = hashlib.sha256(legacy_sql.encode()).hexdigest()
    assert legacy_checksum == (
        "b952d4ff98accea6f6a5df1fa7ed628737d141b076a195edb17c090eba8a3da3"
    )
    legacy_rules = Migration(
        version=current_rules.version,
        name=current_rules.name,
        sql=legacy_sql,
        checksum=legacy_checksum,
    )

    with connect_sqlite(database) as connection:
        assert apply_migrations(connection, (migrations[0], legacy_rules)) == 2

    repository = SqliteReaderRepository(database)

    assert repository.report().schema_version == 8
    with connect_sqlite(database) as connection:
        applied_checksum = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = 2"
        ).fetchone()[0]
        handoff_table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'reader_desktop_open_requests'"
        ).fetchone()
    assert applied_checksum == legacy_checksum
    assert handoff_table is not None


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
