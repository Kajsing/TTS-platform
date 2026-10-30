from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
import regex
from reader_core import search
from reader_core.search import SearchMatch, highlight_text, search_text

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures/search_case_oracle.json").read_text(encoding="utf-8")
)


@dataclass(frozen=True)
class Term:
    id: str
    term: str
    ordinal: int = 0
    active: bool = True


@pytest.mark.parametrize("case", ORACLE["cases"])
def test_literal_case_matches_local_dotnet_ordinal_oracle(case):
    result = search_text(case["source"], case["query"])
    assert result.failure is None
    assert bool(result.matches) == case["ordinal"]
    if result.matches:
        assert result.matches == (SearchMatch(0, len(case["source"])),)


@pytest.mark.parametrize("case", ORACLE["cases"])
def test_service_regex_unicode_provider_differences_are_explicit(case):
    result = search_text(
        case["source"], "^(?:" + regex.escape(case["query"]) + ")$", use_regex=True
    )
    assert result.failure is None
    assert bool(result.matches) == case["regex_v0"]
    assert search.REGEX_PROVIDER == ORACLE["regex_provider"]


def test_literal_case_filter_keeps_an_overlapping_real_ordinal_match():
    assert search_text("ſSS", "SS").matches == (SearchMatch(1, 3),)


def test_simple_greek_uppercase_never_expands_source_offsets():
    assert search_text("ᾀ ᾈ", "ᾈ").matches == (SearchMatch(0, 1), SearchMatch(2, 3))
    assert search_text("ß ss", "ss").matches == (SearchMatch(2, 4),)


def test_case_sensitive_literal_matches_only_exact_original_source():
    assert search_text("Case case CASE", "case", case_sensitive=True).matches == (
        SearchMatch(5, 9),
    )


def test_literal_unicode_word_boundaries_keep_combining_marks_and_underscore():
    assert search_text("a a\u030a _a a_ a", "a", whole_word=True).matches == (
        SearchMatch(0, 1),
        SearchMatch(11, 12),
    )
    assert search_text("Ål ålX ÅL _Ål Ål_ Ål", "ål", whole_word=True).matches == (
        SearchMatch(0, 2),
        SearchMatch(7, 9),
        SearchMatch(18, 20),
    )


def test_find_literal_word_boundary_retains_dotnet_letter_digit_rule():
    # Rune.IsLetterOrDigit differs from regex \p{N} for non-decimal numerals.
    assert search_text("aⅠa", "a", whole_word=True).matches == (
        SearchMatch(0, 1),
        SearchMatch(2, 3),
    )
    assert not search_text("aⅠa", "a", whole_word=True, use_regex=True).matches


def test_cross_block_phrase_and_greedy_regex_use_the_whole_canonical_text():
    text = "😀 one\r\n\r\ntwo\r\n\r\nthree"
    phrase = search_text(text, "one\r\n\r\ntwo")
    assert phrase.matches == (SearchMatch(2, 12),)
    assert search_text(text, r"one.*three", use_regex=True).matches == ()
    assert search_text(text, r"one[\s\S]*three", use_regex=True).matches == (
        SearchMatch(2, len(text)),
    )


def test_regex_multiline_zero_width_and_invalid_pattern_outcomes():
    text = "Chapter 1\nbody\nChapter 22"
    assert search_text(text, r"^chapter\s+\d+$", use_regex=True).matches == (
        SearchMatch(0, 9),
        SearchMatch(15, 25),
    )
    assert not search_text(text, r"^", use_regex=True).matches
    assert search_text(text, "(", use_regex=True).failure == "invalid_regex"


@pytest.mark.parametrize(
    "pattern",
    [
        r"(a)\k<name>",
        r"(?<left-right>a)",
        r"(?'name'a)",
        r"(?n:a)",
        r"(?V1:a)",
        r"(?f:a)",
        r"(?P<name>a)",
        r"(?(1)a|b)",
        r"\Z",
    ],
)
def test_known_unsupported_dialects_are_rejected_explicitly(pattern):
    assert search_text("a", pattern, use_regex=True).failure == "unsupported_regex"


def test_escaped_unsupported_tokens_remain_searchable_literals():
    assert search_text(r"\k<name>", r"\k<name>").matches == (SearchMatch(0, 8),)
    assert search_text("a", r"(?<name>a)", use_regex=True).matches == (SearchMatch(0, 1),)


