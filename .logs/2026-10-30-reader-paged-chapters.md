# Paged chapter navigation

Date: 2026-10-30. Starting main: `d580359`.

## Scope and decisions

The user selected the next existing reliability item: chapter navigation in
large articles. Prior permission to use subagents for the basis work was reused.
Parallel work covered service/client index, application staging/Unicode/tests,
compiled real-service measurements and independent review. Root integrated WPF,
stale-response regressions, docs and publication.

This is the same existing chapter selector and Previous/Next behavior in the
bounded page reader. The service returns at most 1,024 scalar CP anchors from
saved chapter metadata, with a 1 MiB response ceiling. Destination text comes
only from one 64-block / existing byte-bounded page. Converting the chosen CP
anchor to canonical UTF-16 after loading that page avoids inspecting all source
blocks just to build the index. Each jump stages privately between fresh metadata
fences, then publishes. Navigation changes no playback/resume/caret intent.

No architecture/security/licensing/dependency/schema change, live source rewrite,
editor-limit increase, paid/cloud requirement or networking configuration.
Continuous-only chapter editing, one-chapter display and current-chapter Find
remain continuous features; paged mode explicitly disables them. It does not
invent chapter boundaries or download a whole chapter. Folder moves require
reopening before another staged jump; metadata-only row-version changes before
the initial fence remain allowed if the source/folder did not change.

## Files and behavior

- New `reader_core/chapter_index.py` and SQLite adapter: one snapshot, saved
  marker validation and indexed scalar marker lookups. No block text, metadata
  or hashes, no document-wide source enumeration. At most three batches of 500
  marker IDs plus a first-block `LIMIT 1`. Explicit primary-key index hint avoids
  SQLite choosing a wide document-order scan for `IN` lookups.
- New service chapter GET route, public schemas, router registration and exact
  gateway allowlist. Authentication/privacy, expected revision and final
  synchronous access fences retain existing errors; malformed metadata yields a
  typed conflict, including corrupt whole-document JSON behind the privacy gate.
- New C# Client chapter DTO/GET transport and Application staged-navigation
  helper. Index/source identity validation, exact CP-to-UTF-16 mapping, private
  staging pager, before/after revision/deletion/folder/row-version checks and
  cancellation after each await. Same-block audible chapter selection converts
  offsets monotonically through source once instead of once per marker.
- New MainWindow paged-chapter integration and smoke. Existing toolbar now binds
  either continuous chapters or scalar paged anchors; index refresh is owned by
  client/document/load generation. Previous/Next disable at boundaries. Visible
  page and audible source update selection; chapter jumps scroll exact source
  offsets without altering audible/Find markers or caret intent. Source pointer
  scrolling is added to `SourceHighlightTextBlock`.
- MainWindow page/Find/term paths cancel or reject superseded chapter work.
  Chapter intents cancel old Find/term navigation while retaining completed Find
  results. Pending visible-pager work is cancelled before private staging.
- New core/API/client/application tests, actual WPF lifecycle assertion,
  compiled real-service checker extension, golden chapter response, contract
  checker and live status/plan/policy docs.

## Failures and review findings

- Initial App compile found a C# pattern/local variable name collision and one
  nullable smoke dereference. Both corrected; final builds have no warnings.
- Client validation test initially selected obsolete xUnit synchronous overload
  for a Task method; changed to awaited `ThrowsAnyAsync`, all seven tests pass.
- Reviewer found fresh folder changes could pass source-only checks and the old
  UI folder guard. Both fresh helper fences now reject folder changes; before/
  after-move regressions pass.
- Review identified repeated CP-prefix conversion in a many-marker single block.
  The helper now uses monotonic conversion; retained oracle/cursor tests pass.
- Reviewer found held older Find/term requests could overwrite a new chapter.
  Find generation/cancellation and term cancellation now transfer ownership,
  retain Find results and reject late errors. New Find/term/page intents also
  cancel pending chapter work at their start.
