from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from reader_core import (
    BlockKind,
    Bookmark,
    DocumentEdit,
    DocumentState,
    EditOperation,
    ExportStatus,
    PlaybackPosition,
    QueueItem,
    QueueStatus,
    ReaderBlock,
    ReaderCursor,
    ReaderDocument,
    ReaderExportJob,
    RuleScope,
    RuleStage,
    RuleType,
    SourceType,
    SpeechRule,
    SpeechRuleSet,
)

from .reader_offsets import python_offset_to_utf16


class ReaderCursorPayload(BaseModel):
    block_id: str
    block_ordinal: int = Field(ge=0)
    character_offset: int = Field(ge=0)
    content_revision: int = Field(gt=0)
    segment_index: int | None = Field(default=None, ge=0)

    def to_domain(self, document_id: str) -> ReaderCursor:
        return ReaderCursor(
            document_id=document_id,
            block_id=self.block_id,
            block_ordinal=self.block_ordinal,
            character_offset=self.character_offset,
            content_revision=self.content_revision,
            segment_index=self.segment_index,
        )


class ReaderCursorResponse(ReaderCursorPayload):
    document_id: str

    @classmethod
    def from_domain(
        cls,
        cursor: ReaderCursor,
        *,
        source_text: str | None = None,
    ) -> "ReaderCursorResponse":
        character_offset = cursor.character_offset
        if source_text is not None:
            character_offset = python_offset_to_utf16(
                source_text,
                cursor.character_offset,
            )
        return cls(
            document_id=cursor.document_id,
            block_id=cursor.block_id,
            block_ordinal=cursor.block_ordinal,
            character_offset=character_offset,
            content_revision=cursor.content_revision,
            segment_index=cursor.segment_index,
        )


class ReaderDocumentResponse(BaseModel):
    id: str
    title: str
    source_type: SourceType
    source_name: str | None
    source_uri: str | None
    source_sha256: str | None
    language_hint: str | None
    state: DocumentState
    created_at: datetime
    updated_at: datetime
    imported_at: datetime
    deleted_at: datetime | None
    content_revision: int
    row_version: int
    total_sections: int
    total_blocks: int
    total_characters: int
    metadata: dict[str, Any]

    @classmethod
    def from_domain(cls, document: ReaderDocument) -> "ReaderDocumentResponse":
        return cls(
            id=document.id,
            title=document.title,
            source_type=document.source_type,
            source_name=document.source_name,
            source_uri=document.source_uri,
            source_sha256=document.source_sha256,
            language_hint=document.language_hint,
            state=document.state,
            created_at=document.created_at,
            updated_at=document.updated_at,
            imported_at=document.imported_at,
            deleted_at=document.deleted_at,
            content_revision=document.content_revision,
            row_version=document.row_version,
            total_sections=document.total_sections,
            total_blocks=document.total_blocks,
            total_characters=document.total_characters,
            metadata=dict(document.metadata),
        )


class ReaderDocumentPageResponse(BaseModel):
    documents: list[ReaderDocumentResponse]
    next_cursor: str | None


class CreateReaderDocumentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    source_type: SourceType = SourceType.PLAIN_TEXT
    text: str = Field(min_length=1, max_length=10_000_000)
    language_hint: str | None = Field(default=None, max_length=64)
    allow_duplicate: bool = False


class UpdateReaderDocumentRequest(BaseModel):
    expected_row_version: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    state: DocumentState | None = None


class ExpectedReaderVersionRequest(BaseModel):
    expected_row_version: int = Field(gt=0)


class ReplaceReaderContentRequest(ExpectedReaderVersionRequest):
    block_id: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    replacement_text: str = Field(max_length=10_000_000)


class AppendReaderContentRequest(ExpectedReaderVersionRequest):
    text: str = Field(min_length=1, max_length=10_000_000)


class ReaderBlockResponse(BaseModel):
    id: str
    document_id: str
    section_id: str | None
    ordinal: int
    kind: BlockKind
    text: str
    character_count: int
    content_sha256: str
    row_version: int
    metadata: dict[str, Any]

    @classmethod
    def from_domain(cls, block: ReaderBlock) -> "ReaderBlockResponse":
        return cls(
            id=block.id,
            document_id=block.document_id,
            section_id=block.section_id,
            ordinal=block.ordinal,
            kind=block.kind,
            text=block.text,
            character_count=block.character_count,
            content_sha256=block.content_sha256,
            row_version=block.row_version,
            metadata=dict(block.metadata),
        )


class ReaderBlockPageResponse(BaseModel):
    blocks: list[ReaderBlockResponse]
    next_after_ordinal: int | None


class ReaderImportWarningResponse(BaseModel):
    code: str
    message: str
    count: int


