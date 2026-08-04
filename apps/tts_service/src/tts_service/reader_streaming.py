from __future__ import annotations

from dataclasses import dataclass

from reader_core import ReaderBlock, ReaderStaleCursorError, ReaderValidationError, SpeechRule
from speech_rules import RuleContext, RuleWarning, SpeechRuleEngine
from tts_core.text import ChunkPlanner, SentenceSegmenter, TextNormalizer

from .reader_offsets import ReaderOffsetError, python_offset_to_utf16, utf16_offset_to_python
from .reader_service import ReaderApplicationService


@dataclass(frozen=True, slots=True)
class ReaderStreamCursor:
    block_id: str
    block_ordinal: int
    character_offset: int
    content_revision: int
    segment_index: int | None = None

    def api_payload(self, block_text: str) -> dict[str, object]:
        return {
            "block_id": self.block_id,
            "block_ordinal": self.block_ordinal,
            "character_offset": python_offset_to_utf16(
                block_text,
                self.character_offset,
            ),
            "content_revision": self.content_revision,
            "segment_index": self.segment_index,
        }


@dataclass(frozen=True, slots=True)
class ReaderSourceSpan:
    block_id: str
    block_ordinal: int
    start_offset: int
    end_offset: int

    def api_payload(self, block_text: str) -> dict[str, object]:
        return {
            "block_id": self.block_id,
            "block_ordinal": self.block_ordinal,
            "start_offset": python_offset_to_utf16(block_text, self.start_offset),
            "end_offset": python_offset_to_utf16(block_text, self.end_offset),
        }


@dataclass(frozen=True, slots=True)
class ReaderSpeechFragment:
    spoken_text: str
    cursor_start: ReaderStreamCursor
    cursor_end: ReaderStreamCursor
    source_spans: tuple[ReaderSourceSpan, ...]
    section_id: str | None
    pause_ms_hint: int


@dataclass(frozen=True, slots=True)
class ReaderBlockSlice:
    block: ReaderBlock
    start_offset: int
    end_offset: int

    @property
    def text(self) -> str:
        return self.block.text[self.start_offset : self.end_offset]


@dataclass(frozen=True, slots=True)
class ReaderStreamWindow:
    document_id: str
    content_revision: int
    blocks: tuple[ReaderBlockSlice, ...]
    fragments: tuple[ReaderSpeechFragment, ...]
    start_cursor: ReaderStreamCursor
    generated_cursor: ReaderStreamCursor
    next_cursor: ReaderStreamCursor | None
    document_complete: bool
    source_character_count: int
    rule_warnings: tuple[RuleWarning, ...] = ()
    rules_version: int = 1

    def block_text(self, block_id: str) -> str:
        for block_slice in self.blocks:
            if block_slice.block.id == block_id:
                return block_slice.block.text
        raise ReaderValidationError("stream cursor references a block outside its window")


