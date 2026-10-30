# Bounded Reader pages and source search

Implemented 2026-10-30 for the existing Windows Reader reliability backlog.
Python owns canonical source and search execution; WPF receives positions and
counts for paged articles. Continuous editing still searches its current local
text, including unsaved changes. No database migration or new dependency is
required. This does not activate PWA, U8 or audiobook production.

## Complete block pages

`GET /v1/reader/documents/{document_id}/blocks` retains its block-count limit
and now also enforces `reader.max_block_page_bytes` (default **2 MiB**) against
the exact UTF-8 JSON response, including metadata, escapes and the envelope.
One source block may contain at most **1,000,000 Unicode code points** on this
public reading path. These are separate bounds: neither counts UTF-16 units.

SQLite first reads bounded scalar summaries, checks the persisted character
count before inspecting text sizes, and admits only a raw UTF-8 budget of text
and metadata. Hydration shares one explicit read snapshot. Serialization then
admits only complete blocks under the exact response-byte budget. The last
included ordinal becomes the continuation; a shorter page must not be treated
as end-of-document when `next_after_ordinal` is present.

If the first block cannot fit, the service returns typed HTTP 413
`reader_block_too_large` with safe size/ordinal details. Source is never shortened
or rewritten. Reader preserves the previous page and explains how to split the
source into smaller blocks and reimport it. Search navigation tries its context
page, then starts directly at the destination if the byte cap excluded that
block. It still fails explicitly if the destination itself is oversized.

This is a public reading-response bound, not a new import/write/audio/export
limit. Internal repository reads used by those operations remain unchanged.
Fragments of a single oversized source block are not implemented. Authentication
and privacy are checked before reading and again after threaded serialization,
including relock/movement into a locked folder during the read.

## Positions-only search contract

All routes use owner/device authentication and the existing document privacy
guard. Queries are POST bodies, never URL parameters. The local service and
private gateway reject bodies above **16 KiB** before parsing/forwarding them.
The gateway retains its separate upload allowance. Search consumes the existing
background request budget; it cannot borrow playback allowance.

| POST document-relative route | Request | Response |
| --- | --- | --- |
| `search` | expected content revision, query, case/whole-word/regex flags, max results | session summary, count, truncation, failure, regex dialect |
| `highlights` | expected content revision and global highlighter row version | session summary and per-term counts |
| `search/{search_id}/results` | offset, limit | indexed positions and next offset |
| `search/{search_id}/window` | inclusive start/end block ordinals, limit | only intersecting positions; explicit truncation |
| `search/{search_id}/next` | term ID, previous global match index | next term position, wrapping at the end |

Each hit contains its global UTF-16 start/length and start/end canonical
`ReaderCursor` values, including block ID, ordinal and content revision. Results
contain no source excerpts. The canonical projection uses the same CRLF-CRLF
separator and empty-block cursor rules as `ContinuousDocumentText`; matches may
cross blocks and emoji without changing source offsets. Overlay ranges are
clipped to the visible source blocks in WPF.

Create/read/navigation recheck revision, privacy and, for highlights, the saved
configuration version. Result encoding happens off the event loop and is followed
by fresh revision/configuration/privacy fences. Stale requests return typed 409;
expired/evicted sessions return 410; locked content retains the existing 423.
Reader invalidates expired positions and asks for a new search. Cancellation,
workspace/document/page generations and client ownership guard both successful
and failed asynchronous continuations. An older service returning 404 gets a
clear failure; there is no full-article download fallback.

## Work, storage and response limits

Search scans **one bounded full snapshot in the service**. Arbitrary regex is
not approximated independently per page or streamed over disconnected windows.
The client avoids full-source transfer; the service still materializes source
within these explicit limits.

