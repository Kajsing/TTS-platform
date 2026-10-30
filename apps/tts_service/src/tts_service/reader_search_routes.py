"""Owner-authenticated source search. Requests contain queries; results contain positions only."""

from __future__ import annotations

import asyncio
import json
import re
import threading
from contextlib import suppress

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from reader_core.errors import ReaderError
from starlette.concurrency import run_in_threadpool

from .reader_errors import reader_api_error, translate_reader_error
from .reader_routes import _require_document_access, _service
from .reader_schemas import ReaderCursorResponse
from .reader_search import (
    MAX_RESULT_PAGE,
    MAX_WINDOW_MATCHES,
    ReaderSearchError,
    ReaderSearchManager,
)

SEARCH_BODY_BYTES = 16 * 1024
SEARCH_RESPONSE_BYTES = 1024 * 1024
_SEARCH_PATH = re.compile(
    r"^/v1/reader/documents/[^/]+/(?:search(?:/[^/]+/(?:results|window|next))?|highlights)$"
)


def is_search_request(method: str, path: str) -> bool:
    return method == "POST" and _SEARCH_PATH.fullmatch(path) is not None


async def bound_search_body(request: Request) -> None:
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > SEARCH_BODY_BYTES:
            raise reader_api_error(
                "reader_search_request_too_large",
                status_code=413,
                message="Search request exceeds its size limit.",
            )
        chunks.append(chunk)
    request._body = b"".join(chunks)


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_content_revision: int = Field(gt=0)
    query: str = Field(max_length=1024)
    case_sensitive: bool = False
    whole_word: bool = False
    use_regex: bool = False
    max_results: int = Field(default=10_000, gt=0, le=10_000)


class HighlightInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_content_revision: int = Field(gt=0)
    expected_highlighter_row_version: int = Field(gt=0)


class ResultsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=MAX_RESULT_PAGE, gt=0, le=MAX_RESULT_PAGE)


class WindowInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start_ordinal: int = Field(ge=0)
    end_ordinal: int = Field(ge=0)
    limit: int = Field(default=MAX_WINDOW_MATCHES, gt=0, le=MAX_WINDOW_MATCHES)


class NextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    term_id: str = Field(min_length=1, max_length=80)
    after_index: int = Field(default=-1, ge=-1)


class SearchSummaryResponse(BaseModel):
    search_id: str
    document_id: str
    content_revision: int
    kind: str
    total_matches: int
    counts: dict[str, int]
    truncated: bool
    failure: str | None
    regex_dialect: str | None
    expires_in_seconds: int


class SearchHitResponse(BaseModel):
    index: int
    start: int
    length: int
    term_id: str | None
    start_cursor: ReaderCursorResponse
    end_cursor: ReaderCursorResponse


class SearchPageResponse(BaseModel):
    document_id: str
    content_revision: int
    matches: list[SearchHitResponse]
    next_offset: int | None
    total_matches: int
    truncated: bool


class SearchNextResponse(BaseModel):
    match: SearchHitResponse | None


def _manager(request: Request) -> ReaderSearchManager:
    _service(request)
    manager = request.app.state.container.reader_search
    if manager is None:
        raise reader_api_error(
            "reader_disabled", status_code=503, message="Reader search is unavailable."
        )
    return manager


def _run(call):
    try:
        return call()
    except ReaderSearchError as error:
        response = reader_api_error(
            error.kind,
            status_code=error.status,
            message=str(error),
            details={"retry_after_seconds": 1, "request_budget": "background"}
            if error.status == 429
            else None,
        )
        if error.status == 429:
            response.headers.update({"Retry-After": "1", "X-TTS-Request-Budget": "background"})
        raise response from error
    except ReaderError as error:
        raise translate_reader_error(error) from error


