"""Whole-chapter plans over an already-parsed import, with exact source slices.

Only explicit non-root sections at the selected heading level define chapter
boundaries. An implicit first chapter covers any preamble. No text patterns are
guessed and no paragraph or code block is split, normalized or duplicated.
Joining each part's canonical block text with two newlines reconstructs the
original canonical imported text exactly. File titles are article metadata only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace

from reader_core.agent_parts import MAX_METADATA_BYTES, PartPolicy
from reader_core.chapters import CHAPTER_KEY, MAX_CHAPTERS

from .errors import ImportInvalidError
from .models import ImportedDocument

MAX_IMPORT_PARTS = 100
MAX_PART_PREVIEW_BYTES = 1_048_576
_UUID = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True, slots=True)
class ImportChapter:
    number: int
    title: str
    start_block: int
    end_block: int


@dataclass(frozen=True, slots=True)
class ImportPart:
    number: int
    title: str
    first_chapter: int
    last_chapter: int
    chapter_start_title: str
    chapter_end_title: str
    start_block: int
    end_block: int
    codepoints: int
    utf16_units: int
    blocks: int
    text_sha256: str


@dataclass(frozen=True, slots=True)
class ImportPartPlan:
    plan_key: str
    max_characters: int
    heading_level: int
    chapters: tuple[ImportChapter, ...]
    parts: tuple[ImportPart, ...]
    issues: tuple[str, ...]

    @property
    def can_commit(self) -> bool:
        return bool(self.parts) and not self.issues

    def preview(self, preview_id: str) -> dict:
        result = {
            "preview_id": preview_id,
            "plan_key": self.plan_key,
            "max_characters": self.max_characters,
            "heading_level": self.heading_level,
            "chapter_count": len(self.chapters),
            "parts": [
                {
                    key: value
                    for key, value in asdict(part).items()
                    if key not in {"start_block", "end_block"}
                }
                for part in self.parts
            ],
            "can_commit": self.can_commit,
            "issues": list(self.issues),
        }
        if len(_json(result)) > MAX_PART_PREVIEW_BYTES:
            raise ImportInvalidError("The part preview exceeds its 1 MiB response bound.")
        return result


def plan_import_parts(
    imported: ImportedDocument,
    *,
    max_characters: int = 900_000,
    heading_level: int = 1,
) -> ImportPartPlan:
    policy = PartPolicy(max_characters=max_characters)
    if type(heading_level) is not int or not 1 <= heading_level <= 9:
        raise ImportInvalidError("Choose a chapter heading level between 1 and 9.")
    if not imported.blocks:
        raise ImportInvalidError("An empty import has no chapters to divide.")
    if tuple(block.ordinal for block in imported.blocks) != tuple(range(len(imported.blocks))):
        raise ImportInvalidError("Imported block ordering is invalid.")
    starts = {0: imported.title[:300] or "Chapter 1"}
    for section in imported.sections:
        if section.ordinal != 0 and section.level == heading_level:
            if 0 <= section.first_block_ordinal < len(imported.blocks):
                starts[section.first_block_ordinal] = (section.heading or "Chapter")[:300]
    boundaries = sorted(starts)
    chapters = tuple(
        ImportChapter(
            index + 1,
            starts[start],
            start,
            boundaries[index + 1] if index + 1 < len(boundaries) else len(imported.blocks),
        )
        for index, start in enumerate(boundaries)
    )
    plan_key = hashlib.sha256(
        _json(
            {
                "version": 1,
                "source": asdict(imported),
                "max_characters": max_characters,
                "heading_level": heading_level,
                "chapters": [asdict(chapter) for chapter in chapters],
            }
        )
    ).hexdigest()
    if any(len(_json(block.metadata)) > MAX_METADATA_BYTES for block in imported.blocks) or any(
        len(_json(section.metadata)) > MAX_METADATA_BYTES for section in imported.sections
    ):
        return ImportPartPlan(
            plan_key,
            max_characters,
            heading_level,
            chapters,
            (),
            (
                "A source block or section exceeds the 64 KiB metadata bound; "
                "simplify the source metadata before importing. No text was imported.",
            ),
        )
    if len(chapters) > MAX_CHAPTERS:
        return ImportPartPlan(
            plan_key,
            max_characters,
            heading_level,
            chapters,
            (),
            (
                f"The source has {len(chapters)} chapters; the limit is {MAX_CHAPTERS}. "
                "Choose a different heading level or smaller source files.",
            ),
        )
    prefix_cp = [0]
    prefix_utf16 = [0]
    for block in imported.blocks:
        prefix_cp.append(prefix_cp[-1] + len(block.text) + 2)
        prefix_utf16.append(prefix_utf16[-1] + len(block.text.encode("utf-16-le")) // 2 + 2)
    groups = []
    current = []
    for chapter in chapters:
        candidate = [*current, chapter]
        if _fits(imported, candidate, prefix_cp, prefix_utf16, policy):
            current = candidate
            continue
        if current:
            groups.append(current)
        if not _fits(imported, [chapter], prefix_cp, prefix_utf16, policy):
            return ImportPartPlan(
                plan_key,
                max_characters,
                heading_level,
                chapters,
                (),
                (
                    f"Chapter {chapter.number} ({chapter.title[:120]}) cannot fit as a whole "
                    f"chapter within {max_characters:,} characters, "
                    f"{policy.max_blocks:,} blocks or chapter "
                    "metadata bounds. Choose a finer heading level, raise the part limit, "
                    "or divide the source explicitly; no text was imported.",
                ),
            )
        current = [chapter]
    if current:
        groups.append(current)
    if len(groups) > MAX_IMPORT_PARTS:
        return ImportPartPlan(
            plan_key,
            max_characters,
            heading_level,
            chapters,
            (),
            (
                f"The source requires more than {MAX_IMPORT_PARTS} parts; "
                "choose larger part limits "
                "or smaller source files.",
            ),
        )
    parts = []
    for index, group in enumerate(groups, 1):
        first, last = group[0], group[-1]
        title = (
            imported.title
            if len(groups) == 1
            else (
                f"{imported.title[:430]} - Part {index:02d} (Chapters {first.number}-{last.number})"
            )
        )
        text = "\n\n".join(
            block.text for block in imported.blocks[first.start_block : last.end_block]
        )
        parts.append(
            ImportPart(
                index,
                title,
                first.number,
                last.number,
                first.title,
                last.title,
                first.start_block,
                last.end_block,
                len(text),
                len(text.encode("utf-16-le")) // 2,
                last.end_block - first.start_block,
                hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
    return ImportPartPlan(plan_key, max_characters, heading_level, chapters, tuple(parts), ())


def slice_import_part(imported: ImportedDocument, part: ImportPart) -> ImportedDocument:
    """Retain section ancestors and all block metadata, reindexing only positions."""
    source_sections = {section.ordinal: section for section in imported.sections}
    wanted = {0}
    wanted.update(
        block.section_ordinal for block in imported.blocks[part.start_block : part.end_block]
    )
    wanted.update(
        section.ordinal
        for section in imported.sections
        if part.start_block <= section.first_block_ordinal < part.end_block
    )
    pending = list(wanted)
    while pending:
        ordinal = pending.pop()
        section = source_sections.get(ordinal)
        if section is None:
            raise ImportInvalidError("Imported block references a missing section.")
        parent = section.parent_ordinal
        if parent is not None and parent not in wanted:
            wanted.add(parent)
            pending.append(parent)
    selected = sorted(wanted)
    mapping = {old: new for new, old in enumerate(selected)}
    sections = tuple(
        replace(
            source_sections[ordinal],
            ordinal=mapping[ordinal],
            first_block_ordinal=max(
                0, source_sections[ordinal].first_block_ordinal - part.start_block
            ),
            parent_ordinal=(
                mapping[source_sections[ordinal].parent_ordinal]
                if source_sections[ordinal].parent_ordinal is not None
                else None
            ),
        )
        for ordinal in selected
    )
    blocks = tuple(
        replace(
            block,
            ordinal=index,
            section_ordinal=mapping[block.section_ordinal],
        )
        for index, block in enumerate(imported.blocks[part.start_block : part.end_block])
    )
    return replace(imported, title=part.title, sections=sections, blocks=blocks)


def _fits(imported, chapters, prefix_cp, prefix_utf16, policy):
    first, last = chapters[0], chapters[-1]
    cp = prefix_cp[last.end_block] - prefix_cp[first.start_block] - 2
    utf16 = prefix_utf16[last.end_block] - prefix_utf16[first.start_block] - 2
    if cp > policy.max_characters or utf16 > policy.max_characters:
        return False
    if last.end_block - first.start_block > policy.max_blocks:
        return False
    markers = [
        {"id": _UUID, "title": chapter.title[:300], "block_id": _UUID, "codepoint_offset": 0}
        for chapter in chapters
    ]
    # Reserve two marker snapshots plus ordinary edit fields. This protects the
    # initial structure, not arbitrary future edits/append payloads.
    if (
        len(_json({"chapters_before": markers, "chapters_after": markers})) + 1024
        > MAX_METADATA_BYTES
    ):
        return False
    metadata = {
        "import": {
            "format": imported.source_format,
            "importer_version": imported.importer_version,
            "warnings": [warning.to_metadata() for warning in imported.warnings],
            **dict(imported.metadata),
        },
        CHAPTER_KEY: markers,
    }
    return len(_json(metadata)) + 1024 <= MAX_METADATA_BYTES


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
