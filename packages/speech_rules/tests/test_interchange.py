from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from reader_core import RuleScope, RuleStage, RuleType, SpeechRule, SpeechRuleSet
from speech_rules import export_rule_set, parse_rule_set


def test_json_interchange_round_trips_supported_rules_and_preserves_unknown_fields() -> None:
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    rule_set = SpeechRuleSet(
        id=str(uuid4()),
        name="Danish IT",
        scope=RuleScope.LANGUAGE,
        created_at=now,
        updated_at=now,
    )
    rule = SpeechRule(
        id=str(uuid4()),
        rule_set_id=rule_set.id,
        name="Expand fx",
        stage=RuleStage.PRONUNCIATION,
        rule_type=RuleType.LITERAL_REPLACE,
        pattern="fx.",
        replacement="for eksempel",
        language_filter="da",
        created_at=now,
        updated_at=now,
        raw_import_metadata={"future_hint": "kept"},
    )

    parsed = parse_rule_set(export_rule_set(rule_set, (rule,)))

    assert parsed.name == "Danish IT"
    assert parsed.scope is RuleScope.LANGUAGE
    assert parsed.candidates[0].pattern == "fx."
    assert parsed.candidates[0].raw_import_metadata == {"future_hint": "kept"}


def test_unsupported_provider_rule_is_preserved_disabled() -> None:
    payload = {
        "format": "tts-platform-reader-rule-set",
        "version": 1,
        "rule_set": {"name": "Provider import", "scope": "global"},
        "rules": [
            {
                "name": "Vendor hint",
                "stage": "pronunciation",
                "rule_type": "vendor_binary_phoneme",
                "pattern": "name",
                "replacement": "payload",
                "vendor": "example",
            }
        ],
    }

    parsed = parse_rule_set(json.dumps(payload).encode())

    assert parsed.unsupported_count == 1
    assert parsed.candidates[0].enabled is False
    assert parsed.candidates[0].raw_import_metadata == {
        "vendor": "example",
        "unsupported_rule_type": "vendor_binary_phoneme",
    }
