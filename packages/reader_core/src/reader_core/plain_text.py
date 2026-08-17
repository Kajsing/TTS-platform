from __future__ import annotations

import hashlib
import re
import uuid

from .errors import ReaderValidationError
from .models import BlockKind, ReaderBlock, ReaderSection

_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")


def build_plain_text_structure(
    *,
    document_id: str,
    title: str,
    text: str,
) -> tuple[tuple[ReaderSection, ...], tuple[ReaderBlock, ...]]:
    section_id = str(uuid.uuid4())
    raw_blocks = split_plain_text_paragraphs(text)
    blocks = tuple(
        ReaderBlock(
            id=str(uuid.uuid4()),
            document_id=document_id,
            section_id=section_id,
            ordinal=ordinal,
            kind=_classify_block(block_text, ordinal=ordinal),
            text=block_text,
            character_count=len(block_text),
            content_sha256=_sha256_text(block_text),
        )
        for ordinal, block_text in enumerate(raw_blocks)
    )
    section = ReaderSection(
        id=section_id,
        document_id=document_id,
        ordinal=0,
        level=1,
        heading=title,
        first_block_ordinal=0,
    )
    return (section,), blocks


def split_plain_text_paragraphs(text: str) -> tuple[str, ...]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ReaderValidationError("plain-text document text must not be empty")
    return tuple(
        part.strip() for part in _PARAGRAPH_BREAK.split(normalized) if part.strip()
    )


def _classify_block(text: str, *, ordinal: int) -> BlockKind:
    if "\n" not in text and len(text) <= 100 and not text.endswith((".", "!", "?", ";")):
        if ordinal == 0 or text.startswith("#") or text.endswith(":") or text.isupper():
            return BlockKind.HEADING
    return BlockKind.PARAGRAPH


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
