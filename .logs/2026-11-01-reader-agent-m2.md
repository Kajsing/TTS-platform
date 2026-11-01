# 2026-11-01: Reader Agent M2

## Scope and result

Implemented the five owner-selected MCP improvements in the existing domain /
SQLite repository / application service / loopback API / stdio adapter layers.
Adapter 1.1.0 exposes 16 tools. Additive migrations 012/013 preserve M1 data and
grants; no permission category or dependency was added. Public contracts and
limits: `docs/reader_agent_m2.md`.

- Preserve sanitized busy causes, supplied retry timing and budget identity;
  preserve legacy outcome/code fields, with no automatic replay of writes.
- Durable folder-local creation identities and restart-safe managed previews.
- Default 900k whole-chapter parts with normalized code-point/UTF-16/block and
  conservative edit/marker metadata preflight. Bounded batches create new parts.
- Atomic creation/append/receipt/assignment/progress; version/lease fences,
  cross-part/M1 duplicate protection and physical-purge progress tombstones.
- Scoped live story status; current structural chapter text and bounded literal
  overlapping/cross-paragraph search. Full readback remains authoritative.

## Decisions and review fixes

Subagents implemented independent retry, planner and chapter-content pieces and
reviewed security/transaction behavior. Root integrated all contracts and tests.
Stage execution was parallelized without dropping any acceptance requirement.
Plans store fingerprints/assignments/wrappers, not chapter bodies; batches start
new parts rather than modify prior ones. Existing permission allowlists apply:
managed calls need list/create/deliver, status list/chapters, text/search read.
Quota: 256 retained folder plans, 100 chapters / 2 MiB HTTP JSON per batch.
Status has per-call consistency, not a snapshot across pages; owner moves may
change visibility without advancing its delivery version.

Review fixed metadata parsing before scalar scope/bounds checks, unreadable
marker IDs, deep metadata JSON, stale lease-target races, missing receipt/part
cascades after physical purge, and a reproducible playback lease bypass through
collision with a public creation retry key. Managed new-part creation now has
no public creation key: its surrounding atomic transaction/plan identity owns
retry safety. A regression with the actual service/lease registry proves the
playing article stays unchanged. An independent randomized literal-search
oracle checked 240 Unicode/overlap/pagination cases.

## Validation evidence

- Final full Python suite: **1,021 passed / 3 optional skips**. Separate optional
  agent + import/migration suite: **120 passed**, including actual commit-failure,
  schema-11 upgrade and encoded-request-byte regressions. The global runtime
  lacks optional MCP SDK 2; real SDK 2 tests run in `.venv-agent`.
- 449 .NET tests passed (107 client, 238 application, 104 Windows).
- Ruff, 21 Reader payload fixtures and scoped .NET whitespace checks passed.
- Isolated self-contained win-x64 publish passed with no warnings, using
  `--artifacts-path apps/desktop_reader/artifacts/reader-agent-m2/build` and
  a separate `publish` output; no root-shortcut deployment.
- Real stdio/Windows smoke passed: DPAPI provisioning, 16 tools, creation and
  chapter retries, real process restart, scope/revocation, exact text readback,
  current chapter reads/search, ordinary WPF library/editor and chapter-selector
  selection. Stub speech returned 136 source-mapped packets/spans; no physical
  audio device or audible playback was used.
- Default-policy large fixture: 2,210,000 source code points in 13 chapters,
  two bounded batches, three parts, maximum 850,027 code points. Read back all
  2,210,077 normalized characters including repeated wrappers/separators, exact
  equality per part; UTF-16 limits and structural chapter counts also checked.
  Calls were paced below the unchanged 120/minute agent budget.
- Schema-11 upgrade regression preserves article text, metadata/revisions,
  credentials, receipts and all eleven original migration checksums.
- Actual commit-failure and injected post-append failures leave no orphan part,
  receipt, false progress or partial source. Concurrent and lost-response retry,
  stale preview/edit, Undo, move/delete/privacy/revocation and read leases are
  covered by repository/API/MCP tests.

Retained local generated evidence lives under
`apps/desktop_reader/artifacts/reader-agent-m2/` and `logs/reader-agent-m2/`
(git-ignored). Only synthetic source was used; no live article/grant/config was
read or changed by the test scenario. Existing `models/MANIFEST.json` edits are
excluded from this slice.

## Failed evidence and corrections

- Giant raw-metadata pytest parameter IDs exceeded Windows environment limits;
  short explicit test IDs fixed setup without changing acceptance.
- An early full suite had two schema assertions loaded as version 12 while the
  parallel additive migration 013 appeared during execution. Captured failures
  show actual 13 versus expected 12; expected current schema was updated to 13
  and the consolidated suite rerun after source stabilized.
- An initial `dotnet publish -o ...` still targeted ordinary build intermediates
  and failed on DLLs held by running Reader PID 23952. No process was stopped.
  `--artifacts-path` isolated all build outputs; publish and real Windows smoke
  then passed. The existing Reader process remained running.

## Remaining runtime boundary

Source/tests and isolated publication are complete. The running local service
still needs a normal restart to load M2 routes/migrations. No live restart,
in-place library migration, root-shortcut deployment, audio-device test,
networking/U8, website capture or scheduled monitoring was performed. Desktop
production behavior is unchanged apart from its isolated test harness. It is
safe to use M2 after normal service restart and MCP reconnect; do not deploy over
active/unsaved Reader state. Product-wide import UI and append-scaling work remain
separate backlog items.
