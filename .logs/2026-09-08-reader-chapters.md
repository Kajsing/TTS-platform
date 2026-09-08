# Reader chapter system - Sep 8

User approved independent chapter anchors over canonical article text, not a
reuse of import sections. No app goal or networking work was requested. U8 is
still parked. Preserve the user-owned `models/MANIFEST.json` changes.

Implemented domain marker normalization and transactional history snapshots;
API chapter mutations and opt-in append metadata; retry-safe MCP chapter
delivery; thin desktop contracts, chapter/all-text projection, chapter tools,
clipboard checkbox, scoped Find and audible chapter following. Speech compiler
input is split at anchors without changing stream window accounting. No copied
article text, SQL migration or public internet dependency was introduced.

Important regression found and fixed during testing: whole-paragraph desktop
saves must map markers through the changed middle, not collapse unchanged
chapter boundaries to the end of the wire replacement. History byte accounting
now includes metadata and retains a contiguous suffix rather than skipping an
oversized operation and exposing older, unsafe Undo entries.

Tests include Unicode/UTF-16 boundaries, atomic failures, revision conflicts,
leases, append/continue/Undo/Redo, chapter title/history, MCP retry deduplication,
compiler continuation, client wire contracts and isolated WPF views. The WPF
probe covers a mid-paragraph chapter, editing without changing hidden text,
dirty-view guards, audible chapter transition, pause marker/viewport and Find
across hidden chapters. It runs alongside the prior pause/document-switch tests.

Known existing bounds: continuous chapter UI requires editable text within
1,000,000 characters / 20,000 blocks; structured/oversized articles retain their
existing path. View mode is session-local. No automatic reconstruction of old
chapters or per-chapter export/reordering/deletion. Real listening remains a
user field check; synthetic probes do not claim to hear TTS output.

Validation/deployment results are recorded in `docs/codex/Documentation.md`.
