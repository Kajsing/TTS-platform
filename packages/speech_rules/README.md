# Speech Rules

This package owns the engine-independent Reader speech-rule compiler and JSON
interchange format. It supports literal and regular-expression replacement,
skip, spell, pause, and preserved phoneme rules without coupling API contracts
to a synthesis backend.

Untrusted expressions run through the `regex` package with a hard per-rule
timeout, bounded patterns and replacements, a total block budget, a match cap,
and a bounded result size. Rule application never changes stored document text;
every generated character remains mapped to the original source span.

The protected preview API limits input to 4,096 characters because its response
contains a source span for every spoken character. Runtime playback continues to
apply the same engine to bounded Reader block windows without serializing that
per-character map to the UI.

The JSON interchange format is documented in `docs/reader_rule_interchange.md`.
It contains no tokens, document text, or provider binary data. Unknown fields
are preserved within a 64 KiB metadata limit, and unsupported rule types are
retained as disabled candidates.