def _encode(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def _response(payload: dict, *, paged: bool = False) -> Response:
    encoded = _encode(payload)
    while len(encoded) > SEARCH_RESPONSE_BYTES and payload.get("matches"):
        matches = payload["matches"]
        del matches[max(1, len(matches) // 2) :]
        if len(matches) == 1 and len(_encode(payload)) > SEARCH_RESPONSE_BYTES:
            break
        if paged:
            payload["next_offset"] = matches[-1]["index"] + 1
        else:
            payload["truncated"] = True
        encoded = _encode(payload)
    if len(encoded) > SEARCH_RESPONSE_BYTES:
        raise reader_api_error(
            "reader_search_response_too_large",
            status_code=413,
            message="Search results exceed their response size limit.",
        )
    return Response(encoded, media_type="application/json")


async def _create(request: Request, document_id: str, revision: int, **options) -> Response:
    _require_document_access(request, document_id)
    manager = _manager(request)
    cancelled = threading.Event()

    async def observe_disconnect() -> None:
        while not cancelled.is_set():
            if await request.is_disconnected():
                cancelled.set()
                return
            await asyncio.sleep(0.1)

    observer = asyncio.create_task(observe_disconnect())
    try:
        session = await run_in_threadpool(
            _run, lambda: manager.create(document_id, revision, cancellation=cancelled, **options)
        )
        try:
            _require_document_access(request, document_id)
            _run(lambda: manager._current(document_id, revision, session.highlighter_version))
        except Exception:
            manager.drop(session.id)
            raise
        return _response(session.summary())
    finally:
        cancelled.set()
        observer.cancel()
        with suppress(asyncio.CancelledError):
            await observer


async def _finish_results(
    request: Request, document_id: str, session, body: dict, *, paged: bool = False
) -> Response:
    response = await run_in_threadpool(_response, body, paged=paged)
    await run_in_threadpool(
        _run,
        lambda: _manager(request)._current(
            document_id, session.content_revision, session.highlighter_version
        ),
    )
    _require_document_access(request, document_id)
    return response


def build_reader_search_router() -> APIRouter:
    router = APIRouter(prefix="/v1/reader/documents", tags=["reader"])

    @router.post("/{document_id}/search", response_model=SearchSummaryResponse)
    async def search(request: Request, document_id: str, payload: SearchInput) -> Response:
        return await _create(
            request,
            document_id,
            payload.expected_content_revision,
            query=payload.query,
            case_sensitive=payload.case_sensitive,
            whole_word=payload.whole_word,
            use_regex=payload.use_regex,
            max_results=payload.max_results,
        )

    @router.post("/{document_id}/highlights", response_model=SearchSummaryResponse)
    async def highlights(request: Request, document_id: str, payload: HighlightInput) -> Response:
        return await _create(
            request,
            document_id,
            payload.expected_content_revision,
            highlighter_version=payload.expected_highlighter_row_version,
        )

    @router.post("/{document_id}/search/{search_id}/results", response_model=SearchPageResponse)
    async def results(
        request: Request, document_id: str, search_id: str, payload: ResultsInput
    ) -> Response:
        _require_document_access(request, document_id)
        session, body = await run_in_threadpool(
            _run,
            lambda: _manager(request).results(
                document_id, search_id, payload.offset, payload.limit
            ),
        )
        return await _finish_results(request, document_id, session, body, paged=True)

    @router.post("/{document_id}/search/{search_id}/window", response_model=SearchPageResponse)
    async def window(
        request: Request, document_id: str, search_id: str, payload: WindowInput
    ) -> Response:
        _require_document_access(request, document_id)
        if payload.end_ordinal < payload.start_ordinal:
            raise reader_api_error(
                "invalid_request", status_code=400, message="Search window end precedes its start."
            )
        session, body = await run_in_threadpool(
            _run,
            lambda: _manager(request).window(
                document_id, search_id, payload.start_ordinal, payload.end_ordinal, payload.limit
            ),
        )
        return await _finish_results(request, document_id, session, body)

    @router.post("/{document_id}/search/{search_id}/next", response_model=SearchNextResponse)
    async def next_match(
        request: Request, document_id: str, search_id: str, payload: NextInput
    ) -> Response:
        _require_document_access(request, document_id)
        session, body = await run_in_threadpool(
            _run,
            lambda: _manager(request).next_match(
                document_id, search_id, payload.term_id, payload.after_index
            ),
        )
        return await _finish_results(request, document_id, session, body)

    return router
