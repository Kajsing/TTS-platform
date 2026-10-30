# Reader whole-block bounds and positions-only source search

Date: 2026-10-30. Starting main: `1ddfb9f`.

## Authorized slice and decisions

The user selected size bounds for large source blocks and full-text search
without downloading the whole article, explicitly permitting subagents.
Parallel work covered bounded repository/API pages, pure search + API tests,
WPF/client integration, compiled real-service acceptance and independent review.
The normative Reader architecture remains unchanged: Python owns SQLite/source
and execution; WPF is the thin client. No new package, database migration,
live settings/library rewrite, paid/cloud dependency or network activation.

Chosen implementation: preserve complete source blocks; stop pages at exact
UTF-8 JSON limits or reject an oversized first block explicitly. Search executes
against one bounded canonical service snapshot, returning cursors/counts only.
Arbitrary regex is not safely reducible to independent page-local matches; the
32-million-UTF-16/100,000-block service snapshot cap is deliberate. No claim of
streaming/unbounded source support. Continuous editor drafts stay local. The
existing Python regex provider is identified as `regex-v0`; .NET regex dialect
and Unicode equality are not promised. These are local implementation choices
within the requested behavior, documented in `docs/reader_source_search.md`.

## Changed areas

- `reader_core/block_pages.py`, errors/protocol and SQLite repository: bounded
  scalar preflight and hydration under a single read snapshot, whole blocks.
- Service config/example, block serializer, routes/schemas/errors: exact 2 MiB
  public response accounting, 1,000,000-code-point block ceiling, continuation
  and actionable 413; final privacy fence after threaded serialization.
- `reader_core/search.py` and `sqlite/search_source.py`: bounded canonical source
  scan, literal/whole-word/regex/highlighter behavior, UTF-16 cursor mapping.
- Service `reader_search.py`, `reader_search_routes.py`, bootstrap/lifecycle,
  middleware and gateway: bounded session indexes, typed failures, protected
  bodies, positions-only POST contracts, final revision/privacy/config fences,
  request-template logging and gateway allowlist/body cap. Upload limits remain
  separate. Shutdown/disconnects cannot publish abandoned sessions.
- WPF remote search helper, application mapping/helper, client DTO/transport and
  MainWindow: paged Find and active highlighter without full-source reads;
  capped visible windows and server-side next-term navigation. Ownership guards
  cover successful and failed late replies. Byte-shortened context pages retry
  from the destination; oversized destinations preserve the previous page.
- Engine/API/repository/client/application tests, WPF lifecycle smoke, compiled
  client smoke and desktop checker; capabilities payload fixture and live docs.

## Failures retained and resolved

- Review found the original scalar COUNT/SUM could visit all blocks before the
  block ceiling. A bounded LIMIT subquery and SQLite progress handler now reject
  before text hydration. SQL-authorizer regressions verify both size paths.
- A shutdown/cancellation race could publish an index after the final check.
  Admission is rechecked under the session lock; deterministic regression passes.
- Deeply nested regex compilation raised `RecursionError`. It now produces
  `invalid_regex` with a dedicated regression.
- A persisted term valid under the old code-point limit could exceed the new
  UTF-16 scan bound. It now yields typed `reader_search_configuration_invalid`
  rather than an unhandled 500; no saved terms are silently rewritten.
- Initial API tests expected privacy 403. Actual established contract is 423;
  expectations were corrected, not the privacy implementation.
- UI review found retained expired Find positions and unowned failure handlers
  could repaint or clear newer results. Both failure/success paths now validate
  generation/client/pager/page ownership, invalidate stale positions, verify
  cursor IDs/revisions and recheck after async page rendering. Held-response WPF
  regressions pass. Previous/Next now handle the new explicit block failure.
- Review reproduced text disclosure when a folder relocked or a document moved
  into a locked folder during threaded block encoding. A final privacy fence
  blocks both; two regressions pass.
- First full Ruff check found two new overlength lines in gateway/test additions;
  formatting corrected them. Final Ruff passes.
