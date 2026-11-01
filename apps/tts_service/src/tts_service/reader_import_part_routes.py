"""Additive owner routes for planning and committing cached upload parts."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field


class ImportPartPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_characters: int = Field(default=900_000, ge=1, le=1_000_000)
    heading_level: int = Field(default=1, ge=1, le=9)


class ImportPartsCommitRequest(ImportPartPolicyRequest):
    plan_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    allow_duplicate: bool = False
    folder_id: str | None = Field(default=None, min_length=1, max_length=80)


def build_reader_import_part_router() -> APIRouter:
    # Import here so the existing owner router can include this one without a
    # module initialization cycle. All normal owner middleware still applies.
    from .reader_routes import _privacy_tokens, _run_import_async, _service
    from .reader_schemas import ReaderDocumentResponse

    router = APIRouter()

    @router.post("/imports/{preview_id}/parts-preview")
    async def preview_parts(request: Request, preview_id: str, payload: ImportPartPolicyRequest):
        service = _service(request)
        return await _run_import_async(
            lambda _: service.preview_import_parts(
                preview_id,
                max_characters=payload.max_characters,
                heading_level=payload.heading_level,
            )
        )

    @router.post("/imports/{preview_id}/parts-commit", status_code=status.HTTP_201_CREATED)
    async def commit_parts(request: Request, preview_id: str, payload: ImportPartsCommitRequest):
        service = _service(request)
        tokens = _privacy_tokens(request)
        documents = await _run_import_async(
            lambda _: service.commit_import_parts(
                preview_id,
                plan_key=payload.plan_key,
                max_characters=payload.max_characters,
                heading_level=payload.heading_level,
                allow_duplicate=payload.allow_duplicate,
                folder_id=payload.folder_id,
                privacy_tokens=tokens,
            )
        )
        return {
            "documents": [ReaderDocumentResponse.from_domain(document) for document in documents]
        }

    return router