| Resource | Limit |
| --- | --- |
| Canonical source including separators | 32,000,000 UTF-16 units / 100,000 blocks |
| Source preparation, scan and index deadline | 8 seconds total |
| Literal/regex/highlighter scan budgets | 2 seconds / 200 ms / 2 seconds |
| Concurrent scans | 1, with immediate background-tagged 429 + `Retry-After: 1` when busy |
| Find results / highlighter results | 10,000 / 250,000 indexed matches |
| Result page / visible overlay window | 1,000 / 2,000 positions |
| Search response | 1 MiB exact UTF-8 JSON |
| Search sessions | 4, with 300,000 aggregate indexed matches, LRU eviction |
| Session expiry | 300 seconds idle, renewed by successful access |
| Pattern / term / term count | 1,024 UTF-16 units / 200 UTF-16 units / 200 terms |

SQL preflight visits at most 100,001 scalar block rows and rejects count/character
excess before text hydration. A SQLite progress handler, per-block/engine/index
checks, disconnect observer and shutdown event bound abandoned work. Completed
sessions retain maps, positions and counts, not query strings or source text.
Empty Find and inactive/blank highlight configurations skip source hydration.

Counts are exact for a completed, nontruncated index. At a result cap, counts
describe only the retained matches and `truncated` is true. Visible-window
truncation does not discard full-index counts. HTTP encoding may shorten a
result page further; it preserves the correct next offset. A single response
that cannot fit fails explicitly. Oversized sources, timeouts, invalid patterns,
unsupported syntax and cancellation produce explicit failures, not guessed
partial success. Requests and query text are absent from search logs; metrics
use route templates instead of document/search IDs or raw paths.

## Matching behavior

Literal Find keeps the desktop ordinal, case-insensitive and whole-word behavior.
A local .NET 10.0.11 oracle checked all 2,881 Rune case pairs without a literal
search difference; a representative Unicode fixture preserves edge cases.
This is measured compatibility, not a promise for all future Unicode runtimes.

Service regex and Word Highlighter identify the existing Python `regex` package
in VERSION0 mode as **`regex-v0`**. Local continuous-editor regex remains .NET.
Some case behavior differs (for example dotted I and final sigma). Paged Find
shows the provider in its tooltip. Common incompatible .NET/provider-specific
constructs fail as `unsupported_regex`; full .NET dialect equivalence is not
claimed. Regex uses a bounded whole snapshot so cross-block matches are genuine.
Highlighter retains longest-first nonoverlap, configured order tie-breaking,
per-term counts and server-side next-term navigation.

## Verification

The compiled .NET client exercised an isolated real service with a 2,182,414-
character, 1,601-block document. Opening retained 64 blocks / 85,946 characters
with two GETs. Find returned 50 deliberately capped hits; a regex spanning the
first separator mapped `block 0:0` to `block 1:9`. Highlighter found 104,000
`Synthetic paragraph` matches and zero shorter nested `paragraph` matches.
Its visible window returned 2,000 positions with truncation. Navigation to match
103,999 fetched exactly one bounded block page. Search/highlighting itself made
**zero block GETs**, and the largest of seven search responses was **906,085
bytes**. The final full-check run took 59.27 ms for Find and 541.24 ms for highlighting;
these are fixture measurements, not universal latency or peak-memory guarantees.

`scripts/check_desktop_reader.py --require-dotnet --skip-build` also requires
real WPF lifecycle assertions for remote paged Find/highlight windows. Held
responses test document/workspace replacement, stale failures, expired sessions,
revision mismatches, byte-shortened context pages and oversized destinations.
Python tests cover exact block budgets/continuations, SQL preflight, cross-block
UTF-16 mapping, timeout/regex/Unicode cases, request/response bounds, busy/expiry/
shutdown behavior, log redaction and final revision/privacy/configuration fences.

Page-based chapter navigation, product import-part controls, independent
chapter/edit metadata preflight and append-scaling measurements remain separate
backlog items. Larger-than-limit source search and displayable fragments of a
single oversized block would require an additional explicit contract.
