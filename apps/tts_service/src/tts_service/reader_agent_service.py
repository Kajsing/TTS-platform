"""Application orchestration for agent operations, independent of MCP/HTTP."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Protocol

from reader_core.agent_access import AgentUnauthorizedError
from reader_core.sqlite.agent_repository import SqliteReaderAgentRepository
from reader_core.sqlite.repository import SqliteReaderRepository


class ContentLeases(Protocol):
    def mutation(self, document_id: str) -> AbstractContextManager[None]: ...


class ReaderAgentService:
    def __init__(self, repository: SqliteReaderRepository, content_leases: ContentLeases) -> None:
        self.store = SqliteReaderAgentRepository(repository)
        self._leases = content_leases

    def run(self, credential: str, operation: str, **arguments):
        operations = {
            "workspace": self.store.workspace,
            "list": self.store.list_articles,
            "read": self.store.read_article,
            "create": self.store.create_article,
            "rename": self.store.rename_article,
            "append": self.store.append_article,
            "replace": self.store.replace_text,
            "chapters": self.store.list_chapters,
            "deliver": self.store.deliver_chapter,
            "content_chapters": self.store.list_content_chapters,
            "chapter_text": self.store.read_chapter,
            "search": self.store.search_article,
            "preview_import": self.store.preview_import,
            "import_chapter": self.store.deliver_import_chapter,
            "story_status": self.store.story_status,
        }
        if operation not in operations:
            raise AgentUnauthorizedError()
        document_id = arguments.get("document_id")
        permission = (
            "read" if operation in {"content_chapters", "chapter_text", "search"} else operation
        )
        permission = {"preview_import": "create", "import_chapter": "deliver",
                      "story_status": "chapters"}.get(permission, permission)
        self.store.authorize(credential, permission, document_id)
        if operation == "import_chapter":
            target = self.store.import_target(
                credential, arguments["plan_id"], arguments["delivery"].chapter_key
            )
            with self._leases.mutation(target) if target is not None else nullcontext():
                return self.store.deliver_import_chapter(
                    credential, **arguments, lease_document_id=target
                )
        mutation = document_id is not None and operation in {
            "rename",
            "append",
            "replace",
            "deliver",
        }
        # Same lock order as normal Reader writes: playback lease, then DB.
        # Authorization is repeated in the DB transaction after acquiring it.
        with self._leases.mutation(document_id) if mutation else nullcontext():
            return operations[operation](credential, **arguments)
