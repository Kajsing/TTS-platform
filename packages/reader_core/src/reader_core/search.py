"""Bounded, transport-independent search over canonical Reader source.

Spans always index the original Python string (Unicode code points). The service
maps them to canonical UTF-16 Reader cursors. Regex searches use regex VERSION0,
not a claim of complete .NET regex dialect/Unicode equivalence.
"""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import regex

REGEX_PROVIDER = "regex-v0"
MAX_SOURCE_UTF16 = 32_000_000
MAX_PATTERN_UTF16 = 1_024
MAX_FIND_RESULTS = 10_000
MAX_HIGHLIGHT_RESULTS = 250_000
MAX_HIGHLIGHT_TERMS = 200
MAX_TERM_UTF16 = 200
FIND_REGEX_TIMEOUT_MS = 200
LITERAL_TIMEOUT_MS = 2_000
HIGHLIGHT_TIMEOUT_MS = 2_000
_ASTRAL_RUNS = regex.compile(r"[^\u0000-\uffff]+", regex.VERSION0)


@dataclass(frozen=True, slots=True)
class SearchMatch:
    start: int
    end: int
    term_id: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResult:
    matches: tuple[SearchMatch, ...] = ()
    truncated: bool = False
    failure: str | None = None
    counts: dict[str, int] = field(default_factory=dict)


class HighlightTerm(Protocol):
    id: str
    term: str
    ordinal: int
    active: bool


class _Interrupted(Exception):
    def __init__(self, failure: str) -> None:
        self.failure = failure


class _Budget:
    def __init__(
        self, milliseconds: int, cancelled: Callable[[], bool] | None, timeout_failure: str
    ) -> None:
        if not isinstance(milliseconds, int) or isinstance(milliseconds, bool) or milliseconds <= 0:
            raise ValueError("search timeout must be positive")
        self.deadline = time.monotonic() + milliseconds / 1_000
        self.cancelled = cancelled
        self.timeout_failure = timeout_failure

    def remaining(self) -> float:
        if self.cancelled is not None and self.cancelled():
            raise _Interrupted("cancelled")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _Interrupted(self.timeout_failure)
        return remaining


def _small_utf16_length(text: str) -> int:
    return len(text) + sum(ord(character) > 0xFFFF for character in text)


def _source_fits(text: str, budget: _Budget) -> bool:
    budget.remaining()
    if len(text) > MAX_SOURCE_UTF16:
        return False
    units = len(text)
    if not text.isascii():
        for match in _ASTRAL_RUNS.finditer(text, timeout=budget.remaining()):
            units += match.end() - match.start()
            if units > MAX_SOURCE_UTF16:
                return False
            budget.remaining()
    return True


def _ordinal_upper(character: str) -> str:
    upper = character.upper()
    if len(upper) != 1:
        # Greek prosgegrammeni has a simple uppercase/titlecase mapping while
        # Python upper() expands it. Never introduce a multi-character fold.
        upper = character.title()
    if len(upper) != 1 or (ord(character) >= 128 and ord(upper) < 128):
        # .NET ordinal comparison excludes non-ASCII-to-ASCII case pairs such
        # as long s and dotless i; culture-aware regex comparison is different.
        return character
    return upper


def _ordinal_equal(left: str, right: str) -> bool:
    return len(left) == len(right) and all(
        a == b or _ordinal_upper(a) == _ordinal_upper(b) for a, b in zip(left, right, strict=True)
    )


def _literal_word_character(character: str) -> bool:
    category = unicodedata.category(character)
    return character == "_" or category.startswith(("L", "M")) or category == "Nd"


def _whole_literal_word(text: str, start: int, end: int) -> bool:
    return (start == 0 or not _literal_word_character(text[start - 1])) and (
        end == len(text) or not _literal_word_character(text[end])
    )


def _unsupported_regex(pattern: str) -> bool:
    """Reject known .NET-only or provider-switching constructs explicitly."""
    in_class = False
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "\\":
            if index + 1 < len(pattern) and not in_class and pattern[index + 1] in {"k", "Z"}:
                return True
            index += 2
            continue
        if character == "[":
            in_class = True
        elif character == "]":
            in_class = False
        elif not in_class and pattern.startswith("(?", index):
            tail = pattern[index + 2 :]
            if tail.startswith(("'", "P", "|", "R", "0", "&", "(")):
                return True
            if tail.startswith("<") and not tail.startswith(("<=", "<!")):
                name = tail[1:].split(">", 1)[0]
                if "-" in name:
                    return True
            if tail and (tail[0].isalpha() or tail[0] == "-"):
                flags = tail.split(":", 1)[0].split(")", 1)[0]
                if any(flag not in "imsx-" for flag in flags):
                    return True
        index += 1
    return False


