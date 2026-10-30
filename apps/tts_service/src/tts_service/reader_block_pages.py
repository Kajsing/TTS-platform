"""Exact UTF-8 response accounting for complete, preflight-bounded source blocks."""

from __future__ import annotations

from fastapi import Response
from reader_core import MAX_BLOCK_PAGE_CHARACTERS, BoundedReaderBlockPage

from .reader_errors import reader_api_error
from .reader_schemas import ReaderBlockResponse

_PREFIX = b'{"blocks":['


def _suffix(next_after_ordinal: int | None) -> bytes:
    cursor = b"null" if next_after_ordinal is None else str(next_after_ordinal).encode("ascii")
    return b'],"next_after_ordinal":' + cursor + b"}"


def bounded_block_page_response(page: BoundedReaderBlockPage, max_bytes: int) -> Response:
    chunks: list[bytes] = []
    used = len(_PREFIX)
    next_after = page.next_after_ordinal
    for index, block in enumerate(page.blocks):
        encoded = ReaderBlockResponse.from_domain(block).model_dump_json().encode("utf-8")
        candidate_next = (
            block.ordinal
            if index < len(page.blocks) - 1 or page.next_after_ordinal is not None
            else None
        )
        candidate_size = used + (1 if chunks else 0) + len(encoded) + len(_suffix(candidate_next))
        if candidate_size > max_bytes:
            if not chunks:
                raise reader_api_error(
                    "reader_block_too_large",
                    status_code=413,
                    message=(
                        "This source block exceeds the reading page size limits. "
                        "Its text has been kept unchanged. Split it into smaller blocks "
                        "in the source, then import it again."
                    ),
                    details={
                        "block_ordinal": block.ordinal,
                        "block_characters": block.character_count,
                        "max_block_characters": MAX_BLOCK_PAGE_CHARACTERS,
                        "block_response_bytes": candidate_size,
                        "max_block_page_bytes": max_bytes,
                    },
                )
            next_after = page.blocks[index - 1].ordinal
            break
        used += (1 if chunks else 0) + len(encoded)
        chunks.append(encoded)
        next_after = candidate_next
    payload = _PREFIX + b",".join(chunks) + _suffix(next_after)
    if len(payload) > max_bytes:
        # A positive but tiny operator setting may not fit even an empty page.
        raise reader_api_error(
            "reader_block_too_large",
            status_code=413,
            message="The configured reading page byte limit cannot fit a response envelope.",
            details={"max_block_page_bytes": max_bytes},
        )
    return Response(content=payload, media_type="application/json")
