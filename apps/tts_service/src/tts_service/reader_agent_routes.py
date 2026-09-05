"""Native-loopback agent API and separately owner-authenticated grant setup."""

from __future__ import annotations

import ipaddress
from dataclasses import asdict
from typing import Annotated, Callable, TypeVar

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from reader_core.agent_access import (
    MAX_AGENT_PAGE,
    MAX_AGENT_TEXT,
    AgentConflictError,
    AgentUnauthorizedError,
    ChapterDelivery,
)
from reader_core.errors import ReaderError
from reader_core.models import ReaderDocument
from starlette.concurrency import run_in_threadpool

from .reader_agent_service import ReaderAgentService
from .reader_errors import reader_api_error, translate_reader_error
from .security import RateLimiter, extract_bearer_token

AGENT_PREFIX = "/v1/reader/agent/"
AGENT_ADMIN_PREFIX = "/v1/reader/agent-access/"
MAX_AGENT_REQUEST_BYTES = 2 * 1024 * 1024
T = TypeVar("T")


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GrantRequest(AgentRequest):
    folder_id: str = Field(min_length=1, max_length=80)
    name: str = Field(default="Local agent", min_length=1, max_length=80)


class CreateArticleRequest(AgentRequest):
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=MAX_AGENT_TEXT)


class VersionRequest(AgentRequest):
    expected_row_version: int = Field(ge=1)


class RenameArticleRequest(VersionRequest):
    title: str = Field(min_length=1, max_length=500)


class AppendArticleRequest(VersionRequest):
    text: str = Field(min_length=1, max_length=MAX_AGENT_TEXT)


class ReplaceArticleRequest(VersionRequest):
    old_text: str = Field(min_length=1, max_length=MAX_AGENT_TEXT)
    new_text: str = Field(max_length=MAX_AGENT_TEXT)


class DeliverChapterRequest(AppendArticleRequest):
    story_key: str = Field(min_length=1, max_length=200)
    chapter_key: str = Field(min_length=1, max_length=200)
    retry_key: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    order_label: str | None = Field(default=None, min_length=1, max_length=200)
    order_index: int | None = Field(default=None, ge=-(2**53 - 1), le=2**53 - 1)


def _local_native(request: Request) -> None:
    host = request.client.host if request.client else ""
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    if "origin" in request.headers or not local:
        raise reader_api_error(
            "reader_agent_local_only",
            status_code=403,
            message="Agent access requires a native client on this computer.",
        )
    if not request.app.state.container.auth.enabled:
        raise reader_api_error(
            "reader_agent_unavailable",
            status_code=503,
            message="Enable local token authentication before configuring agent access.",
        )


def _service(request: Request) -> ReaderAgentService:
    runtime = request.app.state.container.reader
    if not runtime.enabled or runtime.service is None or not runtime.database_ready:
        raise reader_api_error(
            "reader_agent_unavailable",
            status_code=503,
            message="Reader storage is unavailable.",
        )
    return runtime.service.agents


def _run(call: Callable[[], T]) -> T:
    try:
        return call()
    except AgentUnauthorizedError as exc:
        raise reader_api_error(
            "reader_agent_unauthorized",
            status_code=403,
            message=str(exc),
        ) from exc
    except AgentConflictError as exc:
        raise reader_api_error(
            "reader_agent_conflict",
            status_code=409,
            message=str(exc),
        ) from exc
    except ReaderError as exc:
        raise translate_reader_error(exc) from exc


async def enforce_agent_request(request: Request) -> None:
    """Authenticate before JSON parsing; agent traffic has its own bounded budget."""
    _local_native(request)
    request.app.state.reader_agent_limiter.check("local-agent")
    secret = extract_bearer_token(request) or ""
    await run_in_threadpool(_run, lambda: _service(request).store.authenticate(secret))
    request.state.reader_agent_credential = secret
    await bound_agent_body(request)


async def bound_agent_body(request: Request) -> None:
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_AGENT_REQUEST_BYTES:
            raise reader_api_error(
                "reader_agent_request_too_large",
                status_code=413,
                message="Agent request exceeds the bounded request size.",
            )
        chunks.append(chunk)
    # BaseHTTPMiddleware replays Request's cached body to the downstream router.
    request._body = b"".join(chunks)


def enforce_agent_admin(request: Request) -> None:
    _local_native(request)


def _call(request: Request, operation: str, **arguments):
    credential = getattr(request.state, "reader_agent_credential", "")
    return _run(lambda: _service(request).run(credential, operation, **arguments))


