# Reader Agent M2 contracts

M2 adds tools to the existing native-loopback, folder-scoped API. The adapter is
1.1.0; workspace contract 1 remains additive and exposes a `features` list.
Discover tools/capabilities rather than assuming a running M1 service has M2
routes. The service owns all data and checks existing permissions on every call.
No database access, website fetching, scheduling or broader owner credential is
needed. Setup remains in [reader_agent_mcp.md](reader_agent_mcp.md).

## Busy results and creation

The existing MCP `outcome: busy`, `code: reader_busy`, `retryable: true` remain.
An allowlisted `reason` distinguishes `rate_limited`, `reader_document_locked`
and `reader_database_busy`. Valid supplied delays become integer
`retry_after_seconds` (0..86,400, rounded up); HTTP delta/date `Retry-After` and
numeric service details are supported, choosing the longer valid delay. An
unambiguous allowlisted `request_budget` may be included. Raw messages/details
are never forwarded. Playback locks have no guessed deadline or budget.
No operation is automatically retried by the adapter.

`reader_create_article_once(title, text, retry_key)` uses `POST /articles` with
optional `retry_key`. An ordinary call without a key retains M1 semantics.
The key is unique within the granted folder, survives grant renewal and binds
the exact supplied title/text. Lost-response or concurrent replay returns the
same article's current metadata; changed payload conflicts. Replay neither
reverts edits nor restores removed text. Moved/soft-deleted targets are denied.
Normal owner physical purge cascades standalone creation identities.

## Managed whole-chapter imports

The following routes are relative to `/v1/reader/agent`:

| MCP tool | HTTP | Required existing permissions |
| --- | --- | --- |
| `reader_preview_import` | `POST /import-plans` | `list`, `create`, `deliver` |
| `reader_deliver_import_chapter` | `POST /import-plans/{plan_id}/chapters` | `list`, `create`, `deliver` |
| `reader_story_status` | `GET /stories/status` | `list`, `chapters` |

Preparation takes `title`, optional `intro`, a stable preview `retry_key`,
`chapters` and optional `max_characters`/`max_blocks`. Each chapter has the M1
delivery fields, including story/chapter/retry identities, source URL, title,
text and optional ordering; no expected article version is needed at this stage.
Every chapter in a batch must have the same story identity and unique chapter
and retry keys. Include any spoken chapter heading in its text.

The default cap is **900,000** final normalized Unicode code points **and**
UTF-16 units. The configurable range is 1..1,000,000; block limits are 1..20,000.
Each part begins with normalized `title + optional introduction`, followed by
whole normalized chapter texts joined by two newlines. Counts/hashes include
these wrappers, headings and separators. Article titles receive a part suffix;
that metadata suffix is not an extra spoken heading. The chapter's `title` is
structural/provenance metadata, as in M1. No prose is silently truncated or split.

Preparation conservatively checks document, block, per-write, chapter-marker and
64 KiB edit/marker metadata bounds, including UUIDs and before/after snapshots.
A metadata constraint may create a smaller part. A complete chapter that cannot
fit alone with its wrapper fails before library mutation. Limits also include:

- At most 100 chapters per preview, 200,000 source characters per chapter and
  2 MiB UTF-8 JSON per HTTP write; the adapter checks encoded request size too.
  The pure planner additionally bounds source input to 4 MiB. Send successive
  bounded batches rather than one unbounded story request.
- At most 256 retained plans per folder, including completed plans. Replays of
  an existing plan still work at the quota. No automatic deletion/cleanup is
  exposed. Part ordinals stop at 999,999.

The preview returns `plan_id`, `story_key`, `base_story_version`, `next_index`,
`chapter_count`, `policy`, `parts` and `outcome` (`prepared`/`already_prepared`).
Each part contains its number/title, chapter keys, code-point/UTF-16/block counts,
conservative maximum append metadata bytes and final normalized text SHA-256.
Only wrapper, fingerprints and bounded manifest/assignment metadata are stored;
chapter bodies are supplied again at delivery. Preview registration changes no
library article. Reuse the same preview key and payload after an uncertain call.