class ReaderImportSectionPreviewResponse(BaseModel):
    ordinal: int
    level: int
    heading: str | None
    first_block_ordinal: int


class ReaderImportBlockPreviewResponse(BaseModel):
    ordinal: int
    kind: str
    text: str
    section_ordinal: int


class ReaderImportPreviewResponse(BaseModel):
    preview_id: str
    title: str
    source_type: SourceType
    source_name: str
    total_sections: int
    total_blocks: int
    total_characters: int
    warnings: list[ReaderImportWarningResponse]
    sections: list[ReaderImportSectionPreviewResponse]
    sample_blocks: list[ReaderImportBlockPreviewResponse]
    preview_truncated: bool
    duplicate_document_id: str | None
    expires_in_seconds: int = 600


class ReaderImportCommitRequest(BaseModel):
    allow_duplicate: bool = False


class ReaderEditResponse(BaseModel):
    id: str
    document_id: str
    sequence: int
    base_content_revision: int
    result_content_revision: int
    block_id: str
    start_offset: int
    end_offset: int
    operation_type: EditOperation
    created_at: datetime

    @classmethod
    def from_domain(
        cls,
        edit: DocumentEdit,
        *,
        source_text: str | None = None,
    ) -> "ReaderEditResponse":
        start_offset = edit.start_offset
        end_offset = edit.end_offset
        if source_text is not None:
            start_offset = python_offset_to_utf16(source_text, edit.start_offset)
            end_offset = python_offset_to_utf16(source_text, edit.end_offset)
        return cls(
            id=edit.id,
            document_id=edit.document_id,
            sequence=edit.sequence,
            base_content_revision=edit.base_content_revision,
            result_content_revision=edit.result_content_revision,
            block_id=edit.block_id,
            start_offset=start_offset,
            end_offset=end_offset,
            operation_type=edit.operation_type,
            created_at=edit.created_at,
        )


class ReaderMutationResponse(BaseModel):
    document: ReaderDocumentResponse
    edit: ReaderEditResponse | None = None


class SaveReaderPositionRequest(BaseModel):
    cursor: ReaderCursorPayload
    voice_profile_id: str | None = None
    pipeline_version: int = Field(default=1, gt=0)
    rules_version: int = Field(default=1, gt=0)
    completed: bool = False
    expected_row_version: int | None = Field(default=None, ge=0)


class ReaderPositionResponse(BaseModel):
    document_id: str
    cursor: ReaderCursorResponse
    voice_profile_id: str | None
    pipeline_version: int
    rules_version: int
    updated_at: datetime
    completed: bool
    row_version: int

    @classmethod
    def from_domain(
        cls,
        position: PlaybackPosition,
        *,
        source_text: str | None = None,
    ) -> "ReaderPositionResponse":
        return cls(
            document_id=position.document_id,
            cursor=ReaderCursorResponse.from_domain(
                position.cursor,
                source_text=source_text,
            ),
            voice_profile_id=position.voice_profile_id,
            pipeline_version=position.pipeline_version,
            rules_version=position.rules_version,
            updated_at=position.updated_at,
            completed=position.completed,
            row_version=position.row_version,
        )


class ReaderPositionEnvelope(BaseModel):
    position: ReaderPositionResponse | None


class CreateReaderBookmarkRequest(BaseModel):
    cursor: ReaderCursorPayload
    label: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=10_000)


class UpdateReaderBookmarkRequest(ExpectedReaderVersionRequest):
    cursor: ReaderCursorPayload | None = None
    label: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=10_000)


class ReaderBookmarkResponse(BaseModel):
    id: str
    document_id: str
    cursor: ReaderCursorResponse
    label: str
    note: str
    created_at: datetime
    updated_at: datetime
    row_version: int

    @classmethod
    def from_domain(
        cls,
        bookmark: Bookmark,
        *,
        source_text: str | None = None,
    ) -> "ReaderBookmarkResponse":
        return cls(
            id=bookmark.id,
            document_id=bookmark.document_id,
            cursor=ReaderCursorResponse.from_domain(
                bookmark.cursor,
                source_text=source_text,
            ),
            label=bookmark.label,
            note=bookmark.note,
            created_at=bookmark.created_at,
            updated_at=bookmark.updated_at,
            row_version=bookmark.row_version,
        )


class ReaderBookmarkListResponse(BaseModel):
    bookmarks: list[ReaderBookmarkResponse]


class AddReaderQueueItemRequest(BaseModel):
    document_id: str
    status: QueueStatus = QueueStatus.QUEUED


class UpdateReaderQueueItemRequest(ExpectedReaderVersionRequest):
    status: QueueStatus


class ReorderReaderQueueRequest(BaseModel):
    item_ids: list[str]