def _article(document: ReaderDocument) -> dict[str, object]:
    # Explicit projection: private import metadata/paths must not leak from a
    # document moved into an agent workspace through normal Reader controls.
    return {
        "id": document.id,
        "title": document.title,
        "folder_id": document.folder_id,
        "row_version": document.row_version,
        "content_revision": document.content_revision,
        "state": document.state.value,
        "total_characters": document.total_characters,
        "updated_at": document.updated_at.isoformat(),
    }


def build_reader_agent_router() -> APIRouter:
    router = APIRouter(prefix=AGENT_PREFIX.rstrip("/"), tags=["reader-agent"])

    @router.get("/workspace")
    def workspace(request: Request):
        grant, folder = _call(request, "workspace")
        return {
            "contract_version": 1,
            "grant_id": grant.id,
            "folder_id": folder.id,
            "folder_name": folder.name,
            "operations": grant.operations,
            "max_text_characters": MAX_AGENT_TEXT,
            "max_page_characters": MAX_AGENT_PAGE,
        }

    @router.get("/articles")
    def articles(
        request: Request,
        query: Annotated[str | None, Query(max_length=200)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ):
        page = _call(request, "list", query=query, limit=limit, cursor=cursor)
        return {"items": [_article(item) for item in page.items], "next_cursor": page.next_cursor}

    @router.post("/articles", status_code=201)
    def create(request: Request, payload: CreateArticleRequest):
        return _article(_call(request, "create", **payload.model_dump()))

    @router.get("/articles/{document_id}")
    def read(
        request: Request,
        document_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=MAX_AGENT_PAGE)] = MAX_AGENT_PAGE,
        expected_row_version: Annotated[int | None, Query(ge=1)] = None,
    ):
        page = _call(
            request,
            "read",
            document_id=document_id,
            offset=offset,
            limit=limit,
            expected_row_version=expected_row_version,
        )
        return {
            "article": _article(page.document),
            "text": page.text,
            "offset": page.offset,
            "next_offset": page.next_offset,
            "text_length": page.text_length,
        }

    @router.patch("/articles/{document_id}")
    def rename(request: Request, document_id: str, payload: RenameArticleRequest):
        return _article(_call(request, "rename", document_id=document_id, **payload.model_dump()))

    @router.post("/articles/{document_id}/append")
    def append(request: Request, document_id: str, payload: AppendArticleRequest):
        return _article(_call(request, "append", document_id=document_id, **payload.model_dump()))

    @router.patch("/articles/{document_id}/text")
    def edit(request: Request, document_id: str, payload: ReplaceArticleRequest):
        return _article(_call(request, "replace", document_id=document_id, **payload.model_dump()))

    @router.get("/articles/{document_id}/chapters")
    def chapters(
        request: Request,
        document_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        items = _call(request, "chapters", document_id=document_id, offset=offset, limit=limit)
        return {
            "items": [asdict(item) for item in items],
            "next_offset": offset + len(items) if len(items) == limit else None,
        }

    @router.post("/articles/{document_id}/chapters")
    def deliver(request: Request, document_id: str, payload: DeliverChapterRequest):
        receipt = _run(
            lambda: _call(
                request,
                "deliver",
                document_id=document_id,
                delivery=ChapterDelivery(**payload.model_dump(exclude={"expected_row_version"})),
                expected_row_version=payload.expected_row_version,
            )
        )
        return asdict(receipt)

    return router


def build_reader_agent_admin_router() -> APIRouter:
    router = APIRouter(prefix=AGENT_ADMIN_PREFIX.rstrip("/"), tags=["reader-agent-admin"])

    @router.get("/grants")
    def grants(request: Request):
        return {"grants": [asdict(grant) for grant in _run(_service(request).store.list_grants)]}

    @router.post("/grants", status_code=201)
    def provision(request: Request, payload: GrantRequest):
        grant, credential = _run(
            lambda: _service(request).store.provision(
                payload.folder_id,
                payload.name,
            )
        )
        # Owner-only response, returned once for local protected storage. It is
        # never an agent/MCP result and never appears in status/list responses.
        return {"grant": asdict(grant), "credential": credential}

    @router.delete("/grants/{grant_id}")
    def revoke(request: Request, grant_id: str):
        _run(lambda: _service(request).store.revoke(grant_id))
        return {"revoked": True}

    return router


def agent_rate_limiter() -> RateLimiter:
    # Avoid agent polling exhausting the desktop Reader's connection budget.
    return RateLimiter(requests_per_minute=120)
