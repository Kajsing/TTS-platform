# 2026-11-01: desktop import parts, plan cleanup and deployment

## Authorized scope

The owner selected all three recommendations and explicitly allowed Reader
downtime: append measurement, plan reconciliation and desktop import preview.
No app goal was registered for this follow-up. Benchmark evidence is separate in
`reader-append-benchmark` docs/log; no performance optimization was implemented.

## Implementation

- Added pure whole-chapter planning over parsed import sections at an explicit
  heading level. Shared 900k code-point/UTF-16 policy, block/chapter/part caps,
  metadata headroom and response byte bounds. Source blocks, code whitespace,
  metadata and section ancestry are preserved; no spoken wrapper is added.
- Added protected owner parts-preview/parts-commit routes over the existing
  bounded ten-minute preview cache. A plan hash pins complete source and policy.
  Commit rechecks duplicates, expiry and destination privacy inside one SQLite
  transaction, creates all parts/real chapter markers together, and keeps at most
  one shared managed original. Rollback removes both partial DB state and source
  copy. Existing single-document/MCP paths are retained.
- Extracted the existing transaction-bound repository facade into a generic
  persistence helper, retaining its private agent alias. No migration/dependency.
- WPF single-file dialog shows selectable limit/heading level, proposed titles,
  chapter ranges/counts, warnings and source sample. Source changes require
  re-upload/review; policy changes invalidate the plan. Saving requires the exact
  reviewed plan. Imported structured files use ordinary paged chapter navigation.
- Batch dialog uses a separate prepared-import coordinator with explicit preview
  and save phases. Per-file atomicity, bounded file count, pending-preview cleanup,
  option generations, acknowledged results and uncertain outcomes are explicit.
  JSON/transport errors and duplicate/incomplete acknowledgements never become
  false success or automatic write retries.
- Cached original bytes now have an aggregate configured byte budget. New owner
  routes are explicitly denied by the remote gateway; no U8 exposure was added.
- Reconciled stale Service Center/M1/M2 resume points, activation status and retry
  wording. Original approvals remain historical; parked tracks stay parked.

## Review and validation

Independent subagent review found and fixed operation ownership acquired too
late during old-preview deletion, malformed commit body handling and incomplete
acknowledgement acceptance. A real WPF HTTP gate now holds cleanup while a second
refresh is attempted, proving only one upload proceeds. Batch tests cover late
option changes, cancel/close, lost replies, malformed JSON, duplicate IDs and
preservation of prior acknowledged files.

- Full Python: **1,062 passed / 3 optional skips**; two existing HTTP dependency
  deprecation warnings. Optional agent/part/benchmark suite: **139 passed**.
- .NET: **479 passed** (113 client, 262 application, 104 Windows).
- Ruff, 21 shared payload fixtures, scoped .NET whitespace checks and zero-warning
  isolated/live self-contained win-x64 publication passed.
- Real WPF/HTTP import smoke passed: default900k, explicit heading choice,
  preview with no save, stale/oversized rejection, cleanup ownership, three
  single-file parts and six batch parts. Public API readback exactly reconstructs
  all three synthetic files; normal post-import chapter selector is visible.
  Preview/single-reader/batch screenshots were visually inspected.
- Existing real stdio/Windows M2 smoke passed after transaction extraction:
  protected keys, 16 tools, process restart/retry/scope/revocation, current chapter
  reads/search, ordinary source-mapped stub stream and full exact 2.21m source
  fixture readback. No physical audio device was used.
- The append measurement independently passed all 60 sample readbacks/receipts.
  Phase evidence and noisy outliers are preserved in its report.

Failed evidence/corrections: an early UI test incorrectly required a continuous
editor for read-only Markdown; the assertion now verifies the actual paged chapter
catalog. First full Python run found unclassified new remote routes; default deny
already blocked them, and explicit deny entries/tests were added. A smoke helper
used the wrong overload for folder listing; corrected to the existing public
folder method. All corrected relevant/full runs pass. No passing rerun replaces
an unresolved failed requirement.

Generated reports are ignored under `logs/reader-desktop-parts-validation/`,
`logs/reader-append-benchmark-20261101/` and
`apps/desktop_reader/artifacts/reader-desktop-parts/`.

## Actual runtime deployment

The existing Reader window was closed through its normal Alt+F4 path. No unsaved
dialog appeared and minimize-to-tray-on-close was false; the window closed fully
before its verified idle tray host PID 23952 was stopped. No unrelated process
tree was terminated. Published the exact root-shortcut win-x64 directory from
isolated build outputs; four installed production DLL SHA-256 hashes match the
validated isolated publication.

The production service coordinator confirmed idle work/ownership, reserved
maintenance, restarted the recorded hidden launcher and verified voice/backend/
database readiness (new service PID 28800, schema13). Reader was reopened (PID
32584) and its actual window reports Connected, 25 voices and service running.
Live OpenAPI exposes both new owner import routes. Fresh real stdio MCP confirms
all16 tools and the existing seven Battlemage articles/360 chapter receipts;
article versions remain 61,60,61,60,61,21,43 for Parts01..07. No live test imports,
new grants, library repartition or model MANIFEST changes were made.

All three selected tasks are complete. A search-index optimization is a proposal
for a separately selected next slice, not part of this measurement/deployment.
