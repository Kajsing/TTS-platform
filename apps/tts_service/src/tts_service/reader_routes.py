from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from functools import partial
from threading import Event
from typing import Annotated, TypeVar

from document_import import DocumentImportError, ImportOptions, ImportSource
from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status
from reader_core import (
    Bookmark,
    DocumentState,
    PlaybackPosition,
    QueueItem,
    ReaderCursor,
    ReaderError,
    ReaderStaleCursorError,
    ReaderValidationError,
    SpeechRule,
)
from speech_rules import RuleContext, SpeechRuleError
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

from .reader_errors import (
    reader_api_error,
    reader_database_unavailable,
    reader_disabled,
    translate_import_error,
    translate_reader_error,
    translate_rule_error,
)
from .reader_offsets import ReaderOffsetError, utf16_offset_to_python
from .reader_schemas import (
    AddReaderQueueItemRequest,
    AppendReaderContentRequest,
    CreateReaderBookmarkRequest,
    CreateReaderDocumentRequest,
    CreateReaderExportRequest,
    CreateReaderRuleRequest,
    CreateReaderRuleSetRequest,
    ExpectedReaderVersionRequest,
    ReaderBlockPageResponse,
    ReaderBlockResponse,
    ReaderBookmarkListResponse,
    ReaderBookmarkResponse,
    ReaderCapabilitiesResponse,
    ReaderCursorPayload,
    ReaderDatabaseCapability,
    ReaderDiagnosticsResponse,
    ReaderDocumentPageResponse,
    ReaderDocumentResponse,
    ReaderEditResponse,
    ReaderExportCapability,
    ReaderExportJobListResponse,
    ReaderExportJobResponse,
    ReaderImportBlockPreviewResponse,
    ReaderImportCapability,
    ReaderImportCommitRequest,
    ReaderImportPreviewResponse,
    ReaderImportSectionPreviewResponse,
    ReaderImportWarningResponse,
    ReaderMutationResponse,
    ReaderPlaybackCapability,
    ReaderPositionEnvelope,
    ReaderPositionResponse,
    ReaderQueueItemResponse,
    ReaderQueueResponse,
    ReaderRuleCapability,
    ReaderRuleImportReportResponse,
    ReaderRuleImportRequest,
    ReaderRuleListResponse,
    ReaderRulePreviewRequest,
    ReaderRulePreviewResponse,
    ReaderRulePreviewSpan,
    ReaderRuleResponse,
    ReaderRuleSetListResponse,
    ReaderRuleSetResponse,
    ReaderRuleTraceResponse,
    ReaderRuleWarningResponse,
    ReorderReaderQueueRequest,
    ReplaceReaderContentRequest,
    SaveReaderPositionRequest,
    UpdateReaderBookmarkRequest,
    UpdateReaderDocumentRequest,
    UpdateReaderQueueItemRequest,
    UpdateReaderRuleRequest,
    UpdateReaderRuleSetRequest,
)
from .reader_service import (
    ReaderApplicationService,
    ReaderImportPreview,
    ReaderImportPreviewCapacityError,
    ReaderImportPreviewNotFoundError,
)

T = TypeVar("T")


