from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from reader_core import RuleScope, RuleStage, RuleType, SpeechRule
from speech_rules import (
    RuleContext,
    RuleEngineLimits,
    SpeechRuleEngine,
    SpeechRuleValidationError,
    order_rules,
)

NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)
SET_ID = str(uuid4())


def rule(
    pattern: str,
    replacement: str,
    *,
    rule_type: RuleType = RuleType.LITERAL_REPLACE,
    stage: RuleStage = RuleStage.PRONUNCIATION,
    priority: int = 100,
    **kwargs: object,
) -> SpeechRule:
    return SpeechRule(
        id=str(uuid4()),
        rule_set_id=SET_ID,
        name=f"Rule {pattern}",
        stage=stage,
        rule_type=rule_type,
        pattern=pattern,
        replacement=replacement,
        priority=priority,
        created_at=NOW,
        updated_at=NOW,
        **kwargs,
    )


def test_literal_regex_spell_skip_pause_and_phoneme_keep_source_mapping() -> None:
    rules = (
        rule("URL", "", rule_type=RuleType.SKIP, stage=RuleStage.CLEANUP),
        rule(r"v(\d+)", r"version \1", rule_type=RuleType.REGEX_REPLACE),
        rule("API", "", rule_type=RuleType.SPELL),
        rule("wait", "250", rule_type=RuleType.PAUSE, stage=RuleStage.MARKUP),
        rule("SQL", "sequel", rule_type=RuleType.PHONEME),
    )

    result = SpeechRuleEngine().apply("URL v2 API wait SQL", rules)

    assert result.text == " version 2 A P I wait sequel"
    assert len(result.source_spans) == len(result.text)
    assert result.text[result.text.index("version") :].startswith("version 2")
    version_start = result.text.index("version")
    version_spans = result.source_spans[version_start : version_start + 9]
    assert {span.start_offset for span in version_spans} == {4}
    assert {span.end_offset for span in version_spans} == {6}
    assert result.pauses[0].duration_ms == 250
    assert result.phoneme_annotations[0]["phoneme"] == "sequel"
    assert len(result.trace) == 5


def test_rules_are_nonrecursive_context_filtered_and_deterministically_ordered() -> None:
    first = rule("A", "B", priority=20)
    second = rule("B", "C", priority=10, language_filter="da")
    ordered = order_rules((first, second), {SET_ID: RuleScope.GLOBAL})

    result = SpeechRuleEngine().apply("A", ordered, context=RuleContext(language="en"))

    assert [item.priority for item in ordered] == [10, 20]
    assert result.text == "B"


def test_invalid_empty_matching_regex_and_limits_are_rejected() -> None:
    engine = SpeechRuleEngine(RuleEngineLimits(max_regex_pattern_chars=4))

    with pytest.raises(SpeechRuleValidationError):
        engine.validate_rule(rule(".{0}", "x", rule_type=RuleType.REGEX_REPLACE))
    with pytest.raises(SpeechRuleValidationError):
        engine.validate_rule(rule("12345", "x", rule_type=RuleType.REGEX_REPLACE))


def test_catastrophic_regex_times_out_without_hanging() -> None:
    dangerous = rule(
        r"(a+)+$",
        "x",
        rule_type=RuleType.REGEX_REPLACE,
        regex_timeout_ms=1,
    )

    result = SpeechRuleEngine().apply("a" * 30_000 + "!", (dangerous,))

    assert result.text.endswith("!")
    assert result.warnings[0].code == "rule_timeout"


def test_output_and_match_limits_stop_before_unbounded_expansion() -> None:
    expansion = rule("a", "x" * 50)
    engine = SpeechRuleEngine(
        RuleEngineLimits(max_result_chars=100, max_matches_per_rule=10)
    )

    oversized = engine.apply("aaaa", (expansion,))
    too_many = engine.apply("a" * 20, (rule("a", "x"),))

    assert oversized.text == "aaaa"
    assert oversized.trace == ()
    assert oversized.warnings[0].code == "rule_invalid"
    assert too_many.text == "a" * 20
    assert too_many.trace == ()
    assert too_many.warnings[0].code == "rule_invalid"
