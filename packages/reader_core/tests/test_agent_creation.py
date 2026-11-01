from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from reader_core import FolderDocumentVersion, ReaderFolder, SqliteReaderRepository
from reader_core.agent_access import AgentConflictError, AgentUnauthorizedError
from reader_core.models import utc_now
from reader_core.sqlite.agent_repository import SqliteReaderAgentRepository


def provision(repository):
    now = utc_now()
    folder = repository.create_folder(
        ReaderFolder(str(uuid.uuid4()), "Imports", "imports", now, now)
    )
    agents = SqliteReaderAgentRepository(repository)
    grant, secret = agents.provision(folder.id, "Creator")
    return agents, grant, secret


def test_creation_restart_replay_changed_payload_and_owner_edits(repository):
    agents, grant, secret = provision(repository)
    args = {"title": "Story", "text": "Original.", "retry_key": "create-1"}
    created = agents.create_article(secret, **args)
    edited = agents.replace_text(
        secret, created.id, old_text="Original", new_text="Corrected", expected_row_version=1
    )
    # New process and renewed credential reuse the folder's durable identity.
    agents.revoke(grant.id)
    reopened = SqliteReaderAgentRepository(SqliteReaderRepository(repository.database_path))
    _, renewed = reopened.provision(grant.folder_id, "Renewed")
    replay = reopened.create_article(renewed, **args)
    assert replay.id == created.id and replay.row_version == edited.row_version
    assert reopened.read_article(renewed, created.id).text == "Corrected."
    with pytest.raises(AgentConflictError):
        reopened.create_article(renewed, **(args | {"text": "Other."}))
    with pytest.raises(AgentUnauthorizedError):
        reopened.create_article(secret, **args)
    assert len(reopened.list_articles(renewed).items) == 1


@pytest.mark.parametrize("action", ["move", "delete"])
def test_creation_replay_cannot_restore_removed_content(repository, action):
    agents, _, secret = provision(repository)
    args = {"title": "Story", "text": "Kept.", "retry_key": "create-1"}
    created = agents.create_article(secret, **args)
    if action == "move":
        repository.move_documents((FolderDocumentVersion(created.id, 1),), folder_id=None)
    else:
        repository.soft_delete_document(created.id, expected_row_version=1)
    with pytest.raises(AgentUnauthorizedError):
        agents.create_article(secret, **args)
    assert agents.list_articles(secret).items == ()


def test_concurrent_creation_commits_once(repository):
    _, _, secret = provision(repository)

    def create(_):
        agents = SqliteReaderAgentRepository(SqliteReaderRepository(repository.database_path))
        return agents.create_article(secret, title="One", text="Body.", retry_key="same").id

    with ThreadPoolExecutor(max_workers=4) as pool:
        identifiers = tuple(pool.map(create, range(8)))
    assert len(set(identifiers)) == 1


def test_creation_rolls_back_if_identity_cannot_commit(repository):
    agents, _, secret = provision(repository)
    with repository._write() as connection:
        connection.execute(
            "CREATE TRIGGER fail_creation BEFORE INSERT ON reader_agent_creations "
            "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
    from reader_core.errors import ReaderDatabaseError

    with pytest.raises(ReaderDatabaseError):
        agents.create_article(secret, title="One", text="Body.", retry_key="same")
    assert agents.list_articles(secret).items == ()