@pytest.mark.parametrize("use_regex", [False, True])
def test_find_limit_is_finite_and_truncation_does_not_claim_complete_count(use_regex):
    result = search_text("a a a a", "a", use_regex=use_regex, max_results=3)
    assert result.matches == (SearchMatch(0, 1), SearchMatch(2, 3), SearchMatch(4, 5))
    assert result.truncated
    assert not search_text("a a a", "a", use_regex=use_regex, max_results=3).truncated


def test_source_and_pattern_limits_count_utf16_units(monkeypatch):
    monkeypatch.setattr(search, "MAX_SOURCE_UTF16", 4)
    assert search_text("😀😀", "😀").failure is None
    assert search_text("😀😀a", "a").failure == "document_too_large"
    assert search_text("x", "😀" * 513).failure == "pattern_too_long"


def test_cancellation_and_expired_budget_return_no_partial_results(monkeypatch):
    assert search_text("a a a", "a", cancelled=lambda: True).failure == "cancelled"
    clock = iter([0.0, 0.0, 0.0, 3.0])
    monkeypatch.setattr(search, "time", SimpleNamespace(monotonic=lambda: next(clock, 3.0)))
    result = search_text("a a a", "a")
    assert result.failure == "search_timed_out"
    assert result.matches == ()


def test_actual_pathological_regex_has_a_hard_timeout():
    result = search_text("a" * 200_000 + "!", r"^(a|aa)+$", use_regex=True, timeout_milliseconds=1)
    assert result.failure == "regex_timed_out"
    assert result.matches == ()


def test_deep_valid_length_regex_cannot_escape_the_safe_failure_contract():
    result = search_text("x", "(" * 400 + "x" + ")" * 400, use_regex=True)
    assert result.failure == "invalid_regex"
    assert result.matches == ()
    assert search_text("x", "x", use_regex=True).matches == (SearchMatch(0, 1),)


def test_highlighter_longest_term_precedence_counts_and_non_overlap():
    terms = [Term("short", "New", 0), Term("long", "New York", 1), Term("off", "York", 2, False)]
    result = highlight_text("New York, NEW and new yorker.", terms)
    assert result.matches == (
        SearchMatch(0, 8, "long"),
        SearchMatch(10, 13, "short"),
        SearchMatch(18, 21, "short"),
    )
    assert result.counts == {"long": 1, "short": 2}
    assert not result.truncated


def test_highlighter_case_provider_and_unicode_word_rules_apply_to_original_spans():
    result = highlight_text(
        "😀 İ i ſ s K k", [Term("i", "i"), Term("s", "s", 1), Term("k", "k", 2)]
    )
    assert result.matches == (
        SearchMatch(2, 3, "i"),
        SearchMatch(4, 5, "i"),
        SearchMatch(6, 7, "s"),
        SearchMatch(8, 9, "s"),
        SearchMatch(10, 11, "k"),
        SearchMatch(12, 13, "k"),
    )
    assert result.counts == {"i": 2, "s": 2, "k": 2}
    assert not highlight_text("aⅠa", [Term("a", "a")]).matches


def test_highlighter_truncation_counts_only_retained_hits():
    result = highlight_text("a a a a", [Term("a", "a")], max_results=2)
    assert len(result.matches) == 2
    assert result.counts == {"a": 2}
    assert result.truncated


def test_highlighter_limits_and_cancellation_are_bounded(monkeypatch):
    with pytest.raises(ValueError, match="term limit"):
        highlight_text("a", [Term(str(i), "a", i) for i in range(201)])
    with pytest.raises(ValueError, match="character limit"):
        highlight_text("a", [Term("a", "😀" * 101)])
    with pytest.raises(ValueError, match="identities"):
        highlight_text("a", [Term("same", "a"), Term("same", "b", 1)])
    cancelled = highlight_text("a a a", [Term("a", "a")], cancelled=lambda: True)
    assert (
        cancelled.failure == "cancelled"
        and cancelled.matches == ()
        and cancelled.counts == {"a": 0}
    )
    monkeypatch.setattr(search, "MAX_SOURCE_UTF16", 4)
    assert highlight_text("😀😀a", [Term("a", "a")]).failure == "document_too_large"


@pytest.mark.parametrize("limit", [0, -1, 10_001])
def test_find_result_limit_cannot_remove_the_hard_cap(limit):
    with pytest.raises(ValueError):
        search_text("a", "a", max_results=limit)


@pytest.mark.parametrize("timeout", [0, -1])
def test_timeout_cannot_be_disabled(timeout):
    with pytest.raises(ValueError):
        search_text("a", "a", timeout_milliseconds=timeout)
    with pytest.raises(ValueError):
        highlight_text("a", [Term("a", "a")], timeout_milliseconds=timeout)
