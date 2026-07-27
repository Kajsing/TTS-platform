from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from document_import import (
    ImportedDocument,
    ImportLimits,
    ImportOptions,
    ImportSource,
    import_document,
)
from reader_core import (
    BlockKind,
    DocumentPage,
    DocumentState,
    ReaderBlock,
    ReaderDatabaseReport,
    ReaderDocument,
    ReaderDocumentBundle,
    ReaderError,
    ReaderLibrary,
    ReaderSection,
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


@dataclass(frozen=True, slots=True)
class ReaderImportPreviewNotFoundError(ReaderError):
    preview_id: str


@dataclass(frozen=True, slots=True)
class ReaderImportPreviewCapacityError(ReaderError):
    pass


@dataclass(frozen=True, slots=True)
class ReaderImportPreview:
    id: str
    imported: ImportedDocument
    duplicate_document_id: str | None
    copy_source_file: bool
    source_data: bytes | None
    created_at_monotonic: float


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
        managed_files_path: Path | None = None,
    ) -> None:
        self.repository = repository
        self.config = config
        self.library = ReaderLibrary(repository)
        self.observability = observability
        self.content_leases = ReaderContentLeaseRegistry()
        configured_managed_path = Path(config.managed_files_path).expanduser()
        self.managed_files_path = managed_files_path or (
            configured_managed_path
            if configured_managed_path.is_absolute()
            else Path(config.home_path).expanduser() / configured_managed_path
        )
        self._import_previews: dict[str, ReaderImportPreview] = {}
        self._import_preview_lock = threading.RLock()

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

    def create_import_preview(
        self,
        *,
        source: ImportSource,
        options: ImportOptions,
        copy_source_file: bool | None,
        cancellation: threading.Event | None = None,
    ) -> ReaderImportPreview:
        imported = import_document(
            source,
            options=options,
            limits=self._import_limits(),
            cancellation=cancellation,
        )
        duplicate = self.repository.find_document_by_source_hash(imported.source_sha256)
        resolved_copy = (
            self.config.copy_imported_files
            if copy_source_file is None
            else copy_source_file
        )
        preview = ReaderImportPreview(
            id=str(uuid.uuid4()),
            imported=imported,
            duplicate_document_id=duplicate.id if duplicate is not None else None,
            copy_source_file=resolved_copy,
            source_data=source.data if resolved_copy else None,
            created_at_monotonic=time.monotonic(),
        )
        with self._import_preview_lock:
            self._purge_import_previews_locked()
            retained_characters = sum(
                item.imported.total_characters for item in self._import_previews.values()
            )
            if (
                retained_characters + imported.total_characters
                > self.config.imports.max_document_characters
            ):
                raise ReaderImportPreviewCapacityError()
            self._import_previews[preview.id] = preview
        self._log_import(
            operation="import_preview",
            imported=imported,
            outcome="success",
        )
        return preview

    def commit_import_preview(
        self,
        preview_id: str,
        *,
        allow_duplicate: bool,
    ) -> ReaderDocument:
        with self._import_preview_lock:
            self._purge_import_previews_locked()
            preview = self._import_previews.get(preview_id)
        if preview is None:
            raise ReaderImportPreviewNotFoundError(preview_id)
        document = self._persist_import(
            preview.imported,
            source_data=preview.source_data,
            copy_source_file=preview.copy_source_file,
            allow_duplicate=allow_duplicate,
        )
        with self._import_preview_lock:
            self._import_previews.pop(preview_id, None)
        return document

    def cancel_import_preview(self, preview_id: str) -> None:
        with self._import_preview_lock:
            self._purge_import_previews_locked()
            preview = self._import_previews.pop(preview_id, None)
        if preview is None:
            raise ReaderImportPreviewNotFoundError(preview_id)

    def import_source(
        self,
        *,
        source: ImportSource,
        options: ImportOptions,
        copy_source_file: bool | None,
        allow_duplicate: bool,
        cancellation: threading.Event | None = None,
    ) -> ReaderDocument:
        imported = import_document(
            source,
            options=options,
            limits=self._import_limits(),
            cancellation=cancellation,
        )
        resolved_copy = (
            self.config.copy_imported_files
            if copy_source_file is None
            else copy_source_file
        )
        return self._persist_import(
            imported,
            source_data=source.data if resolved_copy else None,
            copy_source_file=resolved_copy,
            allow_duplicate=allow_duplicate,
        )

    def duplicate_as_editable_text(self, document_id: str) -> ReaderDocument:
        bundle = self.repository.get_document_bundle(document_id)
        text = "\n\n".join(block.text for block in bundle.blocks if block.text.strip())
        return self.create_text_document(
            title=f"Copy of {bundle.document.title}"[:500],
            text=text,
            source_type=SourceType.PLAIN_TEXT,
            language_hint=bundle.document.language_hint,
            allow_duplicate=True,
        )

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

    def _persist_import(
        self,
        imported: ImportedDocument,
        *,
        source_data: bytes | None,
        copy_source_file: bool,
        allow_duplicate: bool,
    ) -> ReaderDocument:
        duplicate = self.repository.find_document_by_source_hash(imported.source_sha256)
        if duplicate is not None and not allow_duplicate:
            raise ReaderDuplicateDocumentError(duplicate.id)
        bundle = _reader_bundle_from_import(imported)
        managed_path: Path | None = None
        if copy_source_file:
            if source_data is None:
                raise ValueError("Copied imports require source bytes.")
            managed_path = self._write_managed_source(
                bundle.document.id,
                imported.source_format,
                source_data,
            )
            bundle = _bundle_with_source_uri(
                bundle,
                f"managed/{managed_path.name}",
            )
        try:
            document = self.repository.create_document(bundle)
        except Exception:
            if managed_path is not None:
                managed_path.unlink(missing_ok=True)
            raise
        self._log_import(
            operation="import_document",
            imported=imported,
            outcome="success",
            document_id=document.id,
        )
        return document

    def _write_managed_source(
        self,
        document_id: str,
        source_format: str,
        data: bytes,
    ) -> Path:
        extension = {
            "txt": ".txt",
            "md": ".md",
            "html": ".html",
            "docx": ".docx",
            "epub": ".epub",
        }[source_format]
        self.managed_files_path.mkdir(parents=True, exist_ok=True)
        destination = self.managed_files_path / f"{document_id}{extension}"
        temporary = self.managed_files_path / f".{document_id}{extension}.tmp"
        try:
            with temporary.open("xb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _import_limits(self) -> ImportLimits:
        config = self.config.imports
        return ImportLimits(
            max_file_bytes=config.max_file_bytes,
            max_expanded_archive_bytes=config.max_expanded_archive_bytes,
            max_archive_members=config.max_archive_members,
            max_document_characters=config.max_document_characters,
            max_blocks=config.max_blocks,
            timeout_seconds=config.timeout_seconds,
        )

    def _purge_import_previews_locked(self) -> None:
        cutoff = time.monotonic() - 600
        expired = [
            preview_id
            for preview_id, preview in self._import_previews.items()
            if preview.created_at_monotonic < cutoff
        ]
        for preview_id in expired:
            self._import_previews.pop(preview_id, None)

    def _log_import(
        self,
        *,
        operation: str,
        imported: ImportedDocument,
        outcome: str,
        document_id: str | None = None,
    ) -> None:
        self.observability.log_reader_operation(
            operation=operation,
            document_id=document_id,
            character_count=imported.total_characters,
            block_count=len(imported.blocks),
            extra={
                "format": imported.source_format,
                "warning_count": len(imported.warnings),
                "outcome": outcome,
            },
        )


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
                managed_files_path=paths.managed_files,
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


def _reader_bundle_from_import(imported: ImportedDocument) -> ReaderDocumentBundle:
    document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    section_ids = {section.ordinal: str(uuid.uuid4()) for section in imported.sections}
    sections = tuple(
        ReaderSection(
            id=section_ids[section.ordinal],
            document_id=document_id,
            ordinal=section.ordinal,
            level=section.level,
            heading=section.heading,
            first_block_ordinal=section.first_block_ordinal,
            parent_section_id=(
                section_ids[section.parent_ordinal]
                if section.parent_ordinal is not None
                else None
            ),
            metadata=section.metadata,
        )
        for section in imported.sections
    )
    blocks = tuple(
        ReaderBlock(
            id=str(uuid.uuid4()),
            document_id=document_id,
            section_id=section_ids[block.section_ordinal],
            ordinal=block.ordinal,
            kind=BlockKind(block.kind),
            text=block.text,
            character_count=len(block.text),
            content_sha256=hashlib.sha256(block.text.encode("utf-8")).hexdigest(),
            metadata=block.metadata,
        )
        for block in imported.blocks
    )
    source_type = {
        "txt": SourceType.TEXT_FILE,
        "md": SourceType.MARKDOWN,
        "html": SourceType.HTML,
        "docx": SourceType.DOCX,
        "epub": SourceType.EPUB,
    }[imported.source_format]
    document = ReaderDocument(
        id=document_id,
        title=imported.title,
        source_type=source_type,
        source_name=imported.source_name,
        source_sha256=imported.source_sha256,
        language_hint=imported.language_hint,
        state=DocumentState.INBOX,
        created_at=now,
        updated_at=now,
        imported_at=now,
        total_sections=len(sections),
        total_blocks=len(blocks),
        total_characters=imported.total_characters,
        metadata={
            "import": {
                "format": imported.source_format,
                "importer_version": imported.importer_version,
                "warnings": [warning.to_metadata() for warning in imported.warnings],
                **dict(imported.metadata),
            }
        },
    )
    return ReaderDocumentBundle(document=document, sections=sections, blocks=blocks)


def _bundle_with_source_uri(
    bundle: ReaderDocumentBundle,
    source_uri: str,
) -> ReaderDocumentBundle:
    updated = replace(bundle.document, source_uri=source_uri)
    return ReaderDocumentBundle(document=updated, sections=bundle.sections, blocks=bundle.blocks)
