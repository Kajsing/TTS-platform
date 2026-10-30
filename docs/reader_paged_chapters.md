# Chapter navigation in paged articles

Implemented 2026-10-30 for the existing large-document reliability backlog.
The same chapter selector and Previous/Next chapter buttons now work in the
bounded page-based reader, including editable articles above the continuous
editor's existing 1,000,000-character / 20,000-block limits.

## User behavior

Choosing a chapter opens only the bounded page starting at its source block and
scrolls to the exact anchor inside that block. Previous/Next use chapter order;
the first/last buttons disable at the ends. Normal page navigation and audible
source following keep the selector aligned with visible source. Mid-block
boundaries use their exact offsets, including emoji. Navigation is separate from
playback: it starts no sound, seeks no active stream, writes no resume position
and preserves Start-at-cursor intent. Follow reading can subsequently bring the
view back to the current audible source. Pause retains the current marker/view.

The page may continue into another chapter. It is not a full-chapter download or
a new chapter-only playback mode. One-chapter editing, chapter mutation tools
and current-chapter Find remain continuous-editor features; their controls are
disabled in paged mode with the page behavior explained. Existing local chapter
editing and unsaved drafts retain their previous semantics. Canonical
`chapter_markers_v1` boundaries are used; an article without markers has the
existing implicit first chapter. No new heading detection or source rewrite.

Failed or stale jumps preserve the previous page and selected chapter. A block
that exceeds the existing reading limit returns an actionable size error; its
text is never truncated. Old-service/malformed-index errors make chapter
navigation unavailable without falling back to downloading the article.

## Public read contract

`GET /v1/reader/documents/{document_id}/chapters?expected_content_revision=N`
requires a positive expected revision, owner/device authentication, the existing
folder privacy session and the background request budget. It returns:

```json
{
  "document_id": "document-id",
  "content_revision": 3,
  "chapters": [
    {
      "id": "root",
      "title": "Chapter 1",
      "block_id": "block-id",
      "block_ordinal": 0,
      "codepoint_offset": 0
    }
  ]
}
```

These are explicitly **code-point anchors**, matching saved chapter metadata;
they are not UTF-16 `ReaderCursor` values. WPF converts the chosen anchor to a
canonical UTF-16 cursor using only that loaded destination block. Source
identity uses block IDs as well as ordinals; the revision belongs to the index.
The golden response is `contracts/reader/chapter_index.response.json`.

The service reads one SQLite snapshot of document metadata and scalar block
identity/ordinal/character counts. It never reads block text, block metadata or
hashes to build the index, nor enumerates every article block. At most 1,024
markers are accepted; one indexed `LIMIT 1` resolves the first block and at most
three primary-key lookups in batches of 500 resolve remaining marker IDs.
The explicit index hint prevents SQLite choosing a document-wide scan for a wide
`IN` expression. Exact UTF-8 JSON response size is capped at 1 MiB. Existing
chapter/write metadata limits remain independent and unchanged.

Absent markers yield the implicit root (or an empty index for a blockless
article). Explicit malformed metadata, foreign/missing block IDs, duplicate IDs
or positions, out-of-range offsets and unordered anchors return typed 409
`reader_chapter_index_conflict`. Source and metadata are not normalized or
repaired during reads. Revision/deletion conflicts retain typed failures;
oversized indexes return 413. Privacy checks retain 423 and run before access,
after threaded work and synchronously immediately before returning the response.
Even malformed document JSON cannot bypass folder privacy or cause a raw 500.
The existing private gateway allowlist admits this GET only; no gateway/network
configuration is activated.

## Safe staged navigation

Each jump uses a private staging pager and this sequence:

1. Fresh document metadata; verify source revision, availability and original
   folder ownership.
2. One exact-ordinal bounded page (at most 64 blocks, under the existing 2 MiB
   reading-response cap); verify the block ID and code-point anchor and convert
   it to UTF-16.
3. Fresh metadata again; reject revision, row-version or folder changes across
   the page read. Only then publish the staged page in the visible pager.

Cancellation is checked after every await. Document/workspace/client/index/page
ownership is checked before publication and again after asynchronous rendering.
A later chapter, page, Find, term jump, clear or audible follow supersedes older
navigation. Chapter requests cancel pending Find/term navigation while retaining
completed Find results. Delayed successes and failures cannot scroll or overwrite
a newer page; cancelled remote term navigation cannot fall through into local
editor navigation. Chapter selection by audible cursor uses a monotonic
code-point conversion through the current block, avoiding a separate full scan
for every marker.

## Verification and limits

The compiled client used the isolated 2,182,414-character, 1,601-block fixture
with chapters at blocks 0, 800 and 1,600. The **537-byte index fetched zero source
blocks**. Four first/next/previous/last jumps each made **one block GET and two
fresh metadata GETs**, retaining at most 64 blocks / 87,296 UTF-16 source units.
There were zero position, playback or write calls. The final full-check run took 9.45 ms
for the index and at most 13.79 ms per jump; these are fixture observations, not
universal latency or process-memory bounds.

The WPF lifecycle probe requires `paged_chapter_navigation`, exercising the real
selector, Previous/Next, mid-block emoji anchors, pause/caret preservation,
oversized/stale/moved destinations, competing chapter/Find/term jumps and late
index replies after workspace clear. Application tests cover invalid wire data,
revision/deletion/folder/row-version fences, ignored cancellation and Unicode.
SQLite authorizer/query-plan tests prove source columns are not read and work
depends on marker count. API tests exercise auth/device origin/privacy and final
relock/move/revision/response-limit fences.

This slice adds no dependency, migration, live article repartition or editor-cap
increase. Product import-part limits/preview, independent chapter/edit metadata
preflight and append-scaling measurements remain separate backlog work. PWA,
U8 and audiobook production remain parked.
