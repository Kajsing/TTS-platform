from __future__ import annotations

import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from reader_core import (
    FolderDeleteMode,
    FolderDocumentVersion,
    ReaderConflictError,
    ReaderDatabaseError,
    ReaderFolder,
    ReaderFolderPrivacy,
    ReaderLibrary,
    ReaderValidationError,
    SqliteReaderRepository,
)
from reader_core.agent_access import AgentConflictError, AgentUnauthorizedError, ChapterDelivery
from reader_core.models import utc_now
from reader_core.sqlite.agent_repository import SqliteReaderAgentRepository


def folder(repository, name="Agent inbox"):
    now = utc_now()
    return repository.create_folder(
        ReaderFolder(str(uuid.uuid4()), name, name.casefold(), now, now)
    )


@pytest.fixture
def access(repository):
    workspace = folder(repository)
    agents = SqliteReaderAgentRepository(repository)
    grant, secret = agents.provision(workspace.id, "Test agent")
    article = agents.create_article(secret, title="Story", text="Opening.\n\nAnother paragraph.")
    return agents, grant, secret, article


def delivery(**changes):
    return ChapterDelivery(
        **(
            {
                "story_key": "fiction:story",
                "chapter_key": "chapter:2",
                "retry_key": "attempt:1",
                "source_url": "https://example.com/story/chapter2",
                "title": "Chapter two",
                "text": "New chapter.\n\nA second paragraph!",
                "order_label": "Interlude",
                "order_index": 2,
            }
            | changes
        )
    )


def test_default_off_hash_storage_and_persistent_grant(repository):
    agents = SqliteReaderAgentRepository(repository)
    assert agents.list_grants() == ()
    workspace = folder(repository)
    grant, secret = agents.provision(workspace.id, "Test agent")
    with repository._connection() as connection:
        row = dict(connection.execute("SELECT * FROM reader_agent_grants").fetchone())
    assert secret not in str(row)
    assert len(row["credential_hash"]) == 64
    reopened = SqliteReaderAgentRepository(SqliteReaderRepository(repository.database_path))
    assert reopened.workspace(secret)[0] == grant
    assert reopened.workspace(secret)[1].id == workspace.id
    agents.revoke(grant.id)
    agents.revoke(grant.id)
    with pytest.raises(AgentUnauthorizedError):
        reopened.workspace(secret)


def test_article_tools_scope_revision_pagination_and_history(repository, access):
    agents, grant, secret, article = access
    hidden = ReaderLibrary(repository).create_plain_text_document(
        title="Private outside",
        text="Secret needle",
        folder_id=folder(repository, "Other").id,
    )
    assert agents.list_articles(secret, query="Secret").items == ()
    assert [item.id for item in agents.list_articles(secret).items] == [article.id]
    for identifier in (hidden.id, str(uuid.uuid4())):
        with pytest.raises(AgentUnauthorizedError):
            agents.read_article(secret, identifier)
        with pytest.raises(AgentUnauthorizedError):
            agents.append_article(secret, identifier, text="Escape", expected_row_version=1)
        with pytest.raises(AgentUnauthorizedError):
            agents.deliver_chapter(secret, identifier, delivery(), expected_row_version=1)
    page = agents.read_article(secret, article.id, limit=5)
    assert page.text == "Openi" and page.next_offset == 5
    with pytest.raises(ReaderValidationError):
        agents.read_article(secret, article.id, offset=5)
    remainder = agents.read_article(secret, article.id, offset=5, expected_row_version=1)
    assert page.text + remainder.text == "Opening.\n\nAnother paragraph."
    renamed = agents.rename_article(secret, article.id, title="New title", expected_row_version=1)
    assert renamed.folder_id == grant.folder_id
    with pytest.raises(ReaderConflictError):
        agents.read_article(secret, article.id, offset=5, expected_row_version=1)
    edited = agents.replace_text(
        secret,
        article.id,
        old_text="Opening",
        new_text="New opening 😃",
        expected_row_version=2,
    )
    with pytest.raises(ReaderConflictError):
        agents.append_article(secret, article.id, text="Stale", expected_row_version=2)
    # This is the ordinary desktop edit API, not a separate agent undo history.
    undone = repository.undo(article.id, expected_row_version=edited.row_version)
    assert agents.read_article(secret, article.id).text.startswith("Opening.")
    redone = repository.redo(article.id, expected_row_version=undone.row_version)
    assert agents.read_article(secret, article.id).text.startswith("New opening 😃.")
    appended = agents.append_article(
        secret,
        article.id,
        text="Last page.",
        expected_row_version=redone.row_version,
    )
    assert appended.total_blocks == 3


