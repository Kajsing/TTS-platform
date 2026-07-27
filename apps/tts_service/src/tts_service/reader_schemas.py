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
    PlaybackPosition,
    QueueItem,
    QueueStatus,
    ReaderBlock,
    ReaderCursor,
    ReaderDocument,
    SourceType,
)


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
    def from_domain(cls, cursor: ReaderCursor) -> "ReaderCursorResponse":
        return cls(
            document_id=cursor.document_id,
            block_id=cursor.block_id,
            block_ordinal=cursor.block_ordinal,
            character_offset=cursor.character_offset,
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
    def from_domain(cls, edit: DocumentEdit) -> "ReaderEditResponse":
        return cls(
            id=edit.id,
            document_id=edit.document_id,
            sequence=edit.sequence,
            base_content_revision=edit.base_content_revision,
            result_content_revision=edit.result_content_revision,
            block_id=edit.block_id,
            start_offset=edit.start_offset,
            end_offset=edit.end_offset,
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
    def from_domain(cls, position: PlaybackPosition) -> "ReaderPositionResponse":
        return cls(
            document_id=position.document_id,
            cursor=ReaderCursorResponse.from_domain(position.cursor),
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
    def from_domain(cls, bookmark: Bookmark) -> "ReaderBookmarkResponse":
        return cls(
            id=bookmark.id,
            document_id=bookmark.document_id,
            cursor=ReaderCursorResponse.from_domain(bookmark.cursor),
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
