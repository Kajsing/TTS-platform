# Reader contract fixtures

These JSON files freeze representative version-1 Reader HTTP payloads. They are
backend-agnostic and intentionally exclude document text from summaries and edit
history text from mutation responses.

Run `py -3 scripts\check_reader_contracts.py` on Windows to validate every
fixture against the service schemas. Contract changes must remain additive or
increment `contract_version` deliberately.

All `/v1/reader/*` routes require the service's existing bearer-token and origin
checks. `/v1/health` remains public and exposes only sanitized Reader readiness.

Reader stream protocol version 1 is available at `WS /v1/reader/stream`. Its
JSON control-event and binary PCM pairing is frozen in
`design_doc/reader_workstation_design_v1.md`; deterministic Python service and
.NET parser tests enforce identity, byte counts, monotonic UTF-16 cursors,
source spans, cancellation, and continuation.

Milestone 6 adds `import_preview.response.json`. Import preview payloads are
bounded: section summaries and sample blocks may be truncated while total
counts and all structured warnings remain explicit. Committing the opaque
preview ID persists those warnings in document metadata.
