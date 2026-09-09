# Durable capture outbox

User approved local buffering/synchronization after rapid large clipboard imports
hit rate limits, and explicitly deferred SAPI fallback. No app goal/networking,
paid dependency or playback-engine change was introduced.

Implemented DPAPI CurrentUser capture envelopes, flushed atomic writes and
bounded FIFO delivery; explicit UI wait/retry/discard/recovery; queued-create
append references; workspace binding; minimal transactional service receipts;
Retry-After/cross-client cooldown and low-sensitivity diagnostic events.

Source areas: Reader Client/Application/Windows/App and tests; service capture
schema/route/error/remote allowlist/rate response; reader_core migration 011,
receipt repository and conflict error. The existing per-user model manifest
was not edited/staged. SAPI is only recorded in the new capture outbox plan.

Tests found a Python frozen-exception/contextlib traceback incompatibility in
rejection paths. Application/privacy errors are now carried through rollback
and lease release before being raised, with capture-specific regression tests.
WPF tests separate delivery acknowledgement from failed library reload, preserve
queued parent IDs, and exercise UI responsiveness with an in-flight request.

Validation: 654 Python passes/2 optional skips; 313 .NET passes; Ruff, scoped
format, build, isolated live HTTP full-text capture/readback, portable package,
WPF lifecycle and actual Windows silent-audio reopen. Exact shortcut probe at
`logs/capture-outbox-20260909/shortcut/` includes `capture-outbox-result.json`
and an inspected `capture-queue.png`. Global clipboard/hotkeys and real TTS
listening were deliberately not activated by automated tests.

User confirmed Reader/tray closed. SQLite backup before migration/restart:
`%LOCALAPPDATA%\TTSPlatform\Reader\backups\2026-09-09-before-capture-outbox.db`.
Integrity passed. Existing LocalServiceProcessControl verified the recorded
launcher, reserved idle maintenance, stopped its process tree and restarted it
hidden with a new persisted ownership lease. Post-restart health schema 11,
25 voices, idle. All live article/block/position rows match backup; receipts
table is empty (no production test content). Two initial PowerShell type/optional
argument binding errors occurred before any service mutation and were corrected.

Boundaries: queue runs while Reader is open; only explicitly accepted captures
are persisted. Unaccepted prompts wait in bounded RAM. No overall library
backup/sync promise, no claim all intermittent playback faults are fixed.
No local rate configuration change; the inspected current TOML has no explicit
requests-per-minute override, despite an older Sep 8 note about a 120/min override.
Any next playback budget adjustment should use current runtime evidence.
