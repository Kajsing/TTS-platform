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
    ReaderNotFoundError,
    ReaderSection,
    RuleScope,
    RuleStage,
    RuleType,
    SourceType,
    SpeechRule,
    SpeechRuleSet,
    SqliteReaderRepository,
    resolve_reader_paths,
)
from speech_rules import (
    ImportedRuleCandidate,
    ParsedRuleSet,
    RuleApplication,
    RuleContext,
    RuleEngineLimits,
    SpeechRuleEngine,
    SpeechRuleValidationError,
    candidate_signature,
    export_rule_set,
    order_rules,
    parse_rule_set,
    rule_signature,
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


@dataclass(frozen=True, slots=True)
class ReaderRuleImportReport:
    source_sha256: str
    imported: int
    disabled: int
    duplicate: int
    invalid: int
    unsupported: int
    committed: bool
    idempotent: bool = False


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

    def create_rule_set(
        self,
        *,
        name: str,
        description: str,
        scope: RuleScope,
    ) -> SpeechRuleSet:
        now = datetime.now(timezone.utc)
        return self.repository.create_rule_set(
            SpeechRuleSet(
                id=str(uuid.uuid4()),
                name=name.strip(),
                description=description.strip(),
                scope=scope,
                created_at=now,
                updated_at=now,
            )
        )

    def create_rule(
        self,
        *,
        rule_set_id: str,
        name: str,
        stage: RuleStage,
        rule_type: RuleType,
        pattern: str,
        replacement: str,
        enabled: bool = True,
        case_sensitive: bool = False,
        whole_word: bool = False,
        language_filter: str | None = None,
        engine_filter: str | None = None,
        voice_filter: str | None = None,
        document_filter: str | None = None,
        priority: int = 100,
        regex_timeout_ms: int | None = None,
        raw_import_metadata: dict[str, object] | None = None,
    ) -> SpeechRule:
        self.repository.get_rule_set(rule_set_id)
        now = datetime.now(timezone.utc)
        rule = SpeechRule(
            id=str(uuid.uuid4()),
            rule_set_id=rule_set_id,
            name=name.strip(),
            stage=stage,
            rule_type=rule_type,
            pattern=pattern,
            replacement=replacement,
            enabled=enabled,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
            language_filter=language_filter,
            engine_filter=engine_filter,
            voice_filter=voice_filter,
            document_filter=document_filter,
            priority=priority,
            regex_timeout_ms=(
                regex_timeout_ms
                if regex_timeout_ms is not None
                else self.config.rules.default_regex_timeout_ms
            ),
            created_at=now,
            updated_at=now,
            raw_import_metadata=raw_import_metadata or {},
        )
        self.rule_engine().validate_rule(rule)
        return self.repository.create_rule(rule)

    def preview_rules(
        self,
        text: str,
        *,
        rule_set_ids: tuple[str, ...],
        context: RuleContext,
    ) -> RuleApplication:
        rules = self.ordered_rules(rule_set_ids)
        return self.rule_engine().apply(text, rules, context=context)

    def ordered_rules(self, rule_set_ids: tuple[str, ...]) -> tuple[SpeechRule, ...]:
        if not self.config.rules.enabled:
            return ()
        rule_sets = {item.id: item for item in self.repository.list_rule_sets()}
        if not rule_set_ids:
            rule_set_ids = tuple(
                item.id for item in rule_sets.values() if item.enabled
            )
        missing = [rule_set_id for rule_set_id in rule_set_ids if rule_set_id not in rule_sets]
        if missing:
            raise ReaderNotFoundError("rule set", missing[0])
        rules = self.repository.list_rules(rule_set_ids)
        return order_rules(rules, {key: value.scope for key, value in rule_sets.items()})

    def rule_engine(self) -> SpeechRuleEngine:
        config = self.config.rules
        return SpeechRuleEngine(
            RuleEngineLimits(
                default_regex_timeout_ms=config.default_regex_timeout_ms,
                max_regex_pattern_chars=config.max_regex_pattern_chars,
                max_replacement_chars=config.max_replacement_chars,
                max_rule_time_per_block_ms=config.max_rule_time_per_block_ms,
            )
        )

    def import_rules(
        self,
        *,
        target_rule_set_id: str,
        source_data: bytes,
        commit: bool,
    ) -> ReaderRuleImportReport:
        self.repository.get_rule_set(target_rule_set_id)
        parsed = parse_rule_set(source_data)
        previous = self.repository.get_rule_import_report(
            target_rule_set_id, parsed.source_sha256
        )
        if commit and previous is not None:
            return ReaderRuleImportReport(
                source_sha256=parsed.source_sha256,
                imported=int(previous.get("imported", 0)),
                disabled=int(previous.get("disabled", 0)),
                duplicate=int(previous.get("duplicate", 0)),
                invalid=int(previous.get("invalid", 0)),
                unsupported=int(previous.get("unsupported", 0)),
                committed=True,
                idempotent=True,
            )
        report, importable = self._prepare_rule_import(target_rule_set_id, parsed)
        if not commit:
            return report
        for candidate in importable:
            self.create_rule(
                rule_set_id=target_rule_set_id,
                name=candidate.name,
                stage=candidate.stage,
                rule_type=candidate.rule_type,
                pattern=candidate.pattern,
                replacement=candidate.replacement,
                enabled=candidate.enabled,
                case_sensitive=candidate.case_sensitive,
                whole_word=candidate.whole_word,
                language_filter=candidate.language_filter,
                engine_filter=candidate.engine_filter,
                voice_filter=candidate.voice_filter,
                document_filter=candidate.document_filter,
                priority=candidate.priority,
                regex_timeout_ms=candidate.regex_timeout_ms,
                raw_import_metadata=dict(candidate.raw_import_metadata),
            )
        committed = replace(report, committed=True, imported=len(importable))
        self.repository.record_rule_import(
            target_rule_set_id,
            parsed.source_sha256,
            {
                "imported": committed.imported,
                "disabled": committed.disabled,
                "duplicate": committed.duplicate,
                "invalid": committed.invalid,
                "unsupported": committed.unsupported,
            },
        )
        return committed

    def _prepare_rule_import(
        self,
        target_rule_set_id: str,
        parsed: ParsedRuleSet,
    ) -> tuple[ReaderRuleImportReport, tuple[ImportedRuleCandidate, ...]]:
        existing = {
            rule_signature(rule)
            for rule in self.repository.list_rules((target_rule_set_id,))
        }
        importable = []
        duplicates = 0
        invalid = parsed.invalid_count
        engine = self.rule_engine()
        for candidate in parsed.candidates:
            if candidate_signature(candidate) in existing:
                duplicates += 1
                continue
            try:
                probe = self._candidate_probe(target_rule_set_id, candidate)
                engine.validate_rule(probe)
            except (ReaderError, SpeechRuleValidationError):
                invalid += 1
                continue
            importable.append(candidate)
        return (
            ReaderRuleImportReport(
                source_sha256=parsed.source_sha256,
                imported=0,
                disabled=sum(not candidate.enabled for candidate in importable),
                duplicate=duplicates,
                invalid=invalid,
                unsupported=parsed.unsupported_count,
                committed=False,
            ),
            tuple(importable),
        )

    @staticmethod
    def _candidate_probe(
        rule_set_id: str, candidate: ImportedRuleCandidate
    ) -> SpeechRule:
        now = datetime.now(timezone.utc)
        return SpeechRule(
            id=str(uuid.uuid4()),
            rule_set_id=rule_set_id,
            name=candidate.name,
            enabled=candidate.enabled,
            stage=candidate.stage,
            rule_type=candidate.rule_type,
            pattern=candidate.pattern,
            replacement=candidate.replacement,
            case_sensitive=candidate.case_sensitive,
            whole_word=candidate.whole_word,
            language_filter=candidate.language_filter,
            engine_filter=candidate.engine_filter,
            voice_filter=candidate.voice_filter,
            document_filter=candidate.document_filter,
            priority=candidate.priority,
            regex_timeout_ms=candidate.regex_timeout_ms,
            created_at=now,
            updated_at=now,
            raw_import_metadata=candidate.raw_import_metadata,
        )

    def export_rules(self, rule_set_id: str) -> bytes:
        rule_set = self.repository.get_rule_set(rule_set_id)
        rules = self.repository.list_rules((rule_set_id,))
        return export_rule_set(rule_set, rules)

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
