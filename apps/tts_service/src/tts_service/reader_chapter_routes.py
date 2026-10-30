"""Owner/device chapter navigation reads metadata and bounded block identities only."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from reader_core.chapter_index import ChapterIndex, ChapterIndexConflictError
from reader_core.errors import ReaderConflictError, ReaderDatabaseError, ReaderError
from reader_core.sqlite.chapter_index import read_chapter_access, read_chapter_index
from starlette.concurrency import run_in_threadpool

from .errors import APIError
from .reader_errors import reader_api_error, translate_reader_error
from .reader_routes import _privacy_tokens, _require_document_access, _run_reader, _service
from .reader_schemas import ReaderChapterIndexResponse

MAX_CHAPTER_RESPONSE_BYTES = 1024 * 1024


def _revision_conflict(document_id: str, expected: int, actual: int):
    return reader_api_error(
        "reader_revision_conflict",
        status_code=409,
        message="The article changed. Reopen it before navigating its chapters.",
        details={
            "document_id": document_id,
            "expected_content_revision": expected,
            "actual_content_revision": actual,
        },
    )


def _require_current_access(request: Request, document_id: str, revision: int) -> None:
    try:
        document = _require_document_access(request, document_id)
    except (json.JSONDecodeError, APIError) as error:
        # The shared document mapper parses metadata before its folder check.
        # Corrupt JSON must still respect privacy, then produce a typed conflict.
        if isinstance(error, APIError) and not (
            isinstance(error.__cause__, ReaderDatabaseError)
            and str(error.__cause__) == "Reader metadata JSON must contain an object"
        ):
            raise
        service = _service(request)
        access = _run_reader(lambda: read_chapter_access(service.repository, document_id))
        _run_reader(
            lambda: service.privacy.require_folder_access(
                access.folder_id, _privacy_tokens(request)
            )
        )
        if access.deleted or access.content_revision != revision:
            raise _revision_conflict(document_id, revision, access.content_revision) from error
        raise reader_api_error(
            "reader_chapter_index_conflict",
            status_code=409,
            message=(
                "The article chapter metadata is invalid. Its stored content was kept unchanged."
            ),
        ) from error
    if document.deleted_at is not None or document.content_revision != revision:
        raise _revision_conflict(document_id, revision, document.content_revision)


def _read_index(repository, document_id: str, revision: int) -> ChapterIndex:
    try:
        return read_chapter_index(repository, document_id, revision)
    except ChapterIndexConflictError as error:
        raise reader_api_error(
            "reader_chapter_index_conflict",
            status_code=409,
            message=(
                "The article chapter metadata is invalid. Its stored content was kept unchanged."
            ),
        ) from error
    except ReaderConflictError as error:
        raise _revision_conflict(document_id, revision, error.actual) from error
    except ReaderError as error:
        raise translate_reader_error(error) from error


def _response(index: ChapterIndex) -> Response:
    try:
        encoded = json.dumps(
            asdict(index), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except UnicodeError as error:
        raise reader_api_error(
            "reader_chapter_index_conflict",
            status_code=409,
            message="The article chapter metadata contains invalid Unicode.",
        ) from error
    if len(encoded) > MAX_CHAPTER_RESPONSE_BYTES:
        raise reader_api_error(
            "reader_chapter_index_too_large",
            status_code=413,
            message="The chapter index exceeds its response size limit.",
        )
    return Response(encoded, media_type="application/json")


def build_reader_chapter_router() -> APIRouter:
    router = APIRouter(prefix="/v1/reader/documents", tags=["reader"])

    @router.get("/{document_id}/chapters", response_model=ReaderChapterIndexResponse)
    async def chapters(
        request: Request,
        document_id: str,
        expected_content_revision: Annotated[int, Query(gt=0)],
    ) -> Response:
        await run_in_threadpool(
            _require_current_access, request, document_id, expected_content_revision
        )
        index = await run_in_threadpool(
            _read_index, _service(request).repository, document_id, expected_content_revision
        )
        response = await run_in_threadpool(_response, index)
        await run_in_threadpool(
            _require_current_access, request, document_id, expected_content_revision
        )
        # A lock/move can happen while the final worker resumes on the event loop.
        # Keep the last access/revision fence synchronous, with no await afterward.
        _require_current_access(request, document_id, expected_content_revision)
        return response

    return router
