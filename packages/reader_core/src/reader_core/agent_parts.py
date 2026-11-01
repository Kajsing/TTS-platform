"""Deterministic, bounded whole-chapter plans for managed Reader agent imports.

The article title and optional introduction form a spoken wrapper on every part.
Each chapter's supplied text must already include any spoken chapter heading,
just as with M1 delivery. Plans contain metadata and hashes, never source bodies.
Metadata preflight deliberately uses upper-bound UUID/offset widths; repository
delivery must still validate actual document state inside its write transaction.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Sequence

from .agent_access import MAX_AGENT_TEXT, ChapterDelivery, bounded_text
from .chapters import MAX_CHAPTERS
from .errors import ReaderValidationError
from .plain_text import split_plain_text_paragraphs

MAX_PLAN_CHAPTERS = 100
MAX_PLAN_SOURCE_BYTES = 4 * 1024 * 1024
MAX_PART_CHARACTERS = 1_000_000
MAX_PART_BLOCKS = 20_000
MAX_METADATA_BYTES = 65_536
_UUID = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True)
class PartPolicy:
    max_characters: int = 900_000
    max_blocks: int = MAX_PART_BLOCKS

    def __post_init__(self) -> None:
        if (
            type(self.max_characters) is not int
            or not 1 <= self.max_characters <= MAX_PART_CHARACTERS
        ):
            raise ReaderValidationError("Part character limit must be between 1 and 1000000")
        if type(self.max_blocks) is not int or not 1 <= self.max_blocks <= MAX_PART_BLOCKS:
            raise ReaderValidationError("Part block limit must be between 1 and 20000")


DEFAULT_PART_POLICY = PartPolicy()


@dataclass(frozen=True)
class ChapterSpec:
    delivery: ChapterDelivery


@dataclass(frozen=True)
class PartState:
    codepoints: int
    utf16_units: int
    blocks: int
    chapter_titles: tuple[str, ...]


@dataclass(frozen=True)
class NextPartPlan:
    new_part: bool
    state: PartState
    append_metadata_bytes: int


@dataclass(frozen=True)
class PartPlan:
    number: int
    title: str
    chapter_keys: tuple[str, ...]
    codepoints: int
    utf16_units: int
    blocks: int
    append_metadata_bytes: int
    text_sha256: str


def normalize_text(text: str) -> str:
    return "\n\n".join(split_plain_text_paragraphs(text))


def normalized_wrapper(title: str, intro: str = "") -> str:
    bounded_text(title, "title", 470)
    bounded_text(intro, "intro", MAX_AGENT_TEXT, empty=True)
    text = normalize_text(title + ("\n\n" + intro if intro.strip() else ""))
    if len(text) > MAX_AGENT_TEXT:
        raise ReaderValidationError("Part wrapper exceeds the per-write text limit")
    _utf16_units(text)
    return text


def wrapper_state(wrapper: str) -> PartState:
    text = normalize_text(wrapper)
    bounded_text(text, "wrapper", MAX_AGENT_TEXT)
    return PartState(
        len(text), _utf16_units(text), len(split_plain_text_paragraphs(text)), ("Chapter 1",)
    )


def estimated_append_metadata_bytes(
    state: PartState, chapter: ChapterDelivery, *, policy: PartPolicy = DEFAULT_PART_POLICY
) -> int:
    """Upper bound for managed-append edit JSON, including both marker snapshots.

    Managed parts have no arbitrary custom metadata. UUIDs are fixed-width;
    ordinals and intra-append offsets use the widest permitted scalar values.
    UTF-8 and JSON escaping are measured with the repository's encoding rules.
    """
    paragraphs = split_plain_text_paragraphs(chapter.text)
    before = [_marker(title, policy.max_characters) for title in state.chapter_titles]
    after = [*before, _marker(chapter.title[:300].strip(), 0)]
    metadata = {
        "section_id": _UUID,
        "ordinal": policy.max_blocks - 1,
        "kind": "paragraph",
        "blocks": [
            {
                "id": _UUID,
                "ordinal": policy.max_blocks - 1,
                "section_id": _UUID,
                "kind": "paragraph",
                "text_start": MAX_AGENT_TEXT,
                "text_length": len(paragraph),
            }
            for paragraph in paragraphs
        ],
        "new_chapter": True,
        "chapter_title": chapter.title[:300],
        "chapters_before": before,
        "chapters_after": after,
    }
    return _json_bytes(metadata)


def plan_next_part(
    state: PartState,
    chapter: ChapterDelivery,
    *,
    wrapper: str,
    policy: PartPolicy = DEFAULT_PART_POLICY,
) -> NextPartPlan:
    _validate_state(state, policy)
    candidate, metadata_bytes = _append(state, chapter, policy)
    if _fits(candidate, metadata_bytes, policy):
        return NextPartPlan(False, candidate, metadata_bytes)
    fresh = wrapper_state(wrapper)
    _validate_state(fresh, policy)
    candidate, metadata_bytes = _append(fresh, chapter, policy)
    if not _fits(candidate, metadata_bytes, policy):
        raise ReaderValidationError(
            "A complete chapter plus wrapper exceeds a part character, block, "
            "chapter or metadata limit"
        )
    return NextPartPlan(True, candidate, metadata_bytes)


def plan_parts(
    title: str,
    intro: str,
    chapters: Sequence[ChapterDelivery | ChapterSpec],
    policy: PartPolicy = DEFAULT_PART_POLICY,
) -> tuple[PartPlan, ...]:
    if not 1 <= len(chapters) <= MAX_PLAN_CHAPTERS:
        raise ReaderValidationError("A part preview requires 1 to 100 chapters")
    deliveries = tuple(
        item.delivery if isinstance(item, ChapterSpec) else item for item in chapters
    )
    if any(not isinstance(item, ChapterDelivery) for item in deliveries):
        raise ReaderValidationError("Part preview chapters must be ChapterDelivery values")
    if len({item.chapter_key for item in deliveries}) != len(deliveries):
        raise ReaderValidationError("Part preview chapter identities must be unique")
    if len({item.retry_key for item in deliveries}) != len(deliveries):
        raise ReaderValidationError("Part preview retry identities must be unique")
    if len({item.story_key for item in deliveries}) != 1:
        raise ReaderValidationError("Part preview must contain one story identity")
    wrapper = normalized_wrapper(title, intro)
    try:
        source_bytes = len(wrapper.encode("utf-8")) + sum(
            len(item.text.encode("utf-8")) for item in deliveries
        )
    except UnicodeError:
        raise ReaderValidationError("Part text must contain valid Unicode") from None
    if source_bytes > MAX_PLAN_SOURCE_BYTES:
        raise ReaderValidationError("Part preview source text exceeds 4 MiB")
    initial = wrapper_state(wrapper)
    _validate_state(initial, policy)
    state = initial
    keys: list[str] = []
    digest = hashlib.sha256(wrapper.encode("utf-8"))
    largest_metadata = 0
    result: list[PartPlan] = []

    def finish() -> None:
        result.append(
            PartPlan(
                len(result) + 1,
                f"{title} - Part {len(result) + 1:02d}",
                tuple(keys),
                state.codepoints,
                state.utf16_units,
                state.blocks,
                largest_metadata,
                digest.hexdigest(),
            )
        )

    for chapter in deliveries:
        next_part = plan_next_part(state, chapter, wrapper=wrapper, policy=policy)
        if next_part.new_part:
            # The single-chapter fit check precedes this branch, so no empty
            # part can be emitted and no chapter can be silently truncated.
            if keys:
                finish()
            keys = []
            digest = hashlib.sha256(wrapper.encode("utf-8"))
            largest_metadata = 0
        state = next_part.state
        keys.append(chapter.chapter_key)
        largest_metadata = max(largest_metadata, next_part.append_metadata_bytes)
        digest.update(b"\n\n")
        digest.update(normalize_text(chapter.text).encode("utf-8"))
    finish()
    return tuple(result)


def _append(
    state: PartState, chapter: ChapterDelivery, policy: PartPolicy
) -> tuple[PartState, int]:
    text = normalize_text(chapter.text)
    title = chapter.title[:300].strip()
    if not title:
        raise ReaderValidationError("The first 300 chapter-title characters must include text")
    paragraphs = split_plain_text_paragraphs(text)
    return (
        PartState(
            state.codepoints + 2 + len(text),
            state.utf16_units + 2 + _utf16_units(text),
            state.blocks + len(paragraphs),
            (*state.chapter_titles, title),
        ),
        estimated_append_metadata_bytes(state, chapter, policy=policy),
    )


def _fits(state: PartState, metadata_bytes: int, policy: PartPolicy) -> bool:
    return (
        state.codepoints <= policy.max_characters
        and state.utf16_units <= policy.max_characters
        and state.blocks <= policy.max_blocks
        and len(state.chapter_titles) <= MAX_CHAPTERS
        and metadata_bytes <= MAX_METADATA_BYTES
        and _json_bytes(
            {
                "chapter_markers_v1": [
                    _marker(title, policy.max_characters) for title in state.chapter_titles
                ]
            }
        )
        <= MAX_METADATA_BYTES
    )


def _validate_state(state: PartState, policy: PartPolicy) -> None:
    if (
        any(type(value) is not int for value in (state.codepoints, state.utf16_units, state.blocks))
        or not 1 <= state.codepoints <= state.utf16_units <= policy.max_characters
        or not 1 <= state.blocks <= policy.max_blocks
        or not 1 <= len(state.chapter_titles) <= MAX_CHAPTERS
        or any(
            not isinstance(title, str) or not 1 <= len(title) <= 300
            for title in state.chapter_titles
        )
    ):
        raise ReaderValidationError("Part state exceeds its policy or contains invalid counters")


def _marker(title: str, offset: int) -> dict[str, object]:
    return {"id": _UUID, "title": title, "block_id": _UUID, "codepoint_offset": offset}


def _json_bytes(value: object) -> int:
    try:
        return len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        )
    except UnicodeError:
        raise ReaderValidationError("Part metadata must contain valid Unicode") from None


def _utf16_units(text: str) -> int:
    try:
        return len(text.encode("utf-16-le")) // 2
    except UnicodeError:
        raise ReaderValidationError("Part text must contain valid Unicode") from None
