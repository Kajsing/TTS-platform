from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from .errors import ReaderValidationError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentState(str, Enum):
    INBOX = "inbox"
    ACTIVE = "active"
    FINISHED = "finished"
    ARCHIVED = "archived"


class SourceType(str, Enum):
    PLAIN_TEXT = "plain_text"
    CLIPBOARD = "clipboard"
    SELECTION = "selection"
    TEXT_FILE = "text_file"
    MARKDOWN = "markdown"
    HTML = "html"
    DOCX = "docx"
    EPUB = "epub"
    PDF = "pdf"
    BROWSER = "browser"
    MIGRATION = "migration"


class BlockKind(str, Enum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    QUOTE = "quote"
    TABLE_ROW = "table_row"
    CODE = "code"
    SEPARATOR = "separator"
    NOTE = "note"


class QueueStatus(str, Enum):
    QUEUED = "queued"
    PLAYING = "playing"
    COMPLETED = "completed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class HighlighterTerm:
    id: str
    term: str
    normalized_term: str
    active: bool
    color: str
    ordinal: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_id(self.id, "highlighter term id")
        _require_utc(self.created_at, "highlighter term created_at")
        _require_utc(self.updated_at, "highlighter term updated_at")
        if not self.term.strip() or len(self.term) > 200:
            raise ReaderValidationError("highlighter term must contain 1 through 200 characters")
        if not self.normalized_term or len(self.normalized_term) > 400:
            raise ReaderValidationError("normalized highlighter term is invalid")
        if len(self.color) != 7 or not self.color.startswith("#"):
            raise ReaderValidationError("highlighter color must use #RRGGBB")
        try:
            int(self.color[1:], 16)
        except ValueError as exc:
            raise ReaderValidationError("highlighter color must use #RRGGBB") from exc
        if self.ordinal < 0:
            raise ReaderValidationError("highlighter term ordinal must not be negative")


@dataclass(frozen=True, slots=True)
class HighlighterConfiguration:
    terms: tuple[HighlighterTerm, ...]
    row_version: int
    updated_at: datetime
    id: str = "global"

    def __post_init__(self) -> None:
        if self.id != "global":
            raise ReaderValidationError("highlighter configuration id must be global")
        _require_utc(self.updated_at, "highlighter configuration updated_at")
        if self.row_version <= 0:
            raise ReaderValidationError("highlighter configuration version must be positive")
        if len(self.terms) > 200:
            raise ReaderValidationError("highlighter configuration exceeds 200 terms")
        if len({term.normalized_term for term in self.terms}) != len(self.terms):
            raise ReaderValidationError("highlighter terms must be unique")
        if any(term.ordinal != index for index, term in enumerate(self.terms)):
            raise ReaderValidationError("highlighter term order must be contiguous")


class ExportStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExportAudioFormat(str, Enum):
    WAV = "wav"
    MP3 = "mp3"


class ExportPhase(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    SYNTHESIZING = "synthesizing"
    ENCODING = "encoding"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EditOperation(str, Enum):
    REPLACE = "replace"
    APPEND = "append"


class RuleStage(str, Enum):
    CLEANUP = "cleanup"
    PRONUNCIATION = "pronunciation"
    MARKUP = "markup"


class RuleType(str, Enum):
    LITERAL_REPLACE = "literal_replace"
    REGEX_REPLACE = "regex_replace"
    SKIP = "skip"
    SPELL = "spell"
    PAUSE = "pause"
    PHONEME = "phoneme"


class RuleScope(str, Enum):
    SYSTEM = "system"
    GLOBAL = "global"
    LANGUAGE = "language"
    VOICE_ENGINE = "voice_engine"
    DOCUMENT = "document"


@dataclass(frozen=True, slots=True)
class ReaderExportJob:
    id: str
    status: ExportStatus
    document_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    section_ids: tuple[str, ...] = ()
    start_cursor: ReaderCursor | None = None
    end_cursor: ReaderCursor | None = None
    voice_id: str | None = None
    audio_format: ExportAudioFormat = ExportAudioFormat.WAV
    progress_phase: ExportPhase = ExportPhase.QUEUED
    progress_percent: int = 0
    output_basename: str | None = None
    overwrite_existing: bool = False
    total_documents: int = 1
    completed_documents: int = 0
    current_document_id: str | None = None
    output_files: tuple[str, ...] = ()
    error_type: str | None = None
    error_message: str | None = None
    cancel_requested: bool = False
    completed_at: datetime | None = None
    row_version: int = 1

    def __post_init__(self) -> None:
        _require_id(self.id, "export job id")
        _require_utc(self.created_at, "export created_at")
        _require_utc(self.updated_at, "export updated_at")
        if self.completed_at is not None:
            _require_utc(self.completed_at, "export completed_at")
        if not self.document_ids or any(not value.strip() for value in self.document_ids):
            raise ReaderValidationError("export job requires document IDs")
        if self.total_documents != len(self.document_ids):
            raise ReaderValidationError("export document total must match document IDs")
        if not 0 <= self.completed_documents <= self.total_documents:
            raise ReaderValidationError("export progress is invalid")
        if not 0 <= self.progress_percent <= 100:
            raise ReaderValidationError("export percentage is invalid")
        if self.row_version <= 0:
            raise ReaderValidationError("export row version must be positive")
        if self.output_basename is not None and len(self.output_basename) > 200:
            raise ReaderValidationError("export output name exceeds its limit")


@dataclass(frozen=True, slots=True)
class ReaderDesktopOpenRequest:
    id: str
    document_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_id(self.id, "desktop open request id")
        _require_id(self.document_id, "document id")
        _require_utc(self.created_at, "desktop open request created_at")


@dataclass(frozen=True, slots=True)
class ReaderDocument:
    id: str
    title: str
    source_type: SourceType
    state: DocumentState
    created_at: datetime
    updated_at: datetime
    imported_at: datetime
    source_name: str | None = None
    source_uri: str | None = None
    source_sha256: str | None = None
    language_hint: str | None = None
    deleted_at: datetime | None = None
    content_revision: int = 1
    row_version: int = 1
    total_sections: int = 0
    total_blocks: int = 0
    total_characters: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id(self.id, "document id")
        _require_utc(self.created_at, "document created_at")
        _require_utc(self.updated_at, "document updated_at")
        _require_utc(self.imported_at, "document imported_at")
        if self.deleted_at is not None:
            _require_utc(self.deleted_at, "document deleted_at")
        if not self.title.strip():
            raise ReaderValidationError("document title must not be empty")
        if self.content_revision <= 0 or self.row_version <= 0:
            raise ReaderValidationError("document revisions must be positive")
        if min(self.total_sections, self.total_blocks, self.total_characters) < 0:
            raise ReaderValidationError("document totals must not be negative")


@dataclass(frozen=True, slots=True)
class ReaderSection:
    id: str
    document_id: str
    ordinal: int
    level: int
    first_block_ordinal: int
    parent_section_id: str | None = None
    heading: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id(self.id, "section id")
        _require_id(self.document_id, "document id")
        if self.parent_section_id is not None:
            _require_id(self.parent_section_id, "parent section id")
        if self.ordinal < 0 or self.first_block_ordinal < 0:
            raise ReaderValidationError("section ordinals must not be negative")
        if self.level <= 0:
            raise ReaderValidationError("section level must be positive")


@dataclass(frozen=True, slots=True)
class ReaderBlock:
    id: str
    document_id: str
    section_id: str | None
    ordinal: int
    kind: BlockKind
    text: str
    character_count: int
    content_sha256: str
    row_version: int = 1
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id(self.id, "block id")
        _require_id(self.document_id, "document id")
        if self.section_id is not None:
            _require_id(self.section_id, "section id")
        if self.ordinal < 0:
            raise ReaderValidationError("block ordinal must not be negative")
        if self.character_count != len(self.text):
            raise ReaderValidationError("block character_count must match text length")
        if self.row_version <= 0:
            raise ReaderValidationError("block row_version must be positive")


@dataclass(frozen=True, slots=True)
class ReaderCursor:
    document_id: str
    block_id: str
    block_ordinal: int
    character_offset: int
    content_revision: int
    segment_index: int | None = None

    def __post_init__(self) -> None:
        _require_id(self.document_id, "document id")
        _require_id(self.block_id, "block id")
        if self.block_ordinal < 0 or self.character_offset < 0:
            raise ReaderValidationError("cursor offsets must not be negative")
        if self.content_revision <= 0:
            raise ReaderValidationError("cursor content_revision must be positive")


@dataclass(frozen=True, slots=True)
class PlaybackPosition:
    document_id: str
    cursor: ReaderCursor
    updated_at: datetime
    voice_profile_id: str | None = None
    pipeline_version: int = 1
    rules_version: int = 1
    completed: bool = False
    row_version: int = 1

    def __post_init__(self) -> None:
        _require_id(self.document_id, "document id")
        _require_utc(self.updated_at, "position updated_at")
        if self.cursor.document_id != self.document_id:
            raise ReaderValidationError("position cursor must belong to its document")
        if min(self.pipeline_version, self.rules_version, self.row_version) <= 0:
            raise ReaderValidationError("position versions must be positive")


@dataclass(frozen=True, slots=True)
class Bookmark:
    id: str
    document_id: str
    cursor: ReaderCursor
    created_at: datetime
    updated_at: datetime
    label: str = ""
    note: str = ""
    row_version: int = 1

    def __post_init__(self) -> None:
        _require_id(self.id, "bookmark id")
        _require_id(self.document_id, "document id")
        _require_utc(self.created_at, "bookmark created_at")
        _require_utc(self.updated_at, "bookmark updated_at")
        if self.cursor.document_id != self.document_id:
            raise ReaderValidationError("bookmark cursor must belong to its document")
        if self.row_version <= 0:
            raise ReaderValidationError("bookmark row_version must be positive")


@dataclass(frozen=True, slots=True)
class QueueItem:
    id: str
    document_id: str
    ordinal: int
    status: QueueStatus
    added_at: datetime
    updated_at: datetime
    row_version: int = 1

    def __post_init__(self) -> None:
        _require_id(self.id, "queue item id")
        _require_id(self.document_id, "document id")
        _require_utc(self.added_at, "queue added_at")
        _require_utc(self.updated_at, "queue updated_at")
        if self.ordinal < 0:
            raise ReaderValidationError("queue ordinal must not be negative")
        if self.row_version <= 0:
            raise ReaderValidationError("queue row_version must be positive")


@dataclass(frozen=True, slots=True)
class SpeechRuleSet:
    id: str
    name: str
    scope: RuleScope
    created_at: datetime
    updated_at: datetime
    description: str = ""
    enabled: bool = True
    source_sha256: str | None = None
    version: int = 1
    row_version: int = 1
    raw_import_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id(self.id, "rule-set id")
        _require_utc(self.created_at, "rule-set created_at")
        _require_utc(self.updated_at, "rule-set updated_at")
        if not self.name.strip():
            raise ReaderValidationError("rule-set name must not be empty")
        if len(self.name) > 200 or len(self.description) > 2000:
            raise ReaderValidationError("rule-set text exceeds its limit")
        if min(self.version, self.row_version) <= 0:
            raise ReaderValidationError("rule-set versions must be positive")


@dataclass(frozen=True, slots=True)
class SpeechRule:
    id: str
    rule_set_id: str
    name: str
    stage: RuleStage
    rule_type: RuleType
    pattern: str
    replacement: str
    created_at: datetime
    updated_at: datetime
    enabled: bool = True
    case_sensitive: bool = False
    whole_word: bool = False
    language_filter: str | None = None
    engine_filter: str | None = None
    voice_filter: str | None = None
    document_filter: str | None = None
    priority: int = 100
    regex_timeout_ms: int = 25
    row_version: int = 1
    raw_import_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id(self.id, "rule id")
        _require_id(self.rule_set_id, "rule-set id")
        _require_utc(self.created_at, "rule created_at")
        _require_utc(self.updated_at, "rule updated_at")
        if not self.name.strip() or not self.pattern:
            raise ReaderValidationError("rule name and pattern must not be empty")
        if len(self.name) > 200:
            raise ReaderValidationError("rule name exceeds its limit")
        if not 1 <= self.regex_timeout_ms <= 1_000 or self.row_version <= 0:
            raise ReaderValidationError(
                "rule timeout must be from 1 through 1000 ms and row version must be positive"
            )
        if not -100_000 <= self.priority <= 100_000:
            raise ReaderValidationError("rule priority is outside the supported range")
        if len(self.pattern) > 2_048 or len(self.replacement) > 4_096:
            raise ReaderValidationError("rule pattern or replacement exceeds its limit")
        if any(
            value is not None and len(value) > 200
            for value in (
                self.language_filter,
                self.engine_filter,
                self.voice_filter,
                self.document_filter,
            )
        ):
            raise ReaderValidationError("rule filter exceeds its limit")


@dataclass(frozen=True, slots=True)
class DocumentEdit:
    id: str
    document_id: str
    sequence: int
    base_content_revision: int
    result_content_revision: int
    block_id: str
    start_offset: int
    end_offset: int
    original_text: str
    replacement_text: str
    operation_type: EditOperation
    created_at: datetime
    applied: bool = True
    undone_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id(self.id, "edit id")
        _require_id(self.document_id, "document id")
        _require_id(self.block_id, "block id")
        _require_utc(self.created_at, "edit created_at")
        if self.undone_at is not None:
            _require_utc(self.undone_at, "edit undone_at")
        if self.sequence <= 0:
            raise ReaderValidationError("edit sequence must be positive")
        if min(self.base_content_revision, self.result_content_revision) <= 0:
            raise ReaderValidationError("edit revisions must be positive")
        if self.result_content_revision <= self.base_content_revision:
            raise ReaderValidationError("edit result revision must follow base revision")
        if min(self.start_offset, self.end_offset) < 0 or self.end_offset < self.start_offset:
            raise ReaderValidationError("edit offsets are invalid")


@dataclass(frozen=True, slots=True)
class ReaderDocumentBundle:
    document: ReaderDocument
    sections: tuple[ReaderSection, ...]
    blocks: tuple[ReaderBlock, ...]


@dataclass(frozen=True, slots=True)
class DocumentPage:
    items: tuple[ReaderDocument, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ReaderDatabaseReport:
    ready: bool
    schema_version: int
    integrity_ok: bool
    integrity_message: str
    journal_mode: str
    database_path: str


def _require_id(value: str, label: str) -> None:
    if not value.strip():
        raise ReaderValidationError(f"{label} must not be empty")
    try:
        UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ReaderValidationError(f"{label} must be a UUID string") from exc


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ReaderValidationError(f"{label} must be a UTC timestamp")
