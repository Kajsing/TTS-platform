from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Mapping

import regex
from reader_core import RuleScope, RuleStage, RuleType, SpeechRule

from .errors import SpeechRuleValidationError


@dataclass(frozen=True, slots=True)
class RuleEngineLimits:
    default_regex_timeout_ms: int = 25
    max_regex_pattern_chars: int = 2_048
    max_replacement_chars: int = 4_096
    max_rule_time_per_block_ms: int = 250
    max_result_chars: int = 128_000
    max_matches_per_rule: int = 10_000

    def __post_init__(self) -> None:
        if min(
            self.default_regex_timeout_ms,
            self.max_regex_pattern_chars,
            self.max_replacement_chars,
            self.max_rule_time_per_block_ms,
            self.max_result_chars,
            self.max_matches_per_rule,
        ) <= 0:
            raise SpeechRuleValidationError("Speech-rule limits must be positive.")


@dataclass(frozen=True, slots=True)
class RuleContext:
    language: str | None = None
    engine: str | None = None
    voice: str | None = None
    document_id: str | None = None


@dataclass(frozen=True, slots=True)
class RuleSourceSpan:
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class RuleTraceEntry:
    rule_id: str
    rule_type: RuleType
    start_offset: int
    end_offset: int
    replacement_length: int


@dataclass(frozen=True, slots=True)
class RuleWarning:
    code: str
    message: str
    rule_id: str | None = None


@dataclass(frozen=True, slots=True)
class RulePause:
    source_offset: int
    duration_ms: int
    rule_id: str


@dataclass(frozen=True, slots=True)
class RuleApplication:
    text: str
    source_spans: tuple[RuleSourceSpan, ...]
    trace: tuple[RuleTraceEntry, ...]
    warnings: tuple[RuleWarning, ...]
    pauses: tuple[RulePause, ...]
    phoneme_annotations: tuple[Mapping[str, object], ...]
    elapsed_ms: float


_STAGE_ORDER = {
    RuleStage.CLEANUP: 0,
    RuleStage.PRONUNCIATION: 1,
    RuleStage.MARKUP: 2,
}
_SCOPE_ORDER = {
    RuleScope.SYSTEM: 0,
    RuleScope.GLOBAL: 1,
    RuleScope.LANGUAGE: 2,
    RuleScope.VOICE_ENGINE: 3,
    RuleScope.DOCUMENT: 4,
}


def order_rules(
    rules: tuple[SpeechRule, ...],
    rule_set_scopes: Mapping[str, RuleScope],
) -> tuple[SpeechRule, ...]:
    return tuple(
        sorted(
            rules,
            key=lambda rule: (
                _SCOPE_ORDER[rule_set_scopes[rule.rule_set_id]],
                _STAGE_ORDER[rule.stage],
                rule.priority,
                rule.created_at,
                rule.id,
            ),
        )
    )


