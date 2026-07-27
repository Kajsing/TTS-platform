from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from reader_core import (
    DocumentPage,
    DocumentState,
    ReaderBlock,
    ReaderDatabaseReport,
    ReaderDocument,
    ReaderDocumentBundle,
    ReaderError,
    ReaderLibrary,
    SourceType,
    SqliteReaderRepository,
    resolve_reader_paths,
)

from .config import ReaderConfig
from .observability import ObservabilityState


@dataclass(frozen=True, slots=True)
class ReaderDuplicateDocumentError(ReaderError):
    document_id: str


@dataclass(frozen=True, slots=True)
class ReaderDocumentLockedError(ReaderError):
    document_id: str


class ReaderContentLeaseRegistry:
    """Serializes content mutations with active in-process Reader streams."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._owners_by_document: dict[str, set[str]] = {}

    @contextmanager
    def lease(self, document_id: str, owner_id: str) -> Iterator[None]:
        with self._lock:
            self._owners_by_document.setdefault(document_id, set()).add(owner_id)
        try:
            yield
        finally:
            with self._lock:
                owners = self._owners_by_document.get(document_id)
                if owners is not None:
                    owners.discard(owner_id)
                    if not owners:
                        self._owners_by_document.pop(document_id, None)

    @contextmanager
    def mutation(self, document_id: str) -> Iterator[None]:
        with self._lock:
            if self._owners_by_document.get(document_id):
                raise ReaderDocumentLockedError(document_id)
            yield

    def is_locked(self, document_id: str) -> bool:
        with self._lock:
            return bool(self._owners_by_document.get(document_id))

    def active_lease_count(self) -> int:
        with self._lock:
            return sum(len(owners) for owners in self._owners_by_document.values())


@dataclass(slots=True)
class ReaderRuntimeState:
    enabled: bool
    service: ReaderApplicationService | None = None
    database_report: ReaderDatabaseReport | None = None
    startup_error: str | None = None

    @property
    def database_ready(self) -> bool:
        return self.database_report is not None and self.database_report.ready

    @property
    def schema_version(self) -> int:
        return self.database_report.schema_version if self.database_report else 0

    def health_payload(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "database_ready": self.database_ready,
            "schema_version": self.schema_version,
            "startup_error": self.startup_error,
        }


class ReaderApplicationService:
    def __init__(
        self,
        repository: SqliteReaderRepository,
        *,
        config: ReaderConfig,
        observability: ObservabilityState,
    ) -> None:
        self.repository = repository
        self.config = config
        self.library = ReaderLibrary(repository)
        self.observability = observability
        self.content_leases = ReaderContentLeaseRegistry()

    def create_text_document(
        self,
        *,
        title: str,
        text: str,
        source_type: SourceType,
        language_hint: str | None,
        allow_duplicate: bool,
    ) -> ReaderDocument:
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        duplicate = self.repository.find_document_by_source_hash(source_hash)
        if duplicate is not None and not allow_duplicate:
            raise ReaderDuplicateDocumentError(duplicate.id)
        document = self.library.create_plain_text_document(
            title=title,
            text=text,
            source_type=source_type,
            language_hint=language_hint,
        )
        self.observability.log_reader_operation(
            operation="create_document",
            document_id=document.id,
            character_count=document.total_characters,
            block_count=document.total_blocks,
        )
        return document

    def list_documents(
        self,
        *,
        state: DocumentState | None,
        query: str | None,
        limit: int,
        cursor: str | None,
    ) -> DocumentPage:
        return self.repository.list_documents(
            state=state,
            query=query,
            limit=limit,
            cursor=cursor,
        )

    def get_document(self, document_id: str) -> ReaderDocument:
        return self.repository.get_document(document_id)

    def get_document_bundle(self, document_id: str) -> ReaderDocumentBundle:
        return self.repository.get_document_bundle(document_id)

    def content_lease(self, document_id: str, owner_id: str):
        return self.content_leases.lease(document_id, owner_id)

    def content_mutation(self, document_id: str):
        return self.content_leases.mutation(document_id)

    def list_blocks(
        self,
        document_id: str,
        *,
        after_ordinal: int,
        limit: int,
    ) -> tuple[ReaderBlock, ...]:
        return self.repository.list_blocks(
            document_id,
            after_ordinal=after_ordinal,
            limit=limit,
        )

    def log_mutation(
        self,
        operation: str,
        document: ReaderDocument,
        *,
        block_id: str | None = None,
        character_count: int | None = None,
    ) -> None:
        self.observability.log_reader_operation(
            operation=operation,
            document_id=document.id,
            block_id=block_id,
            character_count=character_count,
            block_count=document.total_blocks,
        )

    def next_queue_ordinal(self) -> int:
        queue = self.repository.list_queue()
        return max((item.ordinal for item in queue), default=-1) + 1


def initialize_reader_runtime(
    config: ReaderConfig,
    *,
    observability: ObservabilityState,
    env: dict[str, str] | None = None,
) -> ReaderRuntimeState:
    if not config.enabled:
        return ReaderRuntimeState(enabled=False)
    try:
        paths = resolve_reader_paths(
            home_path=config.home_path,
            database_path=config.database_path,
            managed_files_path=config.managed_files_path,
            env=env,
        )
        repository = SqliteReaderRepository(
            paths.database,
            max_edit_history_operations=config.max_edit_history_operations,
            max_edit_history_bytes=config.max_edit_history_bytes,
        )
        report = repository.report()
        return ReaderRuntimeState(
            enabled=True,
            service=ReaderApplicationService(
                repository,
                config=config,
                observability=observability,
            ),
            database_report=report,
        )
    except (ReaderError, OSError) as exc:
        if observability.enabled:
            observability.logger.error(
                json.dumps(
                    {
                        "event": "reader_startup_failed",
                        "error_type": type(exc).__name__,
                    }
                )
            )
        return ReaderRuntimeState(
            enabled=True,
            startup_error="Reader database initialization failed.",
        )
