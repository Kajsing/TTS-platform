from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import ImportInvalidError


@dataclass(frozen=True, slots=True)
class ImportLimits:
    max_file_bytes: int = 52_428_800
    max_expanded_archive_bytes: int = 209_715_200
    max_archive_members: int = 10_000
    max_document_characters: int = 10_000_000
    max_blocks: int = 250_000
    timeout_seconds: int = 60

    def __post_init__(self) -> None:
        if (
            min(
                self.max_file_bytes,
                self.max_expanded_archive_bytes,
                self.max_archive_members,
                self.max_document_characters,
                self.max_blocks,
                self.timeout_seconds,
            )
            <= 0
        ):
            raise ImportInvalidError("Document import limits must be positive.")


@dataclass(frozen=True, slots=True)
class ImportSource:
    filename: str
    content_type: str | None
    data: bytes


@dataclass(frozen=True, slots=True)
class ImportOptions:
    title: str | None = None
    language_hint: str | None = None


@dataclass(frozen=True, slots=True)
class ImportWarning:
    code: str
    message: str
    count: int = 1

    def to_metadata(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "count": self.count}


@dataclass(frozen=True, slots=True)
class ImportedSection:
    ordinal: int
    level: int
    heading: str | None
    first_block_ordinal: int
    parent_ordinal: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImportedBlock:
    ordinal: int
    kind: str
    text: str
    section_ordinal: int
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImportedDocument:
    title: str
    source_format: str
    source_sha256: str
    source_name: str
    importer_version: str
    sections: tuple[ImportedSection, ...]
    blocks: tuple[ImportedBlock, ...]
    warnings: tuple[ImportWarning, ...] = ()
    language_hint: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def total_characters(self) -> int:
        return sum(len(block.text) for block in self.blocks)