@pytest.mark.parametrize("text,needle", [("aaa", "aa"), ("a\n\na", "a")])
def test_ambiguous_replacement_including_overlapping_matches(repository, access, text, needle):
    agents, _, secret, _ = access
    article = agents.create_article(secret, title="Ambiguous", text=text)
    with pytest.raises(AgentConflictError, match="more than once"):
        agents.replace_text(
            secret,
            article.id,
            old_text=needle,
            new_text="x",
            expected_row_version=1,
        )
    assert repository.get_document(article.id).row_version == 1


@pytest.mark.parametrize("action", ["revoke", "move", "lock", "delete_folder", "delete_article"])
def test_scope_revocation_applies_to_reads_writes_and_import_retries(repository, access, action):
    agents, grant, secret, article = access
    agents.deliver_chapter(secret, article.id, delivery(), expected_row_version=1)
    if action == "revoke":
        agents.revoke(grant.id)
    elif action == "move":
        repository.move_documents((FolderDocumentVersion(article.id, 2),), folder_id=None)
    elif action == "lock":
        locked = repository.set_folder_privacy(
            ReaderFolderPrivacy(grant.folder_id, "x" * 64, "y" * 64, utc_now()),
            expected_row_version=1,
        )
        # Even removing Privacy lock cannot reactivate old agent grants.
        repository.clear_folder_privacy(grant.folder_id, expected_row_version=locked.row_version)
    elif action == "delete_folder":
        repository.delete_folder(
            grant.folder_id,
            expected_row_version=1,
            mode=FolderDeleteMode.MOVE_TO_ROOT,
        )
    else:
        repository.soft_delete_document(article.id, expected_row_version=2)
    for operation in (
        lambda: agents.read_article(secret, article.id),
        lambda: agents.list_chapters(secret, article.id),
        lambda: agents.rename_article(secret, article.id, title="No", expected_row_version=2),
        lambda: agents.replace_text(
            secret,
            article.id,
            old_text="Opening",
            new_text="No",
            expected_row_version=2,
        ),
        lambda: agents.append_article(secret, article.id, text="No", expected_row_version=2),
        lambda: agents.deliver_chapter(secret, article.id, delivery(), expected_row_version=1),
    ):
        with pytest.raises(AgentUnauthorizedError):
            operation()
    if action in {"move", "delete_article"}:
        assert not agents.list_articles(secret).items
    else:
        with pytest.raises(AgentUnauthorizedError):
            agents.list_articles(secret)
        with pytest.raises(AgentUnauthorizedError):
            agents.create_article(secret, title="No", text="No")


def test_explicit_allowlist_cannot_write_or_provision_locked_folder(repository, access):
    agents, grant, _, article = access
    _, read_only = agents.provision(grant.folder_id, "Read only", operations=("read",))
    assert agents.read_article(read_only, article.id).document.id == article.id
    for operation in ("create", "append", "replace", "rename", "deliver", "list", "chapters"):
        with pytest.raises(AgentUnauthorizedError):
            agents.authorize(read_only, operation, article.id)
    for operations in ((), ("delete",)):
        with pytest.raises(ReaderValidationError):
            agents.provision(grant.folder_id, "Invalid", operations=operations)
    repository.set_folder_privacy(
        ReaderFolderPrivacy(grant.folder_id, "x" * 64, "y" * 64, utc_now()),
        expected_row_version=1,
    )
    with pytest.raises(AgentUnauthorizedError):
        agents.provision(grant.folder_id, "Locked")


def test_restart_lost_response_new_retry_alias_and_payload_conflicts(repository, access):
    agents, _, secret, article = access
    original = agents.deliver_chapter(secret, article.id, delivery(), expected_row_version=1)
    reopened = SqliteReaderAgentRepository(SqliteReaderRepository(repository.database_path))
    for attempt in (delivery(), delivery(retry_key="attempt:2"), delivery(retry_key="attempt:2")):
        retry = reopened.deliver_chapter(secret, article.id, attempt, expected_row_version=1)
        assert retry == replace(original, outcome="already_imported")
    for changed in (
        delivery(text="Changed!"),
        delivery(source_url="https://example.com/elsewhere"),
        delivery(chapter_key="another"),
        delivery(order_index=3),
        delivery(title="Updated", retry_key="new"),
    ):
        with pytest.raises(AgentConflictError):
            agents.deliver_chapter(secret, article.id, changed, expected_row_version=2)
    assert repository.get_document(article.id).total_blocks == 4
    assert len(agents.list_chapters(secret, article.id)) == 1


