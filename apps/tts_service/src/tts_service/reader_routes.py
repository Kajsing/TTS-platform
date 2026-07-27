from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, TypeVar

from fastapi import APIRouter, Query, Request, Response, status
from reader_core import (
    Bookmark,
    DocumentState,
    PlaybackPosition,
    QueueItem,
    ReaderCursor,
    ReaderError,
    ReaderStaleCursorError,
    ReaderValidationError,
)

from .reader_errors import (
    reader_api_error,
    reader_database_unavailable,
    reader_disabled,
    translate_reader_error,
)
from .reader_offsets import ReaderOffsetError, utf16_offset_to_python
from .reader_schemas import (
    AddReaderQueueItemRequest,
    AppendReaderContentRequest,
    CreateReaderBookmarkRequest,
    CreateReaderDocumentRequest,
    ExpectedReaderVersionRequest,
    ReaderBlockPageResponse,
    ReaderBlockResponse,
    ReaderBookmarkListResponse,
    ReaderBookmarkResponse,
    ReaderCapabilitiesResponse,
    ReaderCursorPayload,
    ReaderDatabaseCapability,
    ReaderDocumentPageResponse,
    ReaderDocumentResponse,
    ReaderEditResponse,
    ReaderExportCapability,
    ReaderImportCapability,
    ReaderMutationResponse,
    ReaderPlaybackCapability,
    ReaderPositionEnvelope,
    ReaderPositionResponse,
    ReaderQueueItemResponse,
    ReaderQueueResponse,
    ReaderRuleCapability,
    ReorderReaderQueueRequest,
    ReplaceReaderContentRequest,
    SaveReaderPositionRequest,
    UpdateReaderBookmarkRequest,
    UpdateReaderDocumentRequest,
    UpdateReaderQueueItemRequest,
)
from .reader_service import ReaderApplicationService

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
                search_available=False,
            ),
            imports=ReaderImportCapability(
                formats=[],
                max_file_bytes=0,
                ocr_available=False,
            ),
            rules=ReaderRuleCapability(types=[], regex_timeout_supported=False),
            playback=ReaderPlaybackCapability(
                stream_protocol_version=1,
                source_offset_encoding="utf-16",
                max_blocks_per_window=config.max_blocks_per_stream_window,
                max_source_chars_per_window=config.max_source_chars_per_stream_window,
            ),
            exports=ReaderExportCapability(formats=[]),
        )

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

    return router


def _service(request: Request) -> ReaderApplicationService:
    runtime = request.app.state.container.reader
    if not runtime.enabled:
        raise reader_disabled()
    if runtime.service is None or not runtime.database_ready:
        raise reader_database_unavailable()
    return runtime.service


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
