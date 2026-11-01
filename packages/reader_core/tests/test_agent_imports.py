from __future__ import annotations

import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from reader_core import (
    ReaderConflictError,
    ReaderDatabaseError,
    ReaderFolder,
    ReaderValidationError,
    SqliteReaderRepository,
)
from reader_core.agent_access import AgentConflictError, AgentUnauthorizedError, ChapterDelivery
from reader_core.agent_parts import PartPolicy
from reader_core.models import utc_now
from reader_core.sqlite.agent_repository import SqliteReaderAgentRepository


def chapter(number, **changes):
    return ChapterDelivery(
        **(
            {
                "story_key": "story",
                "chapter_key": str(number),
                "retry_key": "retry-" + str(number),
                "source_url": "https://example.com/" + str(number),
                "title": "Chapter " + str(number),
                "text": "abcdefgh",
                "order_index": number,
            }
            | changes
        )
    )


@pytest.fixture
def managed(repository):
    now = utc_now()
    folder = repository.create_folder(ReaderFolder(str(uuid.uuid4()), "Agent", "agent", now, now))
    agents = SqliteReaderAgentRepository(repository)
    grant, secret = agents.provision(folder.id, "Test")
    return agents, grant, secret


def prepare(agents, secret, items=None, **changes):
    return agents.preview_import(
        secret,
        **(
            {
                "title": "T",
                "intro": "",
                "chapters": tuple(items or [chapter(1), chapter(2), chapter(3)]),
                "retry_key": "plan-1",
                "policy": PartPolicy(max_characters=22),
            }
            | changes
        ),
    )


def deliver(agents, secret, plan, item):
    target = agents.import_target(secret, plan["plan_id"], item.chapter_key)
    return agents.deliver_import_chapter(
        secret,
        plan_id=plan["plan_id"],
        delivery=item,
        lease_document_id=target,
    )


def test_preview_is_retry_safe_and_stores_no_source_bodies(repository, managed):
    agents, _, secret = managed
    plan = prepare(
        agents, secret, [chapter(1, text="private manuscript prose")], policy=PartPolicy()
    )
    again = prepare(
        agents, secret, [chapter(1, text="private manuscript prose")], policy=PartPolicy()
    )
    assert again["plan_id"] == plan["plan_id"]
    assert again["outcome"] == "already_prepared"
    assert agents.list_articles(secret).items == ()
    with repository._connection() as connection:
        stored = dict(connection.execute("SELECT * FROM reader_agent_import_plans").fetchone())
    assert "private manuscript prose" not in json.dumps(stored)
    assert "private manuscript prose" not in json.dumps(plan)
    with pytest.raises(AgentConflictError, match="different payload"):
        prepare(agents, secret, [chapter(1, text="Changed")], policy=PartPolicy())


def test_multiple_parts_full_readback_restart_and_retry(repository, managed):
    agents, _, secret = managed
    plan = prepare(agents, secret)
    assert [part["chapter_keys"] for part in plan["parts"]] == [["1", "2"], ["3"]]
    first = deliver(agents, secret, plan, chapter(1))
    reopened = SqliteReaderAgentRepository(SqliteReaderRepository(repository.database_path))
    assert deliver(reopened, secret, plan, chapter(1))["outcome"] == "already_imported"
    second = deliver(reopened, secret, plan, chapter(2))
    third = deliver(reopened, secret, plan, chapter(3))
    assert not first["complete"] and not second["complete"] and third["complete"]
    assert first["document_id"] == second["document_id"] != third["document_id"]
    assert reopened.read_article(secret, first["document_id"]).text == "T\n\nabcdefgh\n\nabcdefgh"
    assert reopened.read_article(secret, third["document_id"]).text == "T\n\nabcdefgh"
    assert len(reopened.list_articles(secret).items) == 2
    status = reopened.story_status(secret, story_key="story")
    assert status["story_version"] == 3
    assert status["current_text_verified"] is False
    assert [item["part_number"] for item in status["items"]] == [1, 1, 2]


