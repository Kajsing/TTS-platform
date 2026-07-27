# Reader speech-rule JSON interchange

The Reader-owned interchange is UTF-8 JSON with a 1 MiB file limit:

```json
{
  "format": "tts-platform-reader-rule-set",
  "version": 1,
  "rule_set": {
    "name": "Danish IT",
    "description": "Shared terminology",
    "scope": "language"
  },
  "rules": [
    {
      "name": "Expand fx",
      "enabled": true,
      "stage": "pronunciation",
      "rule_type": "literal_replace",
      "pattern": "fx.",
      "replacement": "for eksempel",
      "case_sensitive": false,
      "whole_word": false,
      "language_filter": "da",
      "engine_filter": null,
      "voice_filter": null,
      "document_filter": null,
      "priority": 100,
      "regex_timeout_ms": 25
    }
  ]
}
```

Supported scopes are `system`, `global`, `language`, `voice_engine`, and
`document`. Supported stages are `cleanup`, `pronunciation`, and `markup`.
Supported types are `literal_replace`, `regex_replace`, `skip`, `spell`,
`pause`, and `phoneme`.

Import is dry-run by default. The service hashes the exact source bytes and an
identical committed import into the same target set is idempotent. Unknown JSON
fields are preserved in bounded metadata. An unknown provider rule type is
reported and retained disabled rather than silently discarded. The format must
not contain bearer tokens, document text, executable code, or backend binaries.