- The held-term WPF regression first failed with uncaught cancellation. Remote
  term navigation now handles owned cancellation/superseded errors. Review then
  caught a fallthrough into local navigation; an explicit return and regression
  preserving match index 17 prevent that state mutation.
- A delayed ordinary-page handler could resume with the pager's new Current
  page and cancel final chapter selection/scroll. It now captures the chapter
  generation and rejects obsolete continuations. A held page plus held overlay
  regression exercises the exact await boundary.
- That new regression initially withheld its fake page response until after
  awaiting the response: the first packaged lifecycle run timed out. The test
  release order was corrected, preserving the real held-response overlap.
  First failed checker output remains in
  `logs/paged-chapters-20261030/check-desktop-reader-first-failed.stderr.log`.
  Corrected dev lifecycle passes; final packaged check is recorded below.
- Initial new payload checker imported the route module and failed in the
  isolated checker environment (`document_import` was not on its schema-only
  path). Public response models moved to the existing schemas module; all 21
  exact payload fixtures now round-trip without expanding checker dependencies.

## Validation and measured acceptance

Windows substitution: `py -3` instead of Store-aliased `python3`; local .NET 10
SDK `%LOCALAPPDATA%\TTSPlatform\dotnet\dotnet.exe` instead of PATH SDK8.

- Full Python: **842 passed, 2 optional skips**, 106.19 seconds.
- Chapter core/API focused suite after the schema move: **49 passed**.
- Full .NET: **449 passed** (238 Application, 107 Client, 104 Windows).
  Includes 39 new Application and seven new Client cases.
- Release solution/App builds: PASS, zero warnings/errors. Final App rebuilt
  after navigation ownership/test changes; real WPF lifecycle passes.
- Scoped .NET whitespace verify: PASS. Full Ruff: PASS.
- Reader payload checker: PASS, **21** fixtures. Security defaults: PASS.
- Compiled isolated real-service chapter acceptance: PASS. Source is 2,182,414
  characters / 1,601 blocks with markers at 0/800/1,600. Index is **537 bytes**,
  **zero block GETs**. Each of four jumps uses one bounded block GET and two
  fresh metadata GETs; at most 64 blocks / 87,296 UTF-16 units retained. Zero
  position/playback/write calls; current visible page unchanged until commit.
- Initial observed index latency 9.82 ms, largest jump 15.17 ms. These are fixture
  measurements, not universal latency/process peak-memory bounds. Final checker
  evidence includes the unchanged earlier search/budget smoke assertions.
- Full `check_desktop_reader.py --require-dotnet --skip-build` after the test
  release-order fix: PASS. Portable WPF lifecycle includes real selector and the
  held old-page/overlay regression; live HTTP/WS, independent request budgets,
  source search, schema-11 preview integrity and packaging all pass. Final index
  9.45 ms / maximum chapter jump 13.79 ms, same 537-byte/one-page bounds.
- Exact root-shortcut self-contained win-x64 publish: PASS. Its isolated folder/
  edit-preservation and lifecycle probes (paged chapters, remote search, document
  switch, playback pause and tray disposal) all pass. Reader/service remain
  stopped. Audible/global clipboard/hotkey probes were skipped, not claimed.
- Final `git diff --check`, scoped .NET whitespace verification and Ruff: PASS.

Ignored evidence folders: `logs/paged-chapter-navigation-20261030` (independent
compiled acceptance) and `logs/paged-chapters-20261030` (full checker, failures,
isolated WPF and root-shortcut probes).

## Preserved state and remaining work

Local `models/MANIFEST.json` is excluded. SHA256 remains
`C0556F885B9AE3D881DDCB8A131B852263DCFC1045872F50F451CDAEC0C95DE8`.
No real article, private settings, credential, audio, clipboard or hotkey change.
The normal Reader/service remain stopped for the owner's relaunch. PWA, U8 and
audiobook production remain inactive. Next basis items are product part limits/
preview, chapter/edit metadata preflight and append-scaling measurements. It is
safe to continue that existing reliability backlog autonomously; no new product
direction or network access is implied.