def test_concurrent_delivery_creates_one_part_and_receipt(repository, managed):
    agents, _, secret = managed
    plan = prepare(agents, secret)

    def run(_):
        reopened = SqliteReaderAgentRepository(SqliteReaderRepository(repository.database_path))
        return reopened.deliver_import_chapter(
            secret, plan_id=plan["plan_id"], delivery=chapter(1), lease_document_id=None
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(result["outcome"] for result in results) == ["already_imported", "imported"]
    assert len(agents.list_articles(secret).items) == 1
    assert len(agents.story_status(secret, story_key="story")["items"]) == 1


def test_concurrent_preview_retry_returns_one_durable_plan(repository, managed):
    _, _, secret = managed

    def run(_):
        reopened = SqliteReaderAgentRepository(SqliteReaderRepository(repository.database_path))
        return prepare(reopened, secret)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert len({result["plan_id"] for result in results}) == 1
    assert sorted(result["outcome"] for result in results) == ["already_prepared", "prepared"]
    with repository._connection() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM reader_agent_import_plans").fetchone()[0] == 1
        )


def test_target_race_cannot_append_without_existing_part_lease(managed):
    agents, _, secret = managed
    plan = prepare(agents, secret)
    assert agents.import_target(secret, plan["plan_id"], "2") is None
    first = deliver(agents, secret, plan, chapter(1))
    with pytest.raises(AgentConflictError, match="target changed"):
        agents.deliver_import_chapter(
            secret, plan_id=plan["plan_id"], delivery=chapter(2), lease_document_id=None
        )
    assert agents.read_article(secret, first["document_id"]).text == "T\n\nabcdefgh"
    assert deliver(agents, secret, plan, chapter(2))["next_index"] == 2


def test_public_creation_retry_key_cannot_redirect_managed_delivery(managed):
    agents, _, secret = managed
    plan = prepare(agents, secret)
    unrelated = agents.create_article(
        secret,
        title=plan["parts"][0]["title"],
        text="T",
        retry_key=f"managed:{plan['plan_id']}:1",
    )
    assert agents.import_target(secret, plan["plan_id"], "1") is None
    result = deliver(agents, secret, plan, chapter(1))
    assert result["document_id"] != unrelated.id
    assert agents.read_article(secret, unrelated.id).text == "T"


def test_invalid_payload_order_stale_plan_and_owner_edit_preserve_source(repository, managed):
    agents, _, secret = managed
    plan = prepare(agents, secret)
    with pytest.raises(AgentConflictError, match="prepared order"):
        deliver(agents, secret, plan, chapter(2))
    with pytest.raises(AgentConflictError, match="does not match"):
        deliver(agents, secret, plan, chapter(1, text="Changed"))
    competing = prepare(agents, secret, [chapter(4)], retry_key="other")
    first = deliver(agents, secret, plan, chapter(1))
    with pytest.raises(AgentConflictError, match="story changed"):
        deliver(agents, secret, competing, chapter(4))
    document = repository.get_document(first["document_id"])
    repository.undo(document.id, expected_row_version=document.row_version)
    assert agents.read_article(secret, document.id).text == "T"
    assert deliver(agents, secret, plan, chapter(1))["outcome"] == "already_imported"
    assert agents.read_article(secret, document.id).text == "T"
    with pytest.raises(ReaderConflictError):
        deliver(agents, secret, plan, chapter(2))


