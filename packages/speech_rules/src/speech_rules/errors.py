from __future__ import annotations


class SpeechRuleError(Exception):
    """Base class for safe, user-facing speech-rule failures."""


class SpeechRuleValidationError(SpeechRuleError):
    pass


class SpeechRuleInterchangeError(SpeechRuleError):
    pass
