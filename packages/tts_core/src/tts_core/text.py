from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ChunkPlan, PlannedChunk

DEFAULT_EN_ABBREVIATIONS = {
    "dr.",
    "mr.",
    "mrs.",
    "ms.",
    "prof.",
    "sr.",
    "jr.",
    "st.",
    "etc.",
    "e.g.",
    "i.e.",
    "vs.",
}


DEFAULT_DA_ABBREVIATIONS = {
    "bl.a.",
    "ca.",
    "dvs.",
    "fx.",
    "mfl.",
    "osv.",
}


@dataclass(frozen=True, slots=True)
class PreparedText:
    original_text: str
    normalized_text: str
    segments: tuple[str, ...]


class TextNormalizer:
    def __init__(self) -> None:
        self._abbreviation_rules = {
            "en": {
                "Dr.": "Doctor",
                "Mr.": "Mister",
                "Mrs.": "Missus",
                "Ms.": "Miss",
                "Prof.": "Professor",
            },
            "da": {
                "fx.": "for eksempel",
                "ca.": "cirka",
            },
        }
        self._symbol_rules = {
            "en": {
                "&": " and ",
                "%": " percent ",
            },
            "da": {
                "&": " og ",
                "%": " procent ",
            },
        }

    def normalize(self, text: str, *, language_hint: str | None = None) -> str:
        language = (language_hint or "en").lower()
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"\n{2,}", "\n\n", normalized)
        normalized = normalized.replace("\n", " ")

        for symbol, replacement in self._symbol_rules.get(language, {}).items():
            normalized = normalized.replace(symbol, replacement)

        for source, replacement in self._abbreviation_rules.get(language, {}).items():
            normalized = normalized.replace(source, replacement)

        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
        return normalized.strip()


class SentenceSegmenter:
    def __init__(self, *, max_chars_per_segment: int = 280) -> None:
        self.max_chars_per_segment = max_chars_per_segment

    def segment(self, text: str, *, language_hint: str | None = None) -> list[str]:
        working_text = text.strip()
        if not working_text:
            return []

        abbreviations = self._abbreviations_for(language_hint)
        segments: list[str] = []
        start = 0
        length = len(working_text)

        for index, character in enumerate(working_text):
            if character not in ".!?;:":
                continue
            if character == "." and self._is_abbreviation(working_text, index, abbreviations):
                continue
            if self._is_decimal_separator(working_text, index):
                continue

            next_index = self._skip_whitespace(working_text, index + 1)
            if next_index == length or self._looks_like_sentence_start(working_text, next_index):
                candidate = working_text[start : index + 1].strip()
                if candidate:
                    segments.extend(self._split_long_segment(candidate))
                start = next_index

        tail = working_text[start:].strip()
        if tail:
            segments.extend(self._split_long_segment(tail))
        return segments

    def _split_long_segment(self, text: str) -> list[str]:
        if len(text) <= self.max_chars_per_segment:
            return [text]

        splits: list[str] = []
        remaining = text
        while len(remaining) > self.max_chars_per_segment:
            window = remaining[: self.max_chars_per_segment + 1]
            split_at = max(window.rfind(","), window.rfind(" "))
            if split_at <= 0:
                split_at = self.max_chars_per_segment
            candidate = remaining[:split_at].strip()
            if candidate:
                splits.append(candidate)
            remaining = remaining[split_at:].strip()

        if remaining:
            splits.append(remaining)
        return splits

    def _abbreviations_for(self, language_hint: str | None) -> set[str]:
        language = (language_hint or "en").lower()
        if language == "da":
            return DEFAULT_DA_ABBREVIATIONS
        return DEFAULT_EN_ABBREVIATIONS

    def _is_abbreviation(
        self,
        text: str,
        period_index: int,
        abbreviations: set[str],
    ) -> bool:
        token_start = period_index
        while token_start > 0 and not text[token_start - 1].isspace():
            token_start -= 1
        token = text[token_start : period_index + 1].lower()
        return token in abbreviations

    def _is_decimal_separator(self, text: str, index: int) -> bool:
        if text[index] != ".":
            return False
        previous_is_digit = index > 0 and text[index - 1].isdigit()
        next_is_digit = index + 1 < len(text) and text[index + 1].isdigit()
        return previous_is_digit and next_is_digit

    def _skip_whitespace(self, text: str, start_index: int) -> int:
        index = start_index
        while index < len(text) and text[index].isspace():
            index += 1
        return index

    def _looks_like_sentence_start(self, text: str, index: int) -> bool:
        if index >= len(text):
            return True
        if text[index].isupper() or text[index].isdigit():
            return True
        return text[index] in {'"', "'", "(", "["}


class ChunkPlanner:
    def __init__(self, *, max_chars_per_chunk: int = 280) -> None:
        self.max_chars_per_chunk = max_chars_per_chunk

    def plan(
        self,
        segments: tuple[str, ...] | list[str],
        *,
        sentence_pause_ms: int = 120,
        comma_pause_ms: int = 60,
    ) -> ChunkPlan:
        normalized_segments = tuple(segment.strip() for segment in segments if segment.strip())
        if not normalized_segments:
            return ChunkPlan(chunks=(), source_segments=())

        chunks: list[PlannedChunk] = []
        current_parts: list[str] = []
        chunk_index = 0

        for segment in normalized_segments:
            candidate_parts = current_parts + [segment]
            candidate_text = " ".join(candidate_parts).strip()
            if (
                current_parts
                and len(candidate_text) > self.max_chars_per_chunk
            ):
                chunk_text = " ".join(current_parts).strip()
                chunks.append(
                    PlannedChunk(
                        index=chunk_index,
                        text=chunk_text,
                        char_count=len(chunk_text),
                        pause_ms_hint=self._pause_hint_for(
                            chunk_text,
                            sentence_pause_ms=sentence_pause_ms,
                            comma_pause_ms=comma_pause_ms,
                        ),
                    )
                )
                chunk_index += 1
                current_parts = [segment]
            else:
                current_parts = candidate_parts

        if current_parts:
            chunk_text = " ".join(current_parts).strip()
            chunks.append(
                PlannedChunk(
                    index=chunk_index,
                    text=chunk_text,
                    char_count=len(chunk_text),
                    pause_ms_hint=self._pause_hint_for(
                        chunk_text,
                        sentence_pause_ms=sentence_pause_ms,
                        comma_pause_ms=comma_pause_ms,
                    ),
                )
            )

        return ChunkPlan(
            chunks=tuple(chunks),
            source_segments=normalized_segments,
        )

    def _pause_hint_for(
        self,
        text: str,
        *,
        sentence_pause_ms: int,
        comma_pause_ms: int,
    ) -> int:
        if text.endswith((".", "!", "?", ";", ":")):
            return sentence_pause_ms
        if text.endswith(","):
            return comma_pause_ms
        return 0


@dataclass(slots=True)
class TextPipeline:
    normalizer: TextNormalizer
    segmenter: SentenceSegmenter

    def process(
        self,
        text: str,
        *,
        language_hint: str | None = None,
        normalize_text: bool = True,
    ) -> PreparedText:
        normalized_text = text.strip()
        if normalize_text:
            normalized_text = self.normalizer.normalize(
                text,
                language_hint=language_hint,
            )

        segments = tuple(
            self.segmenter.segment(
                normalized_text,
                language_hint=language_hint,
            )
        )
        if not segments and normalized_text:
            segments = (normalized_text,)
        return PreparedText(
            original_text=text,
            normalized_text=normalized_text,
            segments=segments,
        )
