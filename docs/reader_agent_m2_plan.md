# Reader Agent M2: resumable multi-part imports and chapter access

## Target for 2026-11-01

The owner requested a short plan and an active goal for the five MCP improvements
reviewed in chat. M1 remains complete. This is an additive service/API/MCP slice;
the Python service remains the sole persistence and authorization owner. Work
through the stages below, committing validated slices. The date is a target,
not permission to skip acceptance or claim incomplete work is complete.

## Execution order

- [ ] **M2.1: Actionable busy responses.** Preserve distinct rate-limit,
  playback-lock and database-busy reasons through MCP. Forward validated,
  bounded retry timing and budget identity when supplied by the service. Keep
  existing outcome/code/retryable compatibility where required; never invent
  a retry deadline for a playback lock or automatically replay ordinary writes.
- [ ] **M2.2: Retry-safe creation and part planning/delivery.** Add durable
  creation identities so a lost response or concurrent retry creates one part.
  Provide a configurable, bounded preview with a 900,000-character default;
  count final normalized text, headings, introduction and separators in both
  Unicode code points and UTF-16 units. Check block, per-write and chapter/edit
  metadata limits before mutation. Split only between complete chapters; reject
  an oversized individual chapter explicitly. Delivery must revalidate the
  preview's inputs/revisions and select/create parts deterministically. A chapter,
  receipt and part assignment commit atomically; interrupted multi-part work
  resumes without duplicates, empty orphan parts or false completion. No claim
  that the whole import is one transaction.
- [ ] **M2.3: Folder-scoped story status.** Return bounded, paginated part and
  chapter delivery status across a stable story identity. Protect against
  duplicate delivery into different managed parts under concurrency. Distinguish
  delivery receipts from current text after Undo/manual edits; report numeric
  discontinuities as observations, not proof of missing prose. Existing M1
  articles/history remain readable and unchanged; any legacy association or
  conflict requires an explicit, documented compatibility policy.
- [ ] **M2.4: Chapter text and passage search.** Add bounded, revision-pinned
  chapter reads and literal in-article search with paginated results. Resolve
  chapter text from current structure rather than treating receipts as text
  anchors. Return explicit unavailable/changed results when an edited chapter
  cannot be resolved safely. Reuse existing service search where appropriate,
  without granting access to broader owner endpoints.
- [ ] **M2.5: Integration and publication.** Update API/MCP/import contracts,
  workflow status and isolated Windows smoke. Validate and commit/push the
  completed slices; report runtime deployment separately from source completion.

## Acceptance

- Boundary fixtures cover exact fit/overflow, non-BMP characters, headings,
  normalization, oversized chapters and metadata exhaustion. Recombined story
  text must match the prepared source exactly, with documented wrapper handling.
- Lost responses, process restart, concurrent retries and injected commit failures
  prove safe creation, rollover and chapter assignment. Changed payloads or
  stale previews conflict rather than silently overwrite or repartition.
- Story pagination, chapter reads/search, retries and all new identities preserve
  folder scope, revocation, moves/deletion/privacy denial, leases and versions.
- Busy results preserve allowed reasons/timing without leaking response bodies,
  credentials or source text. Agent saturation cannot consume playback budgets.
- Real stdio MCP and isolated Windows Reader smoke demonstrate bounded parts,
  visible chapter navigation, exact complete text readback and coherent status.
  Checksums alone do not replace full readback acceptance.
- Run `py -3 -m pytest -q`, optional agent-environment tests,
  `py -3 -m ruff check .`, Reader contract checks and relevant .NET/build/format
  checks when desktop/shared contracts change. Use synthetic temporary storage;
  report failures and skipped/manual acceptance honestly.

## Boundaries and execution notes

No live story imports, rewriting/deleting existing parts, service restart,
playback interruption, grant expansion, networking/U8, website fetching,
scheduler, cloud dependency or audiobook work is included. Preserve the owner's
local `models/MANIFEST.json` modification. Runtime deployment that would disrupt
active Reader/service state requires a separate safe opportunity/authorization.

Start each stage by inspecting current contracts and recording additive schema,
permission and compatibility decisions before implementation. Small implementation
details may be decided locally; a major architecture/security/product change
requires returning to the owner. Optional bounded subagent reviews are authorized.

Chapter reads/search are sequenced after import reliability; this ordering does
not drop them from the goal. Product-wide import UI and retroactive library
repartition remain outside this MCP slice.