def test_failure_after_receipt_rolls_back_part_creation_and_progress(
    repository, managed, monkeypatch
):
    agents, _, secret = managed
    plan = prepare(agents, secret)

    def fail(*_):
        raise ReaderValidationError("Injected failure")

    monkeypatch.setattr(agents, "_validate_part_after_append", fail)
    with pytest.raises(ReaderValidationError, match="Injected"):
        deliver(agents, secret, plan, chapter(1))
    assert agents.list_articles(secret).items == ()
    with repository._connection() as connection:
        for table in (
            "reader_documents",
            "reader_agent_chapters",
            "reader_agent_import_parts",
            "reader_agent_import_assignments",
            "reader_agent_creations",
        ):
            assert connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
        assert (
            connection.execute("SELECT next_index FROM reader_agent_import_plans").fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT version FROM reader_agent_stories").fetchone()[0] == 0


def test_actual_commit_failure_rolls_back_managed_creation_receipt_and_progress(
    repository, managed, monkeypatch
):
    from reader_core.sqlite import repository as repository_module

    agents, _, secret = managed
    plan = prepare(agents, secret)
    original_connect = repository_module.connect_sqlite

    class CommitFailure:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def commit(self):
            raise sqlite3.OperationalError("Synthetic failure before managed commit")

    with monkeypatch.context() as patch:
        patch.setattr(
            repository_module, "connect_sqlite", lambda path: CommitFailure(original_connect(path))
        )
        with pytest.raises(ReaderDatabaseError):
            agents.deliver_import_chapter(
                secret, plan_id=plan["plan_id"], delivery=chapter(1), lease_document_id=None
            )
    assert agents.list_articles(secret).items == ()
    assert agents.story_status(secret, story_key="story")["items"] == []
    with repository._connection() as connection:
        assert (
            connection.execute("SELECT next_index FROM reader_agent_import_plans").fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT version FROM reader_agent_stories").fetchone()[0] == 0
    assert deliver(agents, secret, plan, chapter(1))["outcome"] == "imported"


def test_legacy_status_duplicate_and_continuation_numbering(repository, managed):
    agents, _, secret = managed
    legacy = agents.create_article(secret, title="Legacy", text="Intro")
    agents.deliver_chapter(secret, legacy.id, chapter(1), expected_row_version=1)
    with pytest.raises(AgentConflictError, match="already has a delivery"):
        prepare(agents, secret, [chapter(1)])
    plan = prepare(agents, secret, [chapter(3)])
    assert plan["parts"][0]["number"] == 2
    deliver(agents, secret, plan, chapter(3))
    first = agents.story_status(secret, story_key="story", limit=1)
    assert first["items"][0]["managed"] is False
    assert first["next_offset"] == 1
    second = agents.story_status(secret, story_key="story", offset=1, limit=1)
    assert second["items"][0]["managed"] is True
    assert second["discontinuities"] == [{"previous_order_index": 1, "order_index": 3}]
    assert second["next_offset"] is None


@pytest.mark.parametrize("action", ["revoke", "move", "delete", "physical", "privacy"])
def test_scope_and_removed_content_never_resurrect(repository, managed, action):
    agents, grant, secret = managed
    plan = prepare(agents, secret)
    result = deliver(agents, secret, plan, chapter(1))
    document = repository.get_document(result["document_id"])
    if action == "revoke":
        agents.revoke(grant.id)
    elif action == "move":
        from reader_core import FolderDocumentVersion

        repository.move_documents(
            (FolderDocumentVersion(document.id, document.row_version),), folder_id=None
        )
    elif action == "delete":
        repository.soft_delete_document(document.id, expected_row_version=document.row_version)
    elif action == "physical":
        with repository._write() as connection:
            connection.execute("DELETE FROM reader_documents WHERE id = ?", (document.id,))
    else:
        from reader_core import ReaderFolderPrivacy

        repository.set_folder_privacy(
            ReaderFolderPrivacy(grant.folder_id, "x" * 64, "y" * 64, utc_now()),
            expected_row_version=1,
        )
    with pytest.raises(AgentUnauthorizedError):
        deliver(agents, secret, plan, chapter(1))


def test_existing_legacy_soft_delete_blocks_preview(repository, managed):
    agents, _, secret = managed
    legacy = agents.create_article(secret, title="Legacy", text="Intro")
    receipt = agents.deliver_chapter(secret, legacy.id, chapter(1), expected_row_version=1)
    repository.soft_delete_document(legacy.id, expected_row_version=receipt.result_row_version)
    with pytest.raises(AgentConflictError):
        prepare(agents, secret, [chapter(1)])


def test_physical_purge_blocks_next_chapter_and_fresh_story_plan(repository, managed):
    agents, _, secret = managed
    plan = prepare(agents, secret)
    result = deliver(agents, secret, plan, chapter(1))
    with repository._write() as connection:
        connection.execute("DELETE FROM reader_documents WHERE id = ?", (result["document_id"],))
    with pytest.raises(AgentUnauthorizedError):
        deliver(agents, secret, plan, chapter(2))
    with pytest.raises(AgentUnauthorizedError):
        prepare(agents, secret, [chapter(1)], retry_key="fresh")
    assert agents.list_articles(secret).items == ()


def test_new_m1_delivery_invalidates_pending_plan_and_global_duplicate_is_refused(managed):
    agents, _, secret = managed
    legacy = agents.create_article(secret, title="Legacy", text="Intro")
    plan = prepare(agents, secret)
    agents.deliver_chapter(secret, legacy.id, chapter(4), expected_row_version=1)
    with pytest.raises(AgentConflictError, match="story changed"):
        deliver(agents, secret, plan, chapter(1))
    newer = prepare(agents, secret, [chapter(1)], retry_key="newer")
    result = deliver(agents, secret, newer, chapter(1))
    with pytest.raises(AgentConflictError):
        agents.deliver_chapter(secret, legacy.id, chapter(1), expected_row_version=2)
    assert agents.read_article(secret, result["document_id"]).text == "T\n\nabcdefgh"


def test_other_folder_plan_is_not_addressable(repository, managed):
    agents, _, secret = managed
    plan = prepare(agents, secret)
    now = utc_now()
    other = repository.create_folder(ReaderFolder(str(uuid.uuid4()), "Other", "other", now, now))
    _, other_secret = agents.provision(other.id, "Other agent")
    with pytest.raises(AgentUnauthorizedError):
        agents.import_target(other_secret, plan["plan_id"], "1")
    with pytest.raises(AgentUnauthorizedError):
        deliver(agents, other_secret, plan, chapter(1))
    assert agents.story_status(other_secret, story_key="story")["items"] == []


def test_plan_quota_and_permission_allowlist(managed, monkeypatch):
    from reader_core.sqlite import agent_imports

    agents, grant, secret = managed
    monkeypatch.setattr(agent_imports, "MAX_FOLDER_IMPORT_PLANS", 1)
    prepare(agents, secret)
    assert prepare(agents, secret)["outcome"] == "already_prepared"
    with pytest.raises(ReaderValidationError, match="256"):
        prepare(agents, secret, [chapter(4)], retry_key="second")
    _, limited = agents.provision(grant.folder_id, "Read only", operations=("create", "read"))
    with pytest.raises(AgentUnauthorizedError):
        prepare(agents, limited, [chapter(5)], retry_key="limited")


def test_cross_article_managed_operations_require_list_permission(managed):
    agents, grant, secret = managed
    plan = prepare(agents, secret)
    _, limited = agents.provision(
        grant.folder_id, "No list", operations=("create", "deliver", "chapters")
    )
    for operation in (
        lambda: prepare(agents, limited, [chapter(4)], retry_key="limited"),
        lambda: agents.import_target(limited, plan["plan_id"], "1"),
        lambda: agents.deliver_import_chapter(
            limited, plan_id=plan["plan_id"], delivery=chapter(1), lease_document_id=None
        ),
        lambda: agents.story_status(limited, story_key="story"),
    ):
        with pytest.raises(AgentUnauthorizedError):
            operation()
    # Explicit M1 article creation still follows its narrower create permission.
    assert agents.create_article(limited, title="M1", text="Allowed").title == "M1"
