from __future__ import annotations

import uuid

from reader_core import ReaderFolder, ReaderLibrary, SqliteReaderRepository
from reader_core.models import utc_now
from reader_core.sqlite.agent_repository import SqliteReaderAgentRepository
from reader_core.sqlite.connection import connect_sqlite
from reader_core.sqlite.migrations import apply_migrations, load_migrations


def test_schema_11_upgrade_preserves_legacy_article_grant_and_receipt(tmp_path):
    path = tmp_path / "legacy.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection, load_migrations()[:11])
    old = SqliteReaderRepository(path, initialize=False)
    now = utc_now()
    folder = old.create_folder(ReaderFolder(str(uuid.uuid4()), "Agent", "agent", now, now))
    article = ReaderLibrary(old).create_plain_text_document(
        title="Legacy", text="Chapter one\n\nPreserved 😀.", folder_id=folder.id
    )
    agents = SqliteReaderAgentRepository(old)
    grant, secret = agents.provision(folder.id, "Existing grant")
    receipt_id = str(uuid.uuid4())
    with old._write() as connection:
        connection.execute(
            "INSERT INTO reader_agent_chapters VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (receipt_id, article.id, "story", "one", "https://example.com/one", "One", None,
             1, None, "a" * 64, "historic-edit", now.isoformat(), 1, 1),
        )
        before = tuple(connection.execute("SELECT * FROM schema_migrations ORDER BY version"))
    upgraded = SqliteReaderRepository(path)
    assert upgraded.report().schema_version == 13
    assert upgraded.report().integrity_ok
    current = SqliteReaderAgentRepository(upgraded)
    assert current.workspace(secret)[0] == grant
    assert current.read_article(secret, article.id).text == "Chapter one\n\nPreserved 😀."
    assert current.read_article(secret, article.id).document == article
    assert current.list_chapters(secret, article.id)[0].id == receipt_id
    assert current.story_status(secret, story_key="story")["items"][0]["managed"] is False
    with upgraded._connection() as connection:
        after = tuple(connection.execute("SELECT * FROM schema_migrations ORDER BY version"))
        assert [tuple(row) for row in after[:11]] == [tuple(row) for row in before]
