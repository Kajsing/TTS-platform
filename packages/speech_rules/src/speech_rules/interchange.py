from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from reader_core import RuleScope, RuleStage, RuleType, SpeechRule, SpeechRuleSet

from .errors import SpeechRuleInterchangeError

FORMAT_NAME = "tts-platform-reader-rule-set"
FORMAT_VERSION = 1
MAX_INTERCHANGE_BYTES = 1_048_576
MAX_UNKNOWN_METADATA_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class ImportedRuleCandidate:
    name: str
    enabled: bool
    stage: RuleStage
    rule_type: RuleType
    pattern: str
    replacement: str
    case_sensitive: bool
    whole_word: bool
    language_filter: str | None
    engine_filter: str | None
    voice_filter: str | None
    document_filter: str | None
    priority: int
    regex_timeout_ms: int
    unsupported: bool
    raw_import_metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ParsedRuleSet:
    source_sha256: str
    name: str
    description: str
    scope: RuleScope
    candidates: tuple[ImportedRuleCandidate, ...]
    invalid_count: int
    unsupported_count: int
    unknown_metadata: Mapping[str, Any]


def parse_rule_set(data: bytes) -> ParsedRuleSet:
    if not data or len(data) > MAX_INTERCHANGE_BYTES:
        raise SpeechRuleInterchangeError("Rule interchange file is empty or too large.")
    source_sha256 = hashlib.sha256(data).hexdigest()
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpeechRuleInterchangeError("Rule interchange file is not valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict) or payload.get("format") != FORMAT_NAME:
        raise SpeechRuleInterchangeError("Rule interchange format is unsupported.")
    if payload.get("version") != FORMAT_VERSION:
        raise SpeechRuleInterchangeError("Rule interchange version is unsupported.")
    set_payload = payload.get("rule_set")
    rules_payload = payload.get("rules")
    if not isinstance(set_payload, dict) or not isinstance(rules_payload, list):
        raise SpeechRuleInterchangeError("Rule interchange structure is invalid.")
    unknown_top = {
        key: value
        for key, value in payload.items()
        if key not in {"format", "version", "rule_set", "rules"}
    }
    _check_unknown_size(unknown_top)
    candidates: list[ImportedRuleCandidate] = []
    invalid = 0
    unsupported = 0
    for raw in rules_payload[:10_000]:
        if not isinstance(raw, dict):
            invalid += 1
            continue
        candidate = _candidate(raw)
        if candidate is None:
            invalid += 1
            continue
        candidates.append(candidate)
        unsupported += int(candidate.unsupported)
    if len(rules_payload) > 10_000:
        invalid += len(rules_payload) - 10_000
    try:
        scope = RuleScope(str(set_payload.get("scope", "global")))
    except ValueError as exc:
        raise SpeechRuleInterchangeError("Rule-set scope is unsupported.") from exc
    return ParsedRuleSet(
        source_sha256=source_sha256,
        name=str(set_payload.get("name", "Imported rules"))[:200],
        description=str(set_payload.get("description", ""))[:2000],
        scope=scope,
        candidates=tuple(candidates),
        invalid_count=invalid,
        unsupported_count=unsupported,
        unknown_metadata=unknown_top,
    )


def export_rule_set(rule_set: SpeechRuleSet, rules: tuple[SpeechRule, ...]) -> bytes:
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "rule_set": {
            "name": rule_set.name,
            "description": rule_set.description,
            "scope": rule_set.scope.value,
        },
        "rules": [_export_rule(rule) for rule in rules],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def candidate_signature(candidate: ImportedRuleCandidate) -> tuple[object, ...]:
    values = asdict(candidate)
    values.pop("raw_import_metadata")
    values.pop("unsupported")
    return tuple(values[key] for key in sorted(values))


def rule_signature(rule: SpeechRule) -> tuple[object, ...]:
    return candidate_signature(
        ImportedRuleCandidate(
            name=rule.name,
            enabled=rule.enabled,
            stage=rule.stage,
            rule_type=rule.rule_type,
            pattern=rule.pattern,
            replacement=rule.replacement,
            case_sensitive=rule.case_sensitive,
            whole_word=rule.whole_word,
            language_filter=rule.language_filter,
            engine_filter=rule.engine_filter,
            voice_filter=rule.voice_filter,
            document_filter=rule.document_filter,
            priority=rule.priority,
            regex_timeout_ms=rule.regex_timeout_ms,
            unsupported=False,
            raw_import_metadata={},
        )
    )


def _candidate(raw: Mapping[str, Any]) -> ImportedRuleCandidate | None:
    known = {
        "name", "enabled", "stage", "rule_type", "pattern", "replacement",
        "case_sensitive", "whole_word", "language_filter", "engine_filter",
        "voice_filter", "document_filter", "priority", "regex_timeout_ms",
    }
    unknown = {key: value for key, value in raw.items() if key not in known}
    try:
        _check_unknown_size(unknown)
        stage = RuleStage(str(raw.get("stage", "pronunciation")))
        raw_type = str(raw.get("rule_type", "literal_replace"))
        try:
            rule_type = RuleType(raw_type)
            unsupported = False
        except ValueError:
            rule_type = RuleType.PHONEME
            unsupported = True
            unknown = {**unknown, "unsupported_rule_type": raw_type}
        pattern = str(raw["pattern"])
        if not pattern or len(pattern) > 2_048:
            return None
        replacement = str(raw.get("replacement", ""))
        if len(replacement) > 4_096:
            return None
        return ImportedRuleCandidate(
            name=str(raw.get("name", pattern))[:200],
            enabled=bool(raw.get("enabled", True)) and not unsupported,
            stage=stage,
            rule_type=rule_type,
            pattern=pattern,
            replacement=replacement,
            case_sensitive=bool(raw.get("case_sensitive", False)),
            whole_word=bool(raw.get("whole_word", False)),
            language_filter=_optional_text(raw.get("language_filter")),
            engine_filter=_optional_text(raw.get("engine_filter")),
            voice_filter=_optional_text(raw.get("voice_filter")),
            document_filter=_optional_text(raw.get("document_filter")),
            priority=int(raw.get("priority", 100)),
            regex_timeout_ms=int(raw.get("regex_timeout_ms", 25)),
            unsupported=unsupported,
            raw_import_metadata=unknown,
        )
    except (KeyError, TypeError, ValueError, SpeechRuleInterchangeError):
        return None


def _export_rule(rule: SpeechRule) -> dict[str, object]:
    return {
        "name": rule.name,
        "enabled": rule.enabled,
        "stage": rule.stage.value,
        "rule_type": rule.rule_type.value,
        "pattern": rule.pattern,
        "replacement": rule.replacement,
        "case_sensitive": rule.case_sensitive,
        "whole_word": rule.whole_word,
        "language_filter": rule.language_filter,
        "engine_filter": rule.engine_filter,
        "voice_filter": rule.voice_filter,
        "document_filter": rule.document_filter,
        "priority": rule.priority,
        "regex_timeout_ms": rule.regex_timeout_ms,
        **dict(rule.raw_import_metadata),
    }


def _optional_text(value: object) -> str | None:
    return str(value)[:200] if value not in {None, ""} else None


def _check_unknown_size(value: Mapping[str, Any]) -> None:
    try:
        size = len(json.dumps(dict(value), ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise SpeechRuleInterchangeError("Unknown rule metadata is not valid JSON.") from exc
    if size > MAX_UNKNOWN_METADATA_BYTES:
        raise SpeechRuleInterchangeError("Unknown rule metadata exceeds 64 KiB.")
