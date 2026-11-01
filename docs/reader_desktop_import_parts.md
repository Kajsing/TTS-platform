# Desktop whole-chapter import preview

## Scope activated 2026-11-01

**Status: implemented, validated and deployed 2026-11-01.** Single-file and batch
preview/commit, the normal root-shortcut runtime and the localhost service are
updated. Benchmark findings are in [reader_append_benchmark.md](reader_append_benchmark.md).

The owner selected append measurements, plan cleanup and desktop import preview,
and allowed Reader downtime while away. Implement a coherent single-file and
multi-file workflow: preview proposed parts, chapter ranges and character counts
before saving; default 900,000 code points and UTF-16 units per part. Retain the
existing local service ownership, authorization, privacy and import limits.

## Local design choices

- Reuse parsed, expiring service previews rather than upload chapter prose through
  MCP or invent agent grants for the owner UI. Reuse the shared PartPolicy limits.
- The user explicitly selects an import heading level (default 1). Structured
  sections at that level define chapter boundaries; a preamble is retained as a
  chapter. Unstructured text remains one chapter. Never guess boundaries from
  ordinary paragraphs or silently split a chapter that exceeds a bound.
- Show maximum characters, heading level, part title/range and normalized counts.
  Policy changes invalidate the reviewed plan. Source/title/language/copy-option
  changes require a fresh source preview. Saving requires a current valid plan.
- Plan hashes pin source and policy. Commit rechecks the plan, duplicates and
  destination privacy. All parts of one file are created in one transaction;
  a failed file leaves no partial parts. Separate files retain separate outcomes.
- Preserve block text/kinds, source identity and section ancestry. Counts include
  all canonical paragraph separators. Concatenating part texts with the removed
  boundary separator must reproduce the original canonical source exactly.
  Titles are article metadata; do not add spoken wrappers to imported files.
- Create real chapter markers so normal Reader chapter navigation works.
  Conservatively preflight marker metadata/history bounds. An oversized chapter
  produces an actionable preview issue and disables commit.
- Batch import has separate preview and import stages; reviewing never saves.
  Keep acknowledged results on cancellation/failure and mark uncertain writes
  as unknown. Do not automatically retry a possibly committed write.
- Keep a managed original at most once per file, cleaning it up if the database
  transaction fails. Retained preview source bytes and text remain bounded.

## Public owner endpoints

`POST /v1/reader/imports/{preview_id}/parts-preview` accepts
`{max_characters:900000, heading_level:1}`. Result fields: preview_id, plan_key,
max_characters, heading_level, chapter_count, parts, can_commit and issues.
Part fields: number, title, first_chapter, last_chapter, chapter_start_title,
chapter_end_title, codepoints, utf16_units, blocks and text_sha256.

`POST /v1/reader/imports/{preview_id}/parts-commit` additionally takes plan_key,
allow_duplicate and folder_id; returns `{documents:[...]}` using ordinary Reader
document projections. Existing single-document and MCP routes remain supported.
Both routes use normal protected owner authorization; no new remote exposure.
The U8 gateway explicitly denies these new local-desktop routes. Its legacy
import contracts remain unchanged; remote part-preview support needs a separate
review before promotion. No private-network feature is activated here.

## Acceptance

Exact-fit/overflow/non-BMP, explicit heading levels, preambles/unstructured input,
oversized chapters, text reconstruction, current chapter markers, stale plans,
expired previews, duplicates, privacy and atomic failure must be covered. Test
single-file and batch review/commit separation, option invalidation, cancellation
and uncertain results. Build and verify actual WPF preview/part selection and
post-import chapter navigation against an isolated service before deployment.
Run relevant Python/.NET tests, full regression suites, Ruff, shared payload
checks, .NET format/build and Windows smoke; document outcomes and failures.

Append measurement is observation only: it must report evidence before any
optimization. U8, PWA, PDF, backup/release and audiobook are not activated.

## Verification and operational behavior

Run the isolated Windows check using the optional MCP environment already used
by the shared service/desktop smoke helpers:

```powershell
.venv-agent\Scripts\python.exe scripts/check_reader_import_parts.py --reader-exe apps/desktop_reader/artifacts/reader-desktop-parts/publish/TtsPlatform.Reader.App.exe --artifacts apps/desktop_reader/artifacts/reader-desktop-parts/smoke
```

Actual WPF controls exercise source refresh, policy changes, oversized chapters,
single-file confirmation, batch review and commit. The test gates a pending old
preview deletion and confirms a competing refresh cannot take ownership. It then
reads every committed part through public APIs and exactly reconstructs all three
synthetic input files. Imported Markdown is read-only structured content and uses
the ordinary paged chapter selector; it does not need the continuous editor.
Screenshots and results are retained under ignored desktop artifacts.

Limits: 1..1,000,000 selected characters, default 900,000; 20,000 blocks per part,
at most 1,024 source chapters and 100 parts/file; up to 100 files per batch.
Each preview response is capped at 1 MiB and source previews expire after ten
minutes. Retained original bytes share the configured single-file byte budget;
retained text shares the existing document-character budget. Re-preview an expired
file. Cancellation before saving creates no documents; loss/corruption of a save
reply can leave a committed file and is shown as unknown. Inspect the library
before a deliberate retry; the client never automatically replays these writes.

Full regression: 1,062 Python passes / 3 optional skips, 139 optional-agent/part/
benchmark passes, 479 .NET passes; Ruff, 21 payload contracts, scoped formatting
and zero-warning publish. M2 stdio/Windows regression also passed after the shared
transaction extraction. Runtime deployment and preserved live article versions
are recorded in `.logs/2026-11-01-reader-desktop-import-parts.md`.