class ReaderSpeechCompiler:
    _SPOKEN_FENCE_LANGUAGES = frozenset({"plain", "plaintext", "prose", "text", "txt"})

    def __init__(
        self,
        normalizer: TextNormalizer,
        segmenter: SentenceSegmenter,
        chunk_planner: ChunkPlanner,
        rule_engine: SpeechRuleEngine | None = None,
        rules: tuple[SpeechRule, ...] = (),
        rule_context: RuleContext | None = None,
    ) -> None:
        self._normalizer = normalizer
        self._segmenter = segmenter
        self._chunk_planner = chunk_planner
        self._rule_engine = rule_engine
        self._rules = rules
        self._rule_context = rule_context or RuleContext()

    def compile_slices(
        self,
        block_slices: tuple[ReaderBlockSlice, ...],
        *,
        content_revision: int,
        language_hint: str | None,
    ) -> tuple[ReaderSpeechFragment, ...]:
        fragments, _ = self.compile_slices_with_warnings(
            block_slices,
            content_revision=content_revision,
            language_hint=language_hint,
        )
        return fragments

    def compile_slices_with_warnings(
        self,
        block_slices: tuple[ReaderBlockSlice, ...],
        *,
        content_revision: int,
        language_hint: str | None,
    ) -> tuple[tuple[ReaderSpeechFragment, ...], tuple[RuleWarning, ...]]:
        fragments: list[ReaderSpeechFragment] = []
        rule_warnings: list[RuleWarning] = []
        segment_index = 0
        for block_slice in block_slices:
            if not self._should_speak_block(block_slice.block):
                continue
            rule_result = (
                self._rule_engine.apply(
                    block_slice.text,
                    self._rules,
                    context=self._rule_context,
                )
                if self._rule_engine is not None and self._rules
                else None
            )
            prepared_text = rule_result.text if rule_result is not None else block_slice.text
            if rule_result is not None:
                rule_warnings.extend(rule_result.warnings)
            mapped = self._normalizer.normalize_with_mapping(
                prepared_text,
                language_hint=language_hint,
            )
            if not mapped.text:
                continue
            segments = self._segmenter.segment(
                mapped.text,
                language_hint=language_hint,
            )
            plan = self._chunk_planner.plan(segments)
            normalized_cursor = 0
            for chunk in plan.chunks:
                start, end = self._align_chunk(
                    mapped.text,
                    chunk.text,
                    normalized_cursor,
                )
                mapped_spans = mapped.source_spans[start:end]
                if rule_result is None:
                    original_spans = tuple(mapped_spans)
                else:
                    original_spans = tuple(
                        rule_result.source_spans[index]
                        for span in mapped_spans
                        for index in range(span.start_offset, span.end_offset)
                    )
                source_start = block_slice.start_offset + min(
                    span.start_offset for span in original_spans
                )
                source_end = block_slice.start_offset + max(
                    span.end_offset for span in original_spans
                )
                pause_hint = chunk.pause_ms_hint
                if rule_result is not None:
                    pause_hint = max(
                        [
                            pause_hint,
                            *(
                                pause.duration_ms
                                for pause in rule_result.pauses
                                if source_start - block_slice.start_offset
                                < pause.source_offset
                                <= source_end - block_slice.start_offset
                            ),
                        ]
                    )
                cursor_start = ReaderStreamCursor(
                    block_id=block_slice.block.id,
                    block_ordinal=block_slice.block.ordinal,
                    character_offset=source_start,
                    content_revision=content_revision,
                    segment_index=segment_index,
                )
                cursor_end = ReaderStreamCursor(
                    block_id=block_slice.block.id,
                    block_ordinal=block_slice.block.ordinal,
                    character_offset=source_end,
                    content_revision=content_revision,
                    segment_index=segment_index,
                )
                fragments.append(
                    ReaderSpeechFragment(
                        spoken_text=chunk.text,
                        cursor_start=cursor_start,
                        cursor_end=cursor_end,
                        source_spans=(
                            ReaderSourceSpan(
                                block_id=block_slice.block.id,
                                block_ordinal=block_slice.block.ordinal,
                                start_offset=source_start,
                                end_offset=source_end,
                            ),
                        ),
                        section_id=block_slice.block.section_id,
                        pause_ms_hint=pause_hint,
                    )
                )
                normalized_cursor = end
                segment_index += 1
        return tuple(fragments), tuple(rule_warnings)

    @classmethod
    def _should_speak_block(cls, block: ReaderBlock) -> bool:
        if block.kind.value == "separator":
            return False
        if block.kind.value != "code":
            return True
        fence_language = str(block.metadata.get("markdown_fence_language", "")).lower()
        if fence_language in cls._SPOKEN_FENCE_LANGUAGES:
            return True
        if fence_language:
            return False
        return cls._looks_like_legacy_notification(block.text)

    @staticmethod
    def _looks_like_legacy_notification(text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            return False
        header = lines[0]
        if not (header.startswith("[") and header.endswith("]")):
            return False
        header_text = header[1:-1]
        if not any(character.isalpha() for character in header_text):
            return False
        if header_text != header_text.upper():
            return False
        return any(line.endswith((".", ":", "!", "?")) for line in lines[1:])

    @staticmethod
    def _align_chunk(
        normalized_text: str,
        chunk_text: str,
        normalized_cursor: int,
    ) -> tuple[int, int]:
        """Align planner text while tolerating whitespace inserted between segments."""
        source_index = normalized_cursor
        chunk_index = 0
        while source_index < len(normalized_text) and normalized_text[source_index].isspace():
            source_index += 1
        while chunk_index < len(chunk_text) and chunk_text[chunk_index].isspace():
            chunk_index += 1
        start = source_index

        while chunk_index < len(chunk_text):
            if chunk_text[chunk_index].isspace():
                while chunk_index < len(chunk_text) and chunk_text[chunk_index].isspace():
                    chunk_index += 1
                while source_index < len(normalized_text) and normalized_text[
                    source_index
                ].isspace():
                    source_index += 1
                continue
            while source_index < len(normalized_text) and normalized_text[
                source_index
            ].isspace():
                source_index += 1
            if (
                source_index >= len(normalized_text)
                or normalized_text[source_index] != chunk_text[chunk_index]
            ):
                raise ReaderValidationError("speech chunk could not be mapped to source text")
            source_index += 1
            chunk_index += 1

        if source_index <= start:
            raise ReaderValidationError("speech chunk mapped to an empty source span")
        return start, source_index


class ReaderStreamWindowBuilder:
    def __init__(
        self,
        service: ReaderApplicationService,
        compiler: ReaderSpeechCompiler,
    ) -> None:
        self._service = service
        self._compiler = compiler

    def build(
        self,
        document_id: str,
        *,
        block_ordinal: int,
        character_offset_utf16: int,
        block_id: str | None,
        content_revision: int | None,
        max_blocks: int,
        max_source_characters: int,
        language_hint: str | None = None,
        rules_version: int = 1,
    ) -> ReaderStreamWindow:
        document = self._service.get_document(document_id)
        if content_revision is not None and content_revision != document.content_revision:
            raise ReaderStaleCursorError("stream cursor content revision is stale")
        if block_ordinal < 0 or block_ordinal >= document.total_blocks:
            raise ReaderValidationError("stream block ordinal is outside the document")
        if max_blocks <= 0 or max_source_characters <= 0:
            raise ReaderValidationError("stream window limits must be positive")

        fetched = self._service.list_blocks(
            document_id,
            after_ordinal=block_ordinal - 1,
            limit=max_blocks + 2,
        )
        if not fetched or fetched[0].ordinal != block_ordinal:
            raise ReaderStaleCursorError("stream start block no longer exists")
        requested_first = fetched[0]
        if block_id is not None and requested_first.id != block_id:
            raise ReaderStaleCursorError("stream block id does not match its ordinal")
        try:
            first_offset = utf16_offset_to_python(
                requested_first.text,
                character_offset_utf16,
            )
        except ReaderOffsetError as error:
            raise ReaderValidationError("stream cursor UTF-16 offset is invalid") from error

        window_candidates = fetched
        if (
            first_offset == len(requested_first.text)
            and requested_first.ordinal < document.total_blocks - 1
        ):
            window_candidates = fetched[1:]
            first_offset = 0
        first = window_candidates[0]

        remaining_characters = max_source_characters
        slices: list[ReaderBlockSlice] = []
        next_cursor: ReaderStreamCursor | None = None
        generated_cursor = ReaderStreamCursor(
            first.id,
            first.ordinal,
            first_offset,
            document.content_revision,
        )
        for index, block in enumerate(window_candidates[:max_blocks]):
            start_offset = first_offset if index == 0 else 0
            if start_offset == len(block.text) and block.ordinal < document.total_blocks - 1:
                generated_cursor = ReaderStreamCursor(
                    block.id,
                    block.ordinal,
                    start_offset,
                    document.content_revision,
                )
                continue
            end_offset = min(len(block.text), start_offset + remaining_characters)
            slices.append(ReaderBlockSlice(block, start_offset, end_offset))
            remaining_characters -= end_offset - start_offset
            generated_cursor = ReaderStreamCursor(
                block.id,
                block.ordinal,
                end_offset,
                document.content_revision,
            )
            if end_offset < len(block.text):
                next_cursor = generated_cursor
                break
            if remaining_characters == 0 and block.ordinal < document.total_blocks - 1:
                next_cursor = self._next_block_cursor(
                    window_candidates,
                    index,
                    document.content_revision,
                )
                break
        else:
            last = window_candidates[min(len(window_candidates), max_blocks) - 1]
            if last.ordinal < document.total_blocks - 1:
                next_cursor = self._next_block_cursor(
                    window_candidates,
                    min(len(window_candidates), max_blocks) - 1,
                    document.content_revision,
                )

        block_slices = tuple(slices)
        if not block_slices:
            raise ReaderValidationError("stream window contains no readable blocks")
        fragments, rule_warnings = self._compiler.compile_slices_with_warnings(
            block_slices,
            content_revision=document.content_revision,
            language_hint=language_hint or document.language_hint,
        )
        first_slice = block_slices[0]
        start_cursor = ReaderStreamCursor(
            first_slice.block.id,
            first_slice.block.ordinal,
            first_slice.start_offset,
            document.content_revision,
        )
        return ReaderStreamWindow(
            document_id=document.id,
            content_revision=document.content_revision,
            blocks=block_slices,
            fragments=fragments,
            start_cursor=start_cursor,
            generated_cursor=generated_cursor,
            next_cursor=next_cursor,
            document_complete=next_cursor is None,
            source_character_count=sum(
                block_slice.end_offset - block_slice.start_offset
                for block_slice in block_slices
            ),
            rule_warnings=rule_warnings,
            rules_version=rules_version,
        )

    @staticmethod
    def _next_block_cursor(
        fetched: tuple[ReaderBlock, ...],
        current_index: int,
        content_revision: int,
    ) -> ReaderStreamCursor:
        next_index = current_index + 1
        if next_index >= len(fetched):
            raise ReaderValidationError("bounded block query did not return a continuation block")
        block = fetched[next_index]
        return ReaderStreamCursor(
            block.id,
            block.ordinal,
            0,
            content_revision,
        )