Delivery takes `{plan_id, chapter}` in MCP and `{chapter}` on its plan HTTP route.
Send exact prepared payloads in order. Creation of a new part, its first append,
receipt, assignment and progress commit together. Each later chapter is also
atomic; the entire batch is not one transaction. A response includes plan/story/
chapter/document identities, `part_number`, `next_index`, `chapter_count`,
`complete`, receipt and `outcome`. Replaying committed delivery acknowledges
history, including after Undo; it never puts owner-removed text back.

Every batch starts **new parts**, leaving earlier parts unchanged even if they
have spare capacity. Continuation numbers follow managed part ordinals or the
number of accessible legacy story articles. Legacy receipts remain unmanaged;
they are not adopted, repartitioned or relabelled. Their delivered chapter keys
block duplicate new imports. Once a story is managed, new M1 deliveries also
honor cross-article duplicate protection and advance its delivery version.

Competing plans, changed payloads, changed target row versions or changed lease
targets conflict. Existing targets acquire the ordinary playback mutation lease
before the database transaction; a target creation race cannot bypass it.
Prepare a new batch of remaining chapters after deliberate reconciliation rather
than silently rebase. Managed part moves/soft deletion fail closed. If physical
purge cascades receipts, durable plan progress prevents recreation of that story
through an old plan or a new preview. Owner cleanup is not an agent operation.

## Story status and current content

`reader_story_status(story_key, offset=0, limit=50)` returns up to 100 receipts
with current scoped article metadata, managed flags/part numbers, `story_version`,
`next_offset`, and observed numeric ordering discontinuities. Discontinuities
include the previous page boundary; they do not establish missing prose.
`append_only_receipts: true` and `current_text_verified: false` explicitly
separate historical delivery from content still present after edits/Undo.

Status pages are live per-call transactions, **not a multi-call snapshot**.
Compare story versions to notice new deliveries and restart after known changes.
Owner moves/removals can change visibility without advancing the delivery version.
Do not use receipt counts or hashes as a replacement for full content readback.

| MCP tool | HTTP suffix on `/articles/{id}` | Result |
| --- | --- | --- |
| `reader_list_content_chapters` | `GET /content-chapters` | Current structural chapter IDs/titles/anchors |
| `reader_read_chapter` | `GET /chapter-text` | Current chapter text page |
| `reader_search_article` | `GET /search` | Literal matching text positions |

These require existing `read` permission and a positive `expected_row_version`
on **every** call. Structural chapter IDs are separate from durable receipt IDs.
Discovery uses offset/count pagination; chapter text uses chapter-relative
code-point offsets and at most 20,000 characters per page. Canonical separators
belong to the preceding chapter so concatenating all chapters exactly reproduces
the article. Stale versions, absent markers or invalid structure fail explicitly.

Search takes `query` (1..200 nonblank characters), `offset` and `limit` (1..100).
It is case-sensitive literal search, supporting overlap and paragraph boundaries;
no regex runs. Results contain code-point `offset`, `end_offset` and matching
text. Each call scans at most 100,000 candidate starts plus query lookahead.
Follow `next_offset` even after an empty result page; it is a text offset, not a
result count. Sources are capped at 32 million code points / 100,000 blocks;
chapter metadata parsing is bounded and source hydration uses SQL substrings.

## Validation and deployment

Migrations 012/013 are additive, checksum-tracked service migrations. Upgrade
existing storage only during a normal service restart; no live library rewrite
or running-service restart is part of this development slice. Publish test
binaries with `--artifacts-path` as well as `-o`, so build intermediates never
target the running Reader's locked application directory.

The extended `scripts/check_reader_agent.py` checks real stdio, protected Windows
credentials, process restart, exact multi-part readback, default 900k policy on
over two million synthetic source characters, chapter discovery/read/search,
ordinary WPF chapter selection and source-mapped stub speech, then revocation.
It uses temporary storage/non-default loopback ports and paces agent calls below
the existing 120/minute limit. It does not listen through a real audio device or
prove universal performance bounds. See `.logs/2026-11-01-reader-agent-m2.md` for
the actual run results and remaining runtime deployment status.