def build_reader_router() -> APIRouter:
    router = APIRouter(prefix="/v1/reader", tags=["reader"])

    @router.get("/capabilities", response_model=ReaderCapabilitiesResponse)
    async def capabilities(request: Request) -> ReaderCapabilitiesResponse:
        runtime = request.app.state.container.reader
        config = request.app.state.container.config.reader
        return ReaderCapabilitiesResponse(
            contract_version=1,
            enabled=runtime.enabled,
            database=ReaderDatabaseCapability(
                ready=runtime.database_ready,
                schema_version=runtime.schema_version,
                search_available=(
                    runtime.service.repository.search_available
                    if runtime.service is not None
                    else False
                ),
            ),
            imports=ReaderImportCapability(
                formats=["txt", "md", "html", "docx", "epub"],
                max_file_bytes=config.imports.max_file_bytes,
                ocr_available=False,
            ),
            rules=ReaderRuleCapability(
                types=[
                    "literal_replace",
                    "regex_replace",
                    "skip",
                    "spell",
                    "pause",
                    "phoneme",
                ],
                regex_timeout_supported=True,
            ),
            playback=ReaderPlaybackCapability(
                stream_protocol_version=1,
                source_offset_encoding="utf-16",
                max_blocks_per_window=config.max_blocks_per_stream_window,
                max_source_chars_per_window=config.max_source_chars_per_stream_window,
            ),
            exports=ReaderExportCapability(
                formats=list(config.exports.formats) if config.exports.enabled else []
            ),
        )

    @router.post("/imports/preview", response_model=ReaderImportPreviewResponse)
    async def preview_import(
        request: Request,
        file: Annotated[UploadFile, File()],
        title: Annotated[str | None, Form(max_length=500)] = None,
        language_hint: Annotated[str | None, Form(max_length=64)] = None,
        copy_source_file: Annotated[bool | None, Form()] = None,
    ) -> ReaderImportPreviewResponse:
        service = _service(request)
        source = await _read_import_source(file, service.config.imports.max_file_bytes)
        preview = await _run_import_async(
            lambda cancellation: service.create_import_preview(
                source=source,
                options=ImportOptions(title=title, language_hint=language_hint),
                copy_source_file=copy_source_file,
                cancellation=cancellation,
            )
        )
        return _import_preview_response(preview)

    @router.post(
        "/imports/{preview_id}/commit",
        response_model=ReaderDocumentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def commit_import(
        request: Request,
        preview_id: str,
        payload: ReaderImportCommitRequest,
    ) -> ReaderDocumentResponse:
        service = _service(request)
        document = await _run_import_async(
            lambda _: service.commit_import_preview(
                preview_id,
                allow_duplicate=payload.allow_duplicate,
            )
        )
        return ReaderDocumentResponse.from_domain(document)

    @router.delete(
        "/imports/{preview_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def cancel_import(request: Request, preview_id: str) -> Response:
        service = _service(request)
        await _run_import_async(lambda _: service.cancel_import_preview(preview_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/imports",
        response_model=ReaderDocumentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def import_file(
        request: Request,
        file: Annotated[UploadFile, File()],
        title: Annotated[str | None, Form(max_length=500)] = None,
        language_hint: Annotated[str | None, Form(max_length=64)] = None,
        copy_source_file: Annotated[bool | None, Form()] = None,
        allow_duplicate: Annotated[bool, Form()] = False,
    ) -> ReaderDocumentResponse:
        service = _service(request)
        source = await _read_import_source(file, service.config.imports.max_file_bytes)
        document = await _run_import_async(
            lambda cancellation: service.import_source(
                source=source,
                options=ImportOptions(title=title, language_hint=language_hint),
                copy_source_file=copy_source_file,
                allow_duplicate=allow_duplicate,
                cancellation=cancellation,
            )
        )
        return ReaderDocumentResponse.from_domain(document)

    @router.get("/documents", response_model=ReaderDocumentPageResponse)
    async def list_documents(
        request: Request,
        state_filter: Annotated[DocumentState | None, Query(alias="state")] = None,
        query: Annotated[str | None, Query(max_length=500)] = None,
        limit: Annotated[int, Query(gt=0)] = 50,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> ReaderDocumentPageResponse:
        service = _service(request)
        if limit > service.config.max_page_size:
            raise reader_api_error(
                "reader_conflict",
                status_code=400,
                message="Reader page limit exceeds the configured maximum.",
                param="limit",
                details={"max_page_size": service.config.max_page_size},
            )
        page = _run_reader(
            lambda: service.list_documents(
                state=state_filter,
                query=query,
                limit=limit,
                cursor=cursor,
            ),
            cursor_input=cursor is not None,
        )
        return ReaderDocumentPageResponse(
            documents=[ReaderDocumentResponse.from_domain(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @router.post(
        "/documents",
        response_model=ReaderDocumentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_document(
        request: Request,
        payload: CreateReaderDocumentRequest,
    ) -> ReaderDocumentResponse:
        service = _service(request)
        document = _run_reader(
            lambda: service.create_text_document(
                title=payload.title,
                text=payload.text,
                source_type=payload.source_type,
                language_hint=payload.language_hint,
                allow_duplicate=payload.allow_duplicate,
            )
        )
        return ReaderDocumentResponse.from_domain(document)

    @router.post(
        "/documents/{document_id}/duplicate-as-editable",
        response_model=ReaderDocumentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def duplicate_as_editable(
        request: Request,
        document_id: str,
    ) -> ReaderDocumentResponse:
        service = _service(request)
        document = _run_reader(lambda: service.duplicate_as_editable_text(document_id))
        return ReaderDocumentResponse.from_domain(document)

    @router.get("/documents/{document_id}", response_model=ReaderDocumentResponse)
    async def get_document(request: Request, document_id: str) -> ReaderDocumentResponse:
        service = _service(request)
        document = _run_reader(lambda: service.get_document(document_id))
        return ReaderDocumentResponse.from_domain(document)

    @router.patch("/documents/{document_id}", response_model=ReaderDocumentResponse)
    async def update_document(
        request: Request,
        document_id: str,
        payload: UpdateReaderDocumentRequest,
    ) -> ReaderDocumentResponse:
        if payload.title is None and payload.state is None:
            raise reader_api_error(
                "reader_conflict",
                status_code=400,
                message="At least one document field must be updated.",
            )
        service = _service(request)
        document = _run_reader(
            lambda: service.repository.update_document(
                document_id,
                expected_row_version=payload.expected_row_version,
                title=payload.title,
                state=payload.state,
            )
        )
        service.log_mutation("update_document", document)
        return ReaderDocumentResponse.from_domain(document)

    @router.delete("/documents/{document_id}", response_model=ReaderDocumentResponse)
    async def delete_document(
        request: Request,
        document_id: str,
        expected_row_version: Annotated[int, Query(gt=0)],
    ) -> ReaderDocumentResponse:
        service = _service(request)
        document = _run_reader(
            lambda: service.repository.soft_delete_document(
                document_id,
                expected_row_version=expected_row_version,
            )
        )
        service.log_mutation("soft_delete_document", document)
        return ReaderDocumentResponse.from_domain(document)

    @router.post("/documents/{document_id}/restore", response_model=ReaderDocumentResponse)
    async def restore_document(
        request: Request,
        document_id: str,
        payload: ExpectedReaderVersionRequest,
    ) -> ReaderDocumentResponse:
        service = _service(request)
        document = _run_reader(
            lambda: service.repository.restore_document(
                document_id,
                expected_row_version=payload.expected_row_version,
            )
        )
        service.log_mutation("restore_document", document)
        return ReaderDocumentResponse.from_domain(document)

    @router.patch("/documents/{document_id}/content", response_model=ReaderMutationResponse)
    async def replace_content(
        request: Request,
        document_id: str,
        payload: ReplaceReaderContentRequest,
    ) -> ReaderMutationResponse:
        service = _service(request)
        bundle = _run_reader(lambda: service.get_document_bundle(document_id))
        source_block = next(
            (block for block in bundle.blocks if block.id == payload.block_id),
            None,
        )
        if source_block is None:
            raise reader_api_error(
                "reader_block_not_found",
                status_code=404,
                message="Reader block was not found.",
            )
        try:
            start_offset = utf16_offset_to_python(source_block.text, payload.start_offset)
            end_offset = utf16_offset_to_python(source_block.text, payload.end_offset)
        except ReaderOffsetError as error:
            raise reader_api_error(
                "reader_invalid_offset",
                status_code=400,
                message="Reader edit offsets must be valid UTF-16 code-unit boundaries.",
                param="start_offset/end_offset",
            ) from error
        document, edit = _run_content_mutation(
            service,
            document_id,
            lambda: service.repository.replace_block_text(
                document_id,
                payload.block_id,
                start_offset=start_offset,
                end_offset=end_offset,
                replacement_text=payload.replacement_text,
                expected_row_version=payload.expected_row_version,
            ),
            missing_entity="block",
        )
        service.log_mutation(
            "replace_content",
            document,
            block_id=payload.block_id,
            character_count=len(payload.replacement_text),
        )
        return ReaderMutationResponse(
            document=ReaderDocumentResponse.from_domain(document),
            edit=ReaderEditResponse.from_domain(edit, source_text=source_block.text),
        )

    @router.post("/documents/{document_id}/append", response_model=ReaderMutationResponse)
    async def append_content(
        request: Request,
        document_id: str,
        payload: AppendReaderContentRequest,
    ) -> ReaderMutationResponse:
        service = _service(request)
        document, edit = _run_content_mutation(
            service,
            document_id,
            lambda: service.repository.append_text(
                document_id,
                payload.text,
                expected_row_version=payload.expected_row_version,
            )
        )
        service.log_mutation(
            "append_content",
            document,
            block_id=edit.block_id,
            character_count=len(payload.text),
        )
        return ReaderMutationResponse(
            document=ReaderDocumentResponse.from_domain(document),
            edit=ReaderEditResponse.from_domain(edit),
        )

    @router.post("/documents/{document_id}/undo", response_model=ReaderMutationResponse)
    async def undo_content(
        request: Request,
        document_id: str,
        payload: ExpectedReaderVersionRequest,
    ) -> ReaderMutationResponse:
        service = _service(request)
        document = _run_content_mutation(
            service,
            document_id,
            lambda: service.repository.undo(
                document_id,
                expected_row_version=payload.expected_row_version,
            )
        )
        service.log_mutation("undo_content", document)
        return ReaderMutationResponse(document=ReaderDocumentResponse.from_domain(document))

    @router.post("/documents/{document_id}/redo", response_model=ReaderMutationResponse)
    async def redo_content(
        request: Request,
        document_id: str,
        payload: ExpectedReaderVersionRequest,
    ) -> ReaderMutationResponse:
        service = _service(request)
        document = _run_content_mutation(
            service,
            document_id,
            lambda: service.repository.redo(
                document_id,
                expected_row_version=payload.expected_row_version,
            )
        )
        service.log_mutation("redo_content", document)
        return ReaderMutationResponse(document=ReaderDocumentResponse.from_domain(document))

    @router.get("/documents/{document_id}/blocks", response_model=ReaderBlockPageResponse)
    async def list_blocks(
        request: Request,
        document_id: str,
        after_ordinal: Annotated[int, Query(ge=-1)] = -1,
        limit: Annotated[int, Query(gt=0)] = 200,
    ) -> ReaderBlockPageResponse:
        service = _service(request)
        if limit > service.config.max_page_size:
            raise reader_api_error(
                "reader_conflict",
                status_code=400,
                message="Reader block page limit exceeds the configured maximum.",
                param="limit",
                details={"max_page_size": service.config.max_page_size},
            )
        fetched = _run_reader(
            lambda: service.list_blocks(
                document_id,
                after_ordinal=after_ordinal,
                limit=limit + 1,
            )
        )
        has_more = len(fetched) > limit
        blocks = fetched[:limit]
        return ReaderBlockPageResponse(
            blocks=[ReaderBlockResponse.from_domain(block) for block in blocks],
            next_after_ordinal=blocks[-1].ordinal if has_more and blocks else None,
        )

    @router.get(
        "/documents/{document_id}/position",
        response_model=ReaderPositionEnvelope,
    )
    async def get_position(request: Request, document_id: str) -> ReaderPositionEnvelope:
        service = _service(request)
        _run_reader(lambda: service.get_document(document_id))
        position = _run_reader(lambda: service.repository.get_position(document_id))
        return ReaderPositionEnvelope(
            position=(
                _run_reader(lambda: _position_response(service, position))
                if position
                else None
            )
        )

    @router.put(
        "/documents/{document_id}/position",
        response_model=ReaderPositionResponse,
    )
    async def save_position(
        request: Request,
        document_id: str,
        payload: SaveReaderPositionRequest,
    ) -> ReaderPositionResponse:
        service = _service(request)
        cursor = _run_reader(
            lambda: _api_cursor_to_domain(service, document_id, payload.cursor),
            cursor_input=True,
        )
        position = _run_reader(
            lambda: service.repository.save_position(
                PlaybackPosition(
                    document_id=document_id,
                    cursor=cursor,
                    voice_profile_id=payload.voice_profile_id,
                    pipeline_version=payload.pipeline_version,
                    rules_version=payload.rules_version,
                    updated_at=datetime.now(timezone.utc),
                    completed=payload.completed,
                ),
                expected_row_version=payload.expected_row_version,
            ),
            cursor_input=True,
        )
        service.observability.log_reader_operation(
            operation="save_position",
            document_id=document_id,
            block_id=position.cursor.block_id,
        )
        return _run_reader(lambda: _position_response(service, position))

    @router.get(
        "/documents/{document_id}/bookmarks",
        response_model=ReaderBookmarkListResponse,
    )
    async def list_bookmarks(
        request: Request,
        document_id: str,
    ) -> ReaderBookmarkListResponse:
        service = _service(request)
        bookmarks = _run_reader(lambda: service.repository.list_bookmarks(document_id))
        return ReaderBookmarkListResponse(
            bookmarks=[
                _run_reader(lambda item=item: _bookmark_response(service, item))
                for item in bookmarks
            ]
        )

    @router.post(
        "/documents/{document_id}/bookmarks",
        response_model=ReaderBookmarkResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_bookmark(
        request: Request,
        document_id: str,
        payload: CreateReaderBookmarkRequest,
    ) -> ReaderBookmarkResponse:
        service = _service(request)
        now = datetime.now(timezone.utc)
        cursor = _run_reader(
            lambda: _api_cursor_to_domain(service, document_id, payload.cursor),
            cursor_input=True,
        )
        bookmark = _run_reader(
            lambda: service.repository.create_bookmark(
                Bookmark(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    cursor=cursor,
                    label=payload.label,
                    note=payload.note,
                    created_at=now,
                    updated_at=now,
                )
            ),
            cursor_input=True,
        )
        service.observability.log_reader_operation(
            operation="create_bookmark",
            document_id=document_id,
            block_id=bookmark.cursor.block_id,
        )
        return _run_reader(lambda: _bookmark_response(service, bookmark))

    @router.patch("/bookmarks/{bookmark_id}", response_model=ReaderBookmarkResponse)
    async def update_bookmark(
        request: Request,
        bookmark_id: str,
        payload: UpdateReaderBookmarkRequest,
    ) -> ReaderBookmarkResponse:
        service = _service(request)
        current = _run_reader(
            lambda: service.repository.get_bookmark(bookmark_id),
            missing_entity="bookmark",
        )
        cursor = (
            _run_reader(
                lambda: _api_cursor_to_domain(
                    service,
                    current.document_id,
                    payload.cursor,
                ),
                cursor_input=True,
            )
            if payload.cursor
            else None
        )
        bookmark = _run_reader(
            lambda: service.repository.update_bookmark(
                bookmark_id,
                expected_row_version=payload.expected_row_version,
                cursor=cursor,
                label=payload.label,
                note=payload.note,
            ),
            missing_entity="bookmark",
            cursor_input=payload.cursor is not None,
        )
        service.observability.log_reader_operation(
            operation="update_bookmark",
            document_id=bookmark.document_id,
            block_id=bookmark.cursor.block_id,
        )
        return _run_reader(lambda: _bookmark_response(service, bookmark))

    @router.delete(
        "/bookmarks/{bookmark_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_bookmark(
        request: Request,
        bookmark_id: str,
        expected_row_version: Annotated[int, Query(gt=0)],
    ) -> Response:
        service = _service(request)
        bookmark = _run_reader(
            lambda: service.repository.get_bookmark(bookmark_id),
            missing_entity="bookmark",
        )
        _run_reader(
            lambda: service.repository.delete_bookmark(
                bookmark_id,
                expected_row_version=expected_row_version,
            ),
            missing_entity="bookmark",
        )
        service.observability.log_reader_operation(
            operation="delete_bookmark",
            document_id=bookmark.document_id,
            block_id=bookmark.cursor.block_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/queue", response_model=ReaderQueueResponse)
    async def list_queue(request: Request) -> ReaderQueueResponse:
        service = _service(request)
        items = _run_reader(service.repository.list_queue)
        return ReaderQueueResponse(
            items=[ReaderQueueItemResponse.from_domain(item) for item in items]
        )

    @router.post(
        "/queue/items",
        response_model=ReaderQueueItemResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_queue_item(
        request: Request,
        payload: AddReaderQueueItemRequest,
    ) -> ReaderQueueItemResponse:
        service = _service(request)
        now = datetime.now(timezone.utc)
        item = _run_reader(
            lambda: service.repository.add_queue_item(
                QueueItem(
                    id=str(uuid.uuid4()),
                    document_id=payload.document_id,
                    ordinal=service.next_queue_ordinal(),
                    status=payload.status,
                    added_at=now,
                    updated_at=now,
                )
            )
        )
        service.observability.log_reader_operation(
            operation="add_queue_item",
            document_id=item.document_id,
        )
        return ReaderQueueItemResponse.from_domain(item)

    @router.patch("/queue/items/{item_id}", response_model=ReaderQueueItemResponse)
    async def update_queue_item(
        request: Request,
        item_id: str,
        payload: UpdateReaderQueueItemRequest,
    ) -> ReaderQueueItemResponse:
        service = _service(request)
        item = _run_reader(
            lambda: service.repository.update_queue_item(
                item_id,
                expected_row_version=payload.expected_row_version,
                status=payload.status,
            ),
            missing_entity="queue item",
        )
        service.observability.log_reader_operation(
            operation="update_queue_item",
            document_id=item.document_id,
        )
        return ReaderQueueItemResponse.from_domain(item)

    @router.delete(
        "/queue/items/{item_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def remove_queue_item(
        request: Request,
        item_id: str,
        expected_row_version: Annotated[int, Query(gt=0)],
    ) -> Response:
        service = _service(request)
        _run_reader(
            lambda: service.repository.remove_queue_item(
                item_id,
                expected_row_version=expected_row_version,
            ),
            missing_entity="queue item",
        )
        service.observability.log_reader_operation(operation="remove_queue_item")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/queue/reorder", response_model=ReaderQueueResponse)
    async def reorder_queue(
        request: Request,
        payload: ReorderReaderQueueRequest,
    ) -> ReaderQueueResponse:
        service = _service(request)
        items = _run_reader(
            lambda: service.repository.reorder_queue(tuple(payload.item_ids)),
            missing_entity="queue item",
        )
        service.observability.log_reader_operation(operation="reorder_queue")
        return ReaderQueueResponse(
            items=[ReaderQueueItemResponse.from_domain(item) for item in items]
        )

    @router.post(
        "/queue/items/{item_id}/activate",
        response_model=ReaderQueueItemResponse,
    )
    async def activate_queue_item(request: Request, item_id: str) -> ReaderQueueItemResponse:
        service = _service(request)
        item = _run_reader(
            lambda: service.repository.activate_queue_item(item_id),
            missing_entity="queue item",
        )
        service.observability.log_reader_operation(
            operation="activate_queue_item",
            document_id=item.document_id,
        )
        return ReaderQueueItemResponse.from_domain(item)

    @router.post(
        "/queue/advance/{document_id}",
        response_model=ReaderQueueItemResponse | None,
    )
    async def advance_queue(
        request: Request,
        document_id: str,
    ) -> ReaderQueueItemResponse | None:
        service = _service(request)
        item = _run_reader(lambda: service.repository.advance_queue(document_id))
        service.observability.log_reader_operation(
            operation="advance_queue",
            document_id=document_id,
        )
        return ReaderQueueItemResponse.from_domain(item) if item is not None else None

    @router.get("/exports", response_model=ReaderExportJobListResponse)
    async def list_exports(request: Request) -> ReaderExportJobListResponse:
        service = _service(request)
        jobs = _run_reader(service.repository.list_export_jobs)
        return ReaderExportJobListResponse(
            jobs=[ReaderExportJobResponse.from_domain(job) for job in jobs]
        )

    @router.post(
        "/exports",
        response_model=ReaderExportJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_export(
        request: Request,
        payload: CreateReaderExportRequest,
    ) -> ReaderExportJobResponse:
        service = _service(request)
        manager = _export_manager(request)
        if payload.document_ids and payload.queue_item_ids:
            raise reader_api_error(
                "reader_conflict",
                status_code=400,
                message="Choose document IDs or queue item IDs, not both.",
            )
        document_ids = tuple(payload.document_ids)
        if payload.queue_item_ids:
            queue = {item.id: item for item in _run_reader(service.repository.list_queue)}
            missing = next(
                (item_id for item_id in payload.queue_item_ids if item_id not in queue),
                None,
            )
            if missing is not None:
                raise reader_api_error(
                    "reader_not_found",
                    status_code=404,
                    message="Reader queue item was not found.",
                )
            document_ids = tuple(queue[item_id].document_id for item_id in payload.queue_item_ids)
        if not document_ids:
            raise reader_api_error(
                "reader_conflict",
                status_code=400,
                message="At least one document or queue item is required.",
            )
        if payload.voice_id is not None and not request.app.state.container.voice_registry.has(
            payload.voice_id
        ):
            raise reader_api_error(
                "reader_voice_unavailable",
                status_code=400,
                message="The requested Reader voice is unavailable.",
                param="voice_id",
            )
        start_cursor = (
            _run_reader(
                lambda: _api_cursor_to_domain(service, document_ids[0], payload.start_cursor),
                cursor_input=True,
            )
            if payload.start_cursor is not None
            else None
        )
        end_cursor = (
            _run_reader(
                lambda: _api_cursor_to_domain(service, document_ids[0], payload.end_cursor),
                cursor_input=True,
            )
            if payload.end_cursor is not None
            else None
        )
        job = _run_reader(
            lambda: manager.create(
                document_ids=document_ids,
                section_ids=tuple(payload.section_ids),
                start_cursor=start_cursor,
                end_cursor=end_cursor,
                voice_id=payload.voice_id,
                output_basename=payload.output_basename,
                overwrite_existing=payload.overwrite_existing,
            )
        )
        return ReaderExportJobResponse.from_domain(job)

    @router.get("/exports/{job_id}", response_model=ReaderExportJobResponse)
    async def get_export(request: Request, job_id: str) -> ReaderExportJobResponse:
        service = _service(request)
        job = _run_reader(
            lambda: service.repository.get_export_job(job_id),
            missing_entity="export job",
        )
        return ReaderExportJobResponse.from_domain(job)

    @router.delete("/exports/{job_id}", response_model=ReaderExportJobResponse)
    async def cancel_export(request: Request, job_id: str) -> ReaderExportJobResponse:
        job = _run_reader(
            lambda: _export_manager(request).cancel(job_id),
            missing_entity="export job",
        )
        return ReaderExportJobResponse.from_domain(job)

    @router.get("/exports/{job_id}/result")
    async def get_export_result(
        request: Request,
        job_id: str,
        index: Annotated[int, Query(ge=0)] = 0,
    ) -> FileResponse:
        service = _service(request)
        job = _run_reader(
            lambda: service.repository.get_export_job(job_id),
            missing_entity="export job",
        )
        path = _run_reader(lambda: _export_manager(request).result_path(job, index))
        return FileResponse(path, filename=path.name, media_type="audio/wav")

    @router.get("/diagnostics", response_model=ReaderDiagnosticsResponse)
    async def reader_diagnostics(request: Request) -> ReaderDiagnosticsResponse:
        service = _service(request)
        report = _run_reader(service.repository.report)
        queue = _run_reader(service.repository.list_queue)
        jobs = _run_reader(service.repository.list_export_jobs)
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job.status.value] = counts.get(job.status.value, 0) + 1
        return ReaderDiagnosticsResponse(
            database_ready=report.ready,
            schema_version=report.schema_version,
            integrity_message=report.integrity_message,
            search_available=service.repository.search_available,
            document_counts_by_state={
                state.value: count
                for state, count in _run_reader(
                    service.repository.document_counts_by_state
                ).items()
            },
            queue_item_count=len(queue),
            active_content_leases=service.content_leases.active_lease_count(),
            export_status_counts=counts,
            metrics=request.app.state.container.observability.snapshot(),
        )

    @router.get("/rule-sets", response_model=ReaderRuleSetListResponse)
    async def list_rule_sets(request: Request) -> ReaderRuleSetListResponse:
        service = _service(request)
        rule_sets = _run_reader(service.repository.list_rule_sets, missing_entity="rule set")
        return ReaderRuleSetListResponse(
            rule_sets=[ReaderRuleSetResponse.from_domain(item) for item in rule_sets],
            rules_version=_run_reader(service.repository.get_rules_version),
        )

    @router.post(
        "/rule-sets",
        response_model=ReaderRuleSetResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_rule_set(
        request: Request, payload: CreateReaderRuleSetRequest
    ) -> ReaderRuleSetResponse:
        service = _service(request)
        rule_set = _run_rule(
            lambda: service.create_rule_set(
                name=payload.name,
                description=payload.description,
                scope=payload.scope,
            ),
            missing_entity="rule set",
        )
        return ReaderRuleSetResponse.from_domain(rule_set)

    @router.patch("/rule-sets/{rule_set_id}", response_model=ReaderRuleSetResponse)
    async def update_rule_set(
        request: Request,
        rule_set_id: str,
        payload: UpdateReaderRuleSetRequest,
    ) -> ReaderRuleSetResponse:
        service = _service(request)
        current = _run_reader(
            lambda: service.repository.get_rule_set(rule_set_id),
            missing_entity="rule set",
        )
        changes = payload.model_dump(exclude={"expected_row_version"}, exclude_unset=True)
        updated = _run_reader(
            lambda: service.repository.update_rule_set(
                replace(current, **changes),
                expected_row_version=payload.expected_row_version,
            ),
            missing_entity="rule set",
        )
        return ReaderRuleSetResponse.from_domain(updated)

    @router.delete("/rule-sets/{rule_set_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_rule_set(
        request: Request,
        rule_set_id: str,
        expected_row_version: Annotated[int, Query(gt=0)],
    ) -> Response:
        service = _service(request)
        _run_reader(
            lambda: service.repository.delete_rule_set(
                rule_set_id, expected_row_version=expected_row_version
            ),
            missing_entity="rule set",
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/rule-sets/{rule_set_id}/rules", response_model=ReaderRuleListResponse
    )
    async def list_rules(request: Request, rule_set_id: str) -> ReaderRuleListResponse:
        service = _service(request)
        _run_reader(
            lambda: service.repository.get_rule_set(rule_set_id),
            missing_entity="rule set",
        )
        rules = _run_reader(
            lambda: service.repository.list_rules((rule_set_id,)),
            missing_entity="rule set",
        )
        return ReaderRuleListResponse(
            rules=[ReaderRuleResponse.from_domain(item) for item in rules]
        )

    @router.post(
        "/rule-sets/{rule_set_id}/rules",
        response_model=ReaderRuleResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_rule(
        request: Request,
        rule_set_id: str,
        payload: CreateReaderRuleRequest,
    ) -> ReaderRuleResponse:
        service = _service(request)
        rule = _run_rule(
            lambda: service.create_rule(rule_set_id=rule_set_id, **payload.model_dump()),
            missing_entity="rule set",
        )
        return ReaderRuleResponse.from_domain(rule)

    @router.patch("/rules/{rule_id}", response_model=ReaderRuleResponse)
    async def update_rule(
        request: Request,
        rule_id: str,
        payload: UpdateReaderRuleRequest,
    ) -> ReaderRuleResponse:
        service = _service(request)
        current = _run_reader(
            lambda: service.repository.get_rule(rule_id),
            missing_entity="speech rule",
        )
        changes = payload.model_dump(exclude={"expected_row_version"}, exclude_unset=True)
        if changes.get("regex_timeout_ms") is None:
            changes.pop("regex_timeout_ms", None)
        candidate = replace(current, **changes)
        updated = _run_rule(
            lambda: _validate_and_update_rule(
                service,
                candidate,
                payload.expected_row_version,
            ),
            missing_entity="speech rule",
        )
        return ReaderRuleResponse.from_domain(updated)

    @router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_rule(
        request: Request,
        rule_id: str,
        expected_row_version: Annotated[int, Query(gt=0)],
    ) -> Response:
        service = _service(request)
        _run_reader(
            lambda: service.repository.delete_rule(
                rule_id, expected_row_version=expected_row_version
            ),
            missing_entity="speech rule",
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/rules/preview", response_model=ReaderRulePreviewResponse)
    async def preview_rules(
        request: Request, payload: ReaderRulePreviewRequest
    ) -> ReaderRulePreviewResponse:
        service = _service(request)
        result = await run_in_threadpool(
            lambda: _run_rule(
                lambda: service.preview_rules(
                    payload.text,
                    rule_set_ids=tuple(payload.rule_set_ids),
                    context=RuleContext(
                        language=payload.language,
                        engine=payload.engine,
                        voice=payload.voice,
                        document_id=payload.document_id,
                    ),
                ),
                missing_entity="rule set",
            )
        )
        return ReaderRulePreviewResponse(
            original_text=payload.text,
            spoken_text=result.text,
            source_spans=[
                ReaderRulePreviewSpan(
                    start_offset=_utf16(payload.text, span.start_offset),
                    end_offset=_utf16(payload.text, span.end_offset),
                )
                for span in result.source_spans
            ],
            trace=[
                ReaderRuleTraceResponse(
                    rule_id=item.rule_id,
                    rule_type=item.rule_type,
                    start_offset=_utf16(payload.text, item.start_offset),
                    end_offset=_utf16(payload.text, item.end_offset),
                    replacement_length=item.replacement_length,
                )
                for item in result.trace
            ],
            warnings=[
                ReaderRuleWarningResponse(
                    code=item.code, message=item.message, rule_id=item.rule_id
                )
                for item in result.warnings
            ],
            elapsed_ms=result.elapsed_ms,
            pipeline_version=1,
            rules_version=_run_reader(service.repository.get_rules_version),
        )

    @router.post("/rule-imports", response_model=ReaderRuleImportReportResponse)
    async def import_rules(
        request: Request, payload: ReaderRuleImportRequest
    ) -> ReaderRuleImportReportResponse:
        service = _service(request)
        report = await run_in_threadpool(
            lambda: _run_rule(
                lambda: service.import_rules(
                    target_rule_set_id=payload.target_rule_set_id,
                    source_data=payload.content.encode("utf-8"),
                    commit=payload.commit,
                ),
                missing_entity="rule set",
            )
        )
        return ReaderRuleImportReportResponse(
            source_sha256=report.source_sha256,
            imported=report.imported,
            disabled=report.disabled,
            duplicate=report.duplicate,
            invalid=report.invalid,
            unsupported=report.unsupported,
            committed=report.committed,
            idempotent=report.idempotent,
        )

    @router.get("/rule-sets/{rule_set_id}/export")
    async def export_rules(request: Request, rule_set_id: str) -> Response:
        service = _service(request)
        content = _run_rule(
            lambda: service.export_rules(rule_set_id), missing_entity="rule set"
        )
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="rule-set-{rule_set_id}.json"'
            },
        )

    return router


def _service(request: Request) -> ReaderApplicationService:
    runtime = request.app.state.container.reader
    if not runtime.enabled:
        raise reader_disabled()
    if runtime.service is None or not runtime.database_ready:
        raise reader_database_unavailable()
    return runtime.service


def _export_manager(request: Request):
    manager = request.app.state.container.reader_exports
    if manager is None:
        raise reader_api_error(
            "reader_export_unavailable",
            status_code=503,
            message="Reader WAV export is disabled or unavailable.",
        )
    return manager


def _run_reader(
    operation: Callable[[], T],
    *,
    missing_entity: str = "document",
    cursor_input: bool = False,
) -> T:
    try:
        return operation()
    except ReaderError as exc:
        raise translate_reader_error(
            exc,
            missing_entity=missing_entity,
            cursor_input=cursor_input,
        ) from exc


def _run_rule(
    operation: Callable[[], T],
    *,
    missing_entity: str,
) -> T:
    try:
        return operation()
    except SpeechRuleError as exc:
        raise translate_rule_error(exc) from exc
    except ReaderError as exc:
        raise translate_reader_error(exc, missing_entity=missing_entity) from exc


def _utf16(text: str, offset: int) -> int:
    from .reader_offsets import python_offset_to_utf16

    return python_offset_to_utf16(text, offset)


def _validate_and_update_rule(
    service: ReaderApplicationService,
    candidate: SpeechRule,
    expected_row_version: int,
) -> SpeechRule:
    service.rule_engine().validate_rule(candidate)
    return service.repository.update_rule(
        candidate, expected_row_version=expected_row_version
    )


async def _run_import_async(operation: Callable[[Event], T]) -> T:
    cancellation = Event()
    try:
        return await run_in_threadpool(partial(operation, cancellation))
    except asyncio.CancelledError:
        cancellation.set()
        raise
    except (
        DocumentImportError,
        ReaderImportPreviewCapacityError,
        ReaderImportPreviewNotFoundError,
    ) as exc:
        raise translate_import_error(exc) from exc
    except ReaderError as exc:
        raise translate_reader_error(exc) from exc


async def _read_import_source(upload: UploadFile, max_file_bytes: int) -> ImportSource:
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = await upload.read(min(1_048_576, max_file_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_file_bytes:
                raise reader_api_error(
                    "reader_import_too_large",
                    status_code=413,
                    message="The imported file exceeds the configured size limit.",
                    details={"max_file_bytes": max_file_bytes},
                )
            chunks.append(chunk)
    finally:
        await upload.close()
    return ImportSource(
        filename=upload.filename or "imported-document",
        content_type=upload.content_type,
        data=b"".join(chunks),
    )


def _import_preview_response(preview: ReaderImportPreview) -> ReaderImportPreviewResponse:
    imported = preview.imported
    source_type = {
        "txt": "text_file",
        "md": "markdown",
        "html": "html",
        "docx": "docx",
        "epub": "epub",
    }[imported.source_format]
    section_limit = 100
    block_limit = 20
    return ReaderImportPreviewResponse(
        preview_id=preview.id,
        title=imported.title,
        source_type=source_type,
        source_name=imported.source_name,
        total_sections=len(imported.sections),
        total_blocks=len(imported.blocks),
        total_characters=imported.total_characters,
        warnings=[
            ReaderImportWarningResponse(
                code=warning.code,
                message=warning.message,
                count=warning.count,
            )
            for warning in imported.warnings
        ],
        sections=[
            ReaderImportSectionPreviewResponse(
                ordinal=section.ordinal,
                level=section.level,
                heading=section.heading,
                first_block_ordinal=section.first_block_ordinal,
            )
            for section in imported.sections[:section_limit]
        ],
        sample_blocks=[
            ReaderImportBlockPreviewResponse(
                ordinal=block.ordinal,
                kind=block.kind,
                text=block.text[:1_000],
                section_ordinal=block.section_ordinal,
            )
            for block in imported.blocks[:block_limit]
        ],
        preview_truncated=(
            len(imported.sections) > section_limit or len(imported.blocks) > block_limit
        ),
        duplicate_document_id=preview.duplicate_document_id,
    )


def _run_content_mutation(
    service: ReaderApplicationService,
    document_id: str,
    operation: Callable[[], T],
    *,
    missing_entity: str = "document",
) -> T:
    try:
        with service.content_mutation(document_id):
            return operation()
    except ReaderError as exc:
        raise translate_reader_error(exc, missing_entity=missing_entity) from exc


def _api_cursor_to_domain(
    service: ReaderApplicationService,
    document_id: str,
    payload: ReaderCursorPayload,
) -> ReaderCursor:
    document = service.get_document(document_id)
    if payload.content_revision != document.content_revision:
        raise ReaderStaleCursorError("API cursor content revision is stale")
    blocks = service.list_blocks(
        document_id,
        after_ordinal=payload.block_ordinal - 1,
        limit=1,
    )
    if not blocks or blocks[0].id != payload.block_id:
        raise ReaderStaleCursorError("API cursor block does not match its ordinal")
    try:
        character_offset = utf16_offset_to_python(
            blocks[0].text,
            payload.character_offset,
        )
    except ReaderOffsetError as error:
        raise ReaderValidationError("API cursor UTF-16 offset is invalid") from error
    return ReaderCursor(
        document_id=document_id,
        block_id=payload.block_id,
        block_ordinal=payload.block_ordinal,
        character_offset=character_offset,
        content_revision=payload.content_revision,
        segment_index=payload.segment_index,
    )


def _cursor_source_text(
    service: ReaderApplicationService,
    cursor: ReaderCursor,
) -> str:
    blocks = service.list_blocks(
        cursor.document_id,
        after_ordinal=cursor.block_ordinal - 1,
        limit=1,
    )
    if not blocks or blocks[0].id != cursor.block_id:
        raise ReaderStaleCursorError("stored cursor block does not match its ordinal")
    return blocks[0].text


def _position_response(
    service: ReaderApplicationService,
    position: PlaybackPosition,
) -> ReaderPositionResponse:
    return ReaderPositionResponse.from_domain(
        position,
        source_text=_cursor_source_text(service, position.cursor),
    )


def _bookmark_response(
    service: ReaderApplicationService,
    bookmark: Bookmark,
) -> ReaderBookmarkResponse:
    return ReaderBookmarkResponse.from_domain(
        bookmark,
        source_text=_cursor_source_text(service, bookmark.cursor),
    )
