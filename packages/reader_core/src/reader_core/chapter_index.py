"""Chapter navigation anchors retain canonical Unicode codepoint offsets."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ReaderError


class ChapterIndexConflictError(ReaderError):
    """Persisted chapter metadata cannot safely describe the current article."""


@dataclass(frozen=True, slots=True)
class ChapterAnchor:
    id: str
    title: str
    block_id: str
    block_ordinal: int
    codepoint_offset: int


@dataclass(frozen=True, slots=True)
class ChapterIndex:
    document_id: str
    content_revision: int
    chapters: tuple[ChapterAnchor, ...]


@dataclass(frozen=True, slots=True)
class ChapterDocumentAccess:
    folder_id: str | None
    content_revision: int
    deleted: bool
