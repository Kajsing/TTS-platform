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

Milestone 7 adds `rule_preview.response.json`. Rule previews return the explicit
input and transformed speech text, per-character UTF-16 source spans, an ordered
rule trace, typed warnings, elapsed time, and pipeline/rules versions. Request
and response text is intentionally excluded from service logs. Preview input is
limited to 4,096 characters so per-character mapping remains interactive;
playback compilation retains its separate bounded-window limit.

Milestone 8 adds `create_export.request.json` and `export_job.response.json`.
WAV jobs persist in the Reader database, expose bounded progress without source
text or output-directory paths, and continue while desktop clients disconnect.

Milestone 9 adds structured browser-capture and desktop-open-request fixtures.
Browser captures accept only HTTP(S) source URLs, preserve bounded block kinds
and headings, and expose no filesystem destination. Desktop handoffs are
persistent, idempotent per document, and acknowledged only after the WPF client
has opened the saved document.

Reader Upgrade U3 adds `highlighter.request.json` and
`highlighter.response.json`. The one global literal-term list is revisioned,
stores stable presentation colors, and remains available to future authenticated
Reader clients without exposing article text.

Reader Upgrade U4 adds `folders.response.json`, `move_documents.request.json`,
and `folder_delete.response.json`. Folder membership is a service-owned nullable
document relationship; multi-article moves and the two explicit deletion modes
are revisioned and transactional.