def test_concurrent_duplicate_delivery_appends_once(repository, access):
    _, _, secret, article = access
    barrier = threading.Barrier(4)

    def send(index):
        worker = SqliteReaderAgentRepository(SqliteReaderRepository(repository.database_path))
        barrier.wait(timeout=10)
        return worker.deliver_chapter(
            secret,
            article.id,
            delivery(retry_key=f"concurrent:{index}"),
            expected_row_version=1,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = list(executor.map(send, range(4)))
    assert [receipt.outcome for receipt in receipts].count("imported") == 1
    assert len({receipt.id for receipt in receipts}) == 1
    assert repository.get_document(article.id).row_version == 2


def test_failed_receipt_write_rolls_back_text_and_history(repository, access, monkeypatch):
    agents, _, secret, article = access

    def fail(*args):
        raise sqlite3.OperationalError("injected commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(agents, "_record_retry", fail)
        with pytest.raises(ReaderDatabaseError):
            agents.deliver_chapter(secret, article.id, delivery(), expected_row_version=1)
    assert repository.get_document(article.id) == article
    assert agents.list_chapters(secret, article.id) == ()
    assert len(repository.get_document_bundle(article.id).blocks) == 2
    receipt = agents.deliver_chapter(secret, article.id, delivery(), expected_row_version=1)
    assert receipt.outcome == "imported"


def test_receipts_do_not_resurrect_undo_or_manual_removal(repository, access):
    agents, _, secret, article = access
    receipt = agents.deliver_chapter(secret, article.id, delivery(), expected_row_version=1)
    undone = repository.undo(article.id, expected_row_version=receipt.result_row_version)
    retry = agents.deliver_chapter(secret, article.id, delivery(), expected_row_version=1)
    assert retry.outcome == "already_imported"
    assert repository.get_document(article.id) == undone
    redone = repository.redo(article.id, expected_row_version=undone.row_version)
    removed = agents.replace_text(
        secret,
        article.id,
        old_text="New chapter.",
        new_text="",
        expected_row_version=redone.row_version,
    )
    agents.deliver_chapter(secret, article.id, delivery(), expected_row_version=1)
    assert repository.get_document(article.id) == removed
    assert "New chapter." not in agents.read_article(secret, article.id).text
    deleted = repository.soft_delete_document(article.id, expected_row_version=removed.row_version)
    repository.restore_document(article.id, expected_row_version=deleted.row_version)
    assert (
        agents.deliver_chapter(
            secret,
            article.id,
            delivery(),
            expected_row_version=1,
        ).outcome
        == "already_imported"
    )


def test_order_metadata_flags_nonincreasing_order_without_guessing_gaps(access):
    agents, _, secret, article = access
    first = agents.deliver_chapter(
        secret, article.id, delivery(order_index=20), expected_row_version=1
    )
    second = agents.deliver_chapter(
        secret,
        article.id,
        delivery(chapter_key="later", retry_key="later", order_index=200),
        expected_row_version=first.result_row_version,
    )
    assert second.order_warning is None
    third = agents.deliver_chapter(
        secret,
        article.id,
        delivery(chapter_key="interlude", retry_key="interlude", order_index=150),
        expected_row_version=second.result_row_version,
    )
    assert third.order_warning == "order_not_after_previous_delivery"
    assert third.order_label == "Interlude"
    assert len(agents.list_chapters(secret, article.id, offset=1, limit=1)) == 1


def test_actual_commit_failure_rolls_back_chapter_and_edit(repository, access, monkeypatch):
    from reader_core.sqlite import repository as repository_module

    agents, _, secret, article = access
    original_connect = repository_module.connect_sqlite

    class CommitFailure:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def commit(self):
            raise sqlite3.OperationalError("injected disk failure before commit")

    with monkeypatch.context() as patch:
        patch.setattr(
            repository_module, "connect_sqlite", lambda path: CommitFailure(original_connect(path))
        )
        with pytest.raises(ReaderDatabaseError):
            agents.deliver_chapter(secret, article.id, delivery(), expected_row_version=1)
    assert repository.get_document(article.id) == article
    assert agents.list_chapters(secret, article.id) == ()
    assert (
        agents.deliver_chapter(
            secret,
            article.id,
            delivery(),
            expected_row_version=1,
        ).outcome
        == "imported"
    )


def test_paged_text_exactly_matches_unicode_paragraph_separators(access):
    agents, _, secret, _ = access
    article = agents.create_article(secret, title="Unicode", text="ab😃.\n\ncdø.\n\nef.")
    expected = "ab😃.\n\ncdø.\n\nef."
    for offset in range(len(expected) + 1):
        for size in (1, 2, 5, 20):
            page = agents.read_article(
                secret, article.id, offset=offset, limit=size, expected_row_version=1
            )
            assert page.text == expected[offset : offset + size]
            assert page.text_length == len(expected)