class SpeechRuleEngine:
    def __init__(self, limits: RuleEngineLimits | None = None) -> None:
        self.limits = limits or RuleEngineLimits()

    def validate_rule(self, rule: SpeechRule, *, timeout_ms: int | None = None) -> None:
        if len(rule.pattern) > self.limits.max_regex_pattern_chars:
            raise SpeechRuleValidationError("Rule pattern exceeds the configured limit.")
        if len(rule.replacement) > self.limits.max_replacement_chars:
            raise SpeechRuleValidationError("Rule replacement exceeds the configured limit.")
        if rule.rule_type is RuleType.PAUSE:
            try:
                pause_ms = int(rule.replacement)
            except ValueError as exc:
                raise SpeechRuleValidationError(
                    "Pause-rule replacement must contain milliseconds."
                ) from exc
            if not 0 <= pause_ms <= 10_000:
                raise SpeechRuleValidationError("Pause duration must be between 0 and 10000 ms.")
        pattern = self._pattern_for(rule)
        try:
            compiled = regex.compile(pattern, self._flags_for(rule) | regex.VERSION1)
            validation_timeout_ms = min(
                rule.regex_timeout_ms,
                timeout_ms if timeout_ms is not None else self.limits.default_regex_timeout_ms,
            )
            if compiled.match("", timeout=validation_timeout_ms / 1000) is not None:
                raise SpeechRuleValidationError("Rule patterns must not match empty text.")
        except (regex.error, TimeoutError) as exc:
            raise SpeechRuleValidationError("Rule pattern is invalid or too expensive.") from exc

    def apply(
        self,
        text: str,
        rules: tuple[SpeechRule, ...],
        *,
        context: RuleContext | None = None,
    ) -> RuleApplication:
        started = time.perf_counter()
        current_text = text
        current_map = tuple(RuleSourceSpan(index, index + 1) for index in range(len(text)))
        trace: list[RuleTraceEntry] = []
        warnings: list[RuleWarning] = []
        pauses: list[RulePause] = []
        phonemes: list[Mapping[str, object]] = []
        active_context = context or RuleContext()
        for rule in rules:
            if not rule.enabled or not _matches_context(rule, active_context):
                continue
            elapsed_ms = (time.perf_counter() - started) * 1000
            remaining_ms = self.limits.max_rule_time_per_block_ms - elapsed_ms
            if remaining_ms <= 0:
                warnings.append(
                    RuleWarning(
                        "rule_budget_exceeded",
                        "The total speech-rule budget was exhausted for this block.",
                    )
                )
                break
            try:
                self.validate_rule(rule, timeout_ms=max(1, int(remaining_ms)))
                current_text, current_map = self._apply_rule(
                    current_text,
                    current_map,
                    rule,
                    timeout_ms=min(rule.regex_timeout_ms, max(1, int(remaining_ms))),
                    trace=trace,
                    pauses=pauses,
                    phonemes=phonemes,
                )
            except TimeoutError:
                warnings.append(
                    RuleWarning(
                        "rule_timeout",
                        "A speech rule timed out and was skipped.",
                        rule.id,
                    )
                )
            except SpeechRuleValidationError as exc:
                warnings.append(RuleWarning("rule_invalid", str(exc), rule.id))
        return RuleApplication(
            text=current_text,
            source_spans=current_map,
            trace=tuple(trace),
            warnings=tuple(warnings),
            pauses=tuple(pauses),
            phoneme_annotations=tuple(phonemes),
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    def _apply_rule(
        self,
        text: str,
        source_map: tuple[RuleSourceSpan, ...],
        rule: SpeechRule,
        *,
        timeout_ms: int,
        trace: list[RuleTraceEntry],
        pauses: list[RulePause],
        phonemes: list[Mapping[str, object]],
    ) -> tuple[str, tuple[RuleSourceSpan, ...]]:
        compiled = regex.compile(
            self._pattern_for(rule), self._flags_for(rule) | regex.VERSION1
        )
        matches: list[regex.Match[str]] = []
        for match in compiled.finditer(text, timeout=timeout_ms / 1000):
            matches.append(match)
            if len(matches) > self.limits.max_matches_per_rule:
                raise SpeechRuleValidationError("Rule produced too many matches.")
        if not matches:
            return text, source_map
        output: list[str] = []
        output_map: list[RuleSourceSpan] = []
        pending_trace: list[RuleTraceEntry] = []
        pending_pauses: list[RulePause] = []
        pending_phonemes: list[Mapping[str, object]] = []
        result_length = 0
        cursor = 0
        for match in matches:
            start, end = match.span()
            if end <= start:
                raise SpeechRuleValidationError("Rule patterns must not match empty text.")
            unchanged = text[cursor:start]
            output.append(unchanged)
            output_map.extend(source_map[cursor:start])
            result_length += len(unchanged)
            span = RuleSourceSpan(
                min(item.start_offset for item in source_map[start:end]),
                max(item.end_offset for item in source_map[start:end]),
            )
            replacement = self._replacement(rule, match)
            result_length += len(replacement)
            if result_length + len(text) - end > self.limits.max_result_chars:
                raise SpeechRuleValidationError("Rule output exceeds the configured limit.")
            output.append(replacement)
            output_map.extend(span for _ in replacement)
            pending_trace.append(
                RuleTraceEntry(
                    rule.id,
                    rule.rule_type,
                    span.start_offset,
                    span.end_offset,
                    len(replacement),
                )
            )
            if rule.rule_type is RuleType.PAUSE:
                pending_pauses.append(
                    RulePause(span.end_offset, int(rule.replacement), rule.id)
                )
            elif rule.rule_type is RuleType.PHONEME:
                pending_phonemes.append(
                    {
                        "rule_id": rule.id,
                        "start_offset": span.start_offset,
                        "end_offset": span.end_offset,
                        "phoneme": rule.replacement,
                    }
                )
            cursor = end
        output.append(text[cursor:])
        output_map.extend(source_map[cursor:])
        result = "".join(output)
        if len(result) > self.limits.max_result_chars:
            raise SpeechRuleValidationError("Rule output exceeds the configured limit.")
        trace.extend(pending_trace)
        pauses.extend(pending_pauses)
        phonemes.extend(pending_phonemes)
        return result, tuple(output_map)

    @staticmethod
    def _replacement(rule: SpeechRule, match: regex.Match[str]) -> str:
        if rule.rule_type is RuleType.SKIP:
            return ""
        if rule.rule_type is RuleType.SPELL:
            return " ".join(match.group(0))
        if rule.rule_type is RuleType.PAUSE:
            return match.group(0)
        if rule.rule_type is RuleType.REGEX_REPLACE:
            try:
                return match.expand(rule.replacement)
            except regex.error as exc:
                raise SpeechRuleValidationError("Regex replacement is invalid.") from exc
        return rule.replacement

    @staticmethod
    def _pattern_for(rule: SpeechRule) -> str:
        pattern = (
            rule.pattern
            if rule.rule_type is RuleType.REGEX_REPLACE
            else regex.escape(rule.pattern)
        )
        return rf"\b(?:{pattern})\b" if rule.whole_word else pattern

    @staticmethod
    def _flags_for(rule: SpeechRule) -> regex.RegexFlag:
        return regex.NOFLAG if rule.case_sensitive else regex.IGNORECASE | regex.FULLCASE


def _matches_context(rule: SpeechRule, context: RuleContext) -> bool:
    return all(
        _filter_matches(expected, actual)
        for expected, actual in (
            (rule.language_filter, context.language),
            (rule.engine_filter, context.engine),
            (rule.voice_filter, context.voice),
            (rule.document_filter, context.document_id),
        )
    )


def _filter_matches(expected: str | None, actual: str | None) -> bool:
    if not expected:
        return True
    if not actual:
        return False
    return expected.casefold() == actual.casefold()