class ReaderQueueItemResponse(BaseModel):
    id: str
    document_id: str
    ordinal: int
    status: QueueStatus
    added_at: datetime
    updated_at: datetime
    row_version: int

    @classmethod
    def from_domain(cls, item: QueueItem) -> "ReaderQueueItemResponse":
        return cls(
            id=item.id,
            document_id=item.document_id,
            ordinal=item.ordinal,
            status=item.status,
            added_at=item.added_at,
            updated_at=item.updated_at,
            row_version=item.row_version,
        )


class ReaderQueueResponse(BaseModel):
    items: list[ReaderQueueItemResponse]


class CreateReaderExportRequest(BaseModel):
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    queue_item_ids: list[str] = Field(default_factory=list, max_length=100)
    section_ids: list[str] = Field(default_factory=list, max_length=10_000)
    start_cursor: ReaderCursorPayload | None = None
    end_cursor: ReaderCursorPayload | None = None
    voice_id: str | None = Field(default=None, max_length=200)
    output_basename: str | None = Field(default=None, max_length=200)
    overwrite_existing: bool = False


class ReaderExportJobResponse(BaseModel):
    id: str
    status: ExportStatus
    document_ids: list[str]
    section_ids: list[str]
    voice_id: str | None
    output_basename: str | None
    overwrite_existing: bool
    total_documents: int
    completed_documents: int
    current_document_id: str | None
    output_files: list[str]
    error_type: str | None
    error_message: str | None
    cancel_requested: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    row_version: int

    @classmethod
    def from_domain(cls, job: ReaderExportJob) -> "ReaderExportJobResponse":
        return cls(
            id=job.id,
            status=job.status,
            document_ids=list(job.document_ids),
            section_ids=list(job.section_ids),
            voice_id=job.voice_id,
            output_basename=job.output_basename,
            overwrite_existing=job.overwrite_existing,
            total_documents=job.total_documents,
            completed_documents=job.completed_documents,
            current_document_id=job.current_document_id,
            output_files=list(job.output_files),
            error_type=job.error_type,
            error_message=job.error_message,
            cancel_requested=job.cancel_requested,
            created_at=job.created_at,
            updated_at=job.updated_at,
            completed_at=job.completed_at,
            row_version=job.row_version,
        )


class ReaderExportJobListResponse(BaseModel):
    jobs: list[ReaderExportJobResponse]


class ReaderDiagnosticsResponse(BaseModel):
    database_ready: bool
    schema_version: int
    integrity_message: str
    search_available: bool
    document_counts_by_state: dict[str, int]
    queue_item_count: int
    active_content_leases: int
    export_status_counts: dict[str, int]
    metrics: dict[str, Any]


class CreateReaderRuleSetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    scope: RuleScope = RuleScope.GLOBAL


class UpdateReaderRuleSetRequest(BaseModel):
    expected_row_version: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    scope: RuleScope | None = None


