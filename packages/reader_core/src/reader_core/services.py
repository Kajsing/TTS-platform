from __future__ import annotations

import hashlib
import uuid

from .errors import ReaderValidationError
from .models import (
    DocumentState,
    ReaderDocument,
    ReaderDocumentBundle,
    SourceType,
    utc_now,
)
from .plain_text import build_plain_text_structure
from .repositories import ReaderRepository


class ReaderLibrary:
    def __init__(self, repository: ReaderRepository) -> None:
        self._repository = repository

    def create_plain_text_document(
        self,
        *,
        title: str,
        text: str,
        source_type: SourceType = SourceType.PLAIN_TEXT,
        language_hint: str | None = None,
    ) -> ReaderDocument:
        if source_type not in {
            SourceType.PLAIN_TEXT,
            SourceType.CLIPBOARD,
            SourceType.SELECTION,
            SourceType.TEXT_FILE,
        }:
            raise ReaderValidationError(
                "plain-text creation requires an editable text source type"
            )
        document_id = str(uuid.uuid4())
        now = utc_now()
        sections, blocks = build_plain_text_structure(
            document_id=document_id,
            title=title,
            text=text,
        )
        document = ReaderDocument(
            id=document_id,
            title=title,
            source_type=source_type,
            state=DocumentState.INBOX,
            created_at=now,
            updated_at=now,
            imported_at=now,
            source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            language_hint=language_hint,
            total_sections=len(sections),
            total_blocks=len(blocks),
            total_characters=sum(block.character_count for block in blocks),
        )
        bundle = ReaderDocumentBundle(
            document=document,
            sections=sections,
            blocks=blocks,
        )
        return self._repository.create_document(bundle)