- The first payload check failed because the capabilities golden JSON omitted
  the two additive fields. Updated the fixture; all 20 payloads round-trip.

## Validation

Windows uses `py -3` because `python3` is the Store alias. The local .NET 10 SDK
at `%LOCALAPPDATA%\TTSPlatform\dotnet\dotnet.exe` was used instead of PATH's SDK8.

- `py -3 -m pytest -q`: **793 passed, 2 optional skips**, 103.99 seconds.
- `py -3 -m ruff check .`: PASS.
- Scoped `dotnet format whitespace --no-restore --verify-no-changes`: PASS.
- Release solution build: PASS, zero warnings/errors.
- Release solution tests: **403 passed** (199 Application, 100 Client, 104 Windows).
- `py -3 scripts/check_reader_contracts.py`: PASS, 20 payloads.
- `py -3 scripts/check_security_defaults.py`: PASS.
- `py -3 scripts/check_v1_completion.py`: PASS, all 9 existing criteria ready.
- `py -3 scripts/check_desktop_reader.py --require-dotnet --skip-build`: PASS.
  Live compiled HTTP/WS, UTF-16 edits/resume, request-budget saturation/enforcement,
  schema-11 preview integrity, portable packaging, WPF folder/lifecycle and new
  `remote_paged_search` / `remote_highlight_window` assertions all pass.
- Engine/API focused suite: 79 passes. Final block API file: 11 passes. Unicode
  oracle measured all 2,881 local .NET Rune case pairs without literal mismatch;
  representative regex differences are frozen rather than hidden.
- Exact root-shortcut self-contained win-x64 publish: PASS. Started only with
  isolated `--smoke-test`, hidden helpers and temporary synthetic settings.
  Folder/lifetime/edit-preservation and lifecycle/document-switch/pause/tray/
  remote-search flags all pass. Normal Reader/service remain stopped.
- `git diff --check`: PASS. No real audio/global clipboard/hotkey acceptance
  was requested or performed; optional desktop probes report those as skipped.

Ignored evidence: `logs/source-bounds-20261030/check-desktop-reader.json`, its
stderr log, `shortcut-folders.json`, `shortcut-lifecycle.json` and the independent
WPF `logs/remote-search-ui-20261030/lifecycle-final.json`.

## Measured real-service acceptance

| Measurement | Result |
| --- | --- |
| Synthetic source | 2,182,414 characters / 1,601 blocks |
| Initial open | 2 GETs, 64 blocks / 85,946 source characters retained |
| Overlapping capabilities / follows | 8 logical calls -> 1 HTTP call each |
| Search/highlighter block GETs | **0** |
| Deliberately capped Find | 50 hits, truncated |
| Cross-block regex | 1 hit, cursor 0:0 -> 1:9, `regex-v0` |
| Longest-term highlighting | 104,000 phrase hits / 0 nested shorter-term hits |
| Visible overlay window | 2,000 hits, explicit truncation |
| Near-end navigation | index 103,999, 1 bounded block GET / 1 retained block |
| Search responses | 7, largest 906,085 bytes (< 1 MiB) |
| Find / highlighter / combined remote checks | 59.27 / 541.24 / 722.85 ms |
| Initial-load observed allocations | 502,240 bytes |

These are fixture observations, not process peak RSS, universal latency bounds
or proof of all possible regex/provider equivalence. Source/index/request bounds
are enforced independently of the measurements.

## Preserved state and remaining work

Local `models/MANIFEST.json` remains excluded from the commit. Its SHA256 stays
`C0556F885B9AE3D881DDCB8A131B852263DCFC1045872F50F451CDAEC0C95DE8`.
Production config/library/credentials remain unchanged, and Reader/service are
left stopped for normal relaunch. No live source is repartitioned.

Next existing reliability items: paged chapter navigation, product part limits/
preview, independent chapter/edit metadata preflight and append-scaling evidence.
Oversized single-block fragments and sources beyond the search ceiling need
additional contracts. PWA, U8 and audiobook production remain parked. Continuing
the selected existing reliability backlog is safe; networking stays unactivated.