class ReaderRuleSetResponse(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool
    scope: RuleScope
    source_sha256: str | None
    version: int
    row_version: int
    created_at: datetime
    updated_at: datetime
    raw_import_metadata: dict[str, Any]

    @classmethod
    def from_domain(cls, rule_set: SpeechRuleSet) -> "ReaderRuleSetResponse":
        return cls(
            id=rule_set.id,
            name=rule_set.name,
            description=rule_set.description,
            enabled=rule_set.enabled,
            scope=rule_set.scope,
            source_sha256=rule_set.source_sha256,
            version=rule_set.version,
            row_version=rule_set.row_version,
            created_at=rule_set.created_at,
            updated_at=rule_set.updated_at,
            raw_import_metadata=dict(rule_set.raw_import_metadata),
        )


class ReaderRuleSetListResponse(BaseModel):
    rule_sets: list[ReaderRuleSetResponse]
    rules_version: int


class ReaderRuleFields(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    stage: RuleStage = RuleStage.PRONUNCIATION
    rule_type: RuleType = RuleType.LITERAL_REPLACE
    pattern: str = Field(min_length=1, max_length=2048)
    replacement: str = Field(default="", max_length=4096)
    case_sensitive: bool = False
    whole_word: bool = False
    language_filter: str | None = Field(default=None, max_length=200)
    engine_filter: str | None = Field(default=None, max_length=200)
    voice_filter: str | None = Field(default=None, max_length=200)
    document_filter: str | None = Field(default=None, max_length=200)
    priority: int = Field(default=100, ge=-100_000, le=100_000)
    regex_timeout_ms: int | None = Field(default=None, gt=0, le=1000)


class CreateReaderRuleRequest(ReaderRuleFields):
    pass


class UpdateReaderRuleRequest(BaseModel):
    expected_row_version: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    stage: RuleStage | None = None
    rule_type: RuleType | None = None
    pattern: str | None = Field(default=None, min_length=1, max_length=2048)
    replacement: str | None = Field(default=None, max_length=4096)
    case_sensitive: bool | None = None
    whole_word: bool | None = None
    language_filter: str | None = Field(default=None, max_length=200)
    engine_filter: str | None = Field(default=None, max_length=200)
    voice_filter: str | None = Field(default=None, max_length=200)
    document_filter: str | None = Field(default=None, max_length=200)
    priority: int | None = Field(default=None, ge=-100_000, le=100_000)
    regex_timeout_ms: int | None = Field(default=None, gt=0, le=1000)


class ReaderRuleResponse(BaseModel):
    id: str
    rule_set_id: str
    name: str
    enabled: bool
    stage: RuleStage
    rule_type: RuleType
    pattern: str
    replacement: str
    case_sensitive: bool
    whole_word: bool
    language_filter: str | None
    engine_filter: str | None
    voice_filter: str | None
    document_filter: str | None
    priority: int
    regex_timeout_ms: int
    row_version: int
    created_at: datetime
    updated_at: datetime
    raw_import_metadata: dict[str, Any]

    @classmethod
    def from_domain(cls, rule: SpeechRule) -> "ReaderRuleResponse":
        return cls(
            id=rule.id,
            rule_set_id=rule.rule_set_id,
            name=rule.name,
            enabled=rule.enabled,
            stage=rule.stage,
            rule_type=rule.rule_type,
            pattern=rule.pattern,
            replacement=rule.replacement,
            case_sensitive=rule.case_sensitive,
            whole_word=rule.whole_word,
            language_filter=rule.language_filter,
            engine_filter=rule.engine_filter,
            voice_filter=rule.voice_filter,
            document_filter=rule.document_filter,
            priority=rule.priority,
            regex_timeout_ms=rule.regex_timeout_ms,
            row_version=rule.row_version,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
            raw_import_metadata=dict(rule.raw_import_metadata),
        )


class ReaderRuleListResponse(BaseModel):
    rules: list[ReaderRuleResponse]


class ReaderRulePreviewRequest(BaseModel):
    # Preview returns one source span per spoken character. Keep this interactive
    # path smaller than a streaming compilation window so the UI cannot be
    # stalled by an oversized mapping response.
    text: str = Field(max_length=4_096)
    rule_set_ids: list[str] = Field(default_factory=list, max_length=100)
    language: str | None = Field(default=None, max_length=200)
    engine: str | None = Field(default=None, max_length=200)
    voice: str | None = Field(default=None, max_length=200)
    document_id: str | None = Field(default=None, max_length=200)


class ReaderRulePreviewSpan(BaseModel):
    start_offset: int
    end_offset: int


class ReaderRuleTraceResponse(BaseModel):
    rule_id: str
    rule_type: RuleType
    start_offset: int
    end_offset: int
    replacement_length: int


class ReaderRuleWarningResponse(BaseModel):
    code: str
    message: str
    rule_id: str | None


class ReaderRulePreviewResponse(BaseModel):
    original_text: str
    spoken_text: str
    source_spans: list[ReaderRulePreviewSpan]
    trace: list[ReaderRuleTraceResponse]
    warnings: list[ReaderRuleWarningResponse]
    elapsed_ms: float
    pipeline_version: int
    rules_version: int


class ReaderRuleImportRequest(BaseModel):
    target_rule_set_id: str
    content: str = Field(min_length=1, max_length=1_048_576)
    commit: bool = False


class ReaderRuleImportReportResponse(BaseModel):
    source_sha256: str
    imported: int
    disabled: int
    duplicate: int
    invalid: int
    unsupported: int
    committed: bool
    idempotent: bool


class ReaderDatabaseCapability(BaseModel):
    ready: bool
    schema_version: int
    search_available: bool


class ReaderImportCapability(BaseModel):
    formats: list[str]
    max_file_bytes: int
    ocr_available: bool


class ReaderRuleCapability(BaseModel):
    types: list[str]
    regex_timeout_supported: bool


class ReaderPlaybackCapability(BaseModel):
    stream_protocol_version: int
    source_offset_encoding: str
    max_blocks_per_window: int
    max_source_chars_per_window: int


class ReaderExportCapability(BaseModel):
    formats: list[str]


class ReaderCapabilitiesResponse(BaseModel):
    contract_version: int
    enabled: bool
    database: ReaderDatabaseCapability
    imports: ReaderImportCapability
    rules: ReaderRuleCapability
    playback: ReaderPlaybackCapability
    exports: ReaderExportCapability


class ReaderErrorBody(BaseModel):
    type: str
    message: str
    param: str | None
    request_id: str
    details: dict[str, Any]


class ReaderErrorResponse(BaseModel):
    error: ReaderErrorBody