def search_text(
    text: str,
    query: str,
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
    use_regex: bool = False,
    max_results: int = MAX_FIND_RESULTS,
    cancelled: Callable[[], bool] | None = None,
    timeout_milliseconds: int | None = None,
) -> SearchResult:
    if not 1 <= max_results <= MAX_FIND_RESULTS:
        raise ValueError("Find result limit is outside its bounded range")
    if len(query) > MAX_PATTERN_UTF16 or _small_utf16_length(query) > MAX_PATTERN_UTF16:
        return SearchResult(failure="pattern_too_long")
    maximum_timeout = FIND_REGEX_TIMEOUT_MS if use_regex else LITERAL_TIMEOUT_MS
    timeout = maximum_timeout if timeout_milliseconds is None else timeout_milliseconds
    budget = _Budget(
        min(timeout, maximum_timeout),
        cancelled,
        "regex_timed_out" if use_regex else "search_timed_out",
    )
    try:
        budget.remaining()
        if not query:
            return SearchResult()
        if not _source_fits(text, budget):
            return SearchResult(failure="document_too_large")
        if use_regex and _unsupported_regex(query):
            return SearchResult(failure="unsupported_regex")
        flags = regex.VERSION0 | regex.MULTILINE
        if not case_sensitive:
            flags |= regex.IGNORECASE
        pattern = query if use_regex else regex.escape(query)
        if whole_word and use_regex:
            pattern = rf"(?<![\p{{L}}\p{{M}}\p{{N}}_])(?:{pattern})(?![\p{{L}}\p{{M}}\p{{N}}_])"
        compiled = regex.compile(pattern, flags)
        matches: list[SearchMatch] = []
        if use_regex:
            for match in compiled.finditer(text, timeout=budget.remaining()):
                budget.remaining()
                if match.start() == match.end():
                    continue
                if len(matches) == max_results:
                    return SearchResult(tuple(matches), truncated=True)
                matches.append(SearchMatch(match.start(), match.end()))
        else:
            position = 0
            while position <= len(text) - len(query):
                budget.remaining()
                match = compiled.search(text, pos=position, timeout=budget.remaining())
                if match is None:
                    break
                start, end = match.span()
                if not case_sensitive and not _ordinal_equal(text[start:end], query):
                    # A regex case candidate may fail ordinal comparison. Do
                    # not skip an overlapping real match ("SS" in "ſSS").
                    position = start + 1
                    continue
                if not whole_word or _whole_literal_word(text, start, end):
                    if len(matches) == max_results:
                        return SearchResult(tuple(matches), truncated=True)
                    matches.append(SearchMatch(start, end))
                position = end
        budget.remaining()
        return SearchResult(tuple(matches))
    except _Interrupted as interrupted:
        return SearchResult(failure=interrupted.failure)
    except TimeoutError:
        return SearchResult(failure=budget.timeout_failure)
    except (regex.error, RecursionError):
        return SearchResult(failure="invalid_regex")


def highlight_text(
    text: str,
    terms: Sequence[HighlightTerm],
    *,
    max_results: int = MAX_HIGHLIGHT_RESULTS,
    cancelled: Callable[[], bool] | None = None,
    timeout_milliseconds: int = HIGHLIGHT_TIMEOUT_MS,
) -> SearchResult:
    if len(terms) > MAX_HIGHLIGHT_TERMS:
        raise ValueError("highlighter term limit exceeded")
    if not 1 <= max_results <= MAX_HIGHLIGHT_RESULTS:
        raise ValueError("highlighter match limit is outside its bounded range")
    active = [term for term in terms if term.active and term.term.strip()]
    if any(_small_utf16_length(term.term) > MAX_TERM_UTF16 for term in active):
        raise ValueError("highlighter term character limit exceeded")
    if len({term.id for term in active}) != len(active):
        raise ValueError("highlighter term identities must be unique")
    active.sort(key=lambda term: (-_small_utf16_length(term.term), term.ordinal))
    counts = {term.id: 0 for term in active}
    budget = _Budget(min(timeout_milliseconds, HIGHLIGHT_TIMEOUT_MS), cancelled, "search_timed_out")
    try:
        budget.remaining()
        if not active or not text:
            return SearchResult(counts=counts)
        if not _source_fits(text, budget):
            return SearchResult(failure="document_too_large", counts=counts)
        alternatives = "|".join(
            f"(?P<term{index}>{regex.escape(term.term)})" for index, term in enumerate(active)
        )
        pattern = rf"(?<![\p{{L}}\p{{M}}\p{{N}}_])(?:{alternatives})(?![\p{{L}}\p{{M}}\p{{N}}_])"
        compiled = regex.compile(pattern, regex.VERSION0 | regex.IGNORECASE)
        matches: list[SearchMatch] = []
        for match in compiled.finditer(text, timeout=budget.remaining()):
            budget.remaining()
            if len(matches) == max_results:
                return SearchResult(tuple(matches), truncated=True, counts=counts)
            term = active[int(match.lastgroup.removeprefix("term"))]
            counts[term.id] += 1
            matches.append(SearchMatch(match.start(), match.end(), term.id))
        budget.remaining()
        return SearchResult(tuple(matches), counts=counts)
    except _Interrupted as interrupted:
        return SearchResult(failure=interrupted.failure, counts={term.id: 0 for term in active})
    except TimeoutError:
        return SearchResult(failure="search_timed_out", counts={term.id: 0 for term in active})
