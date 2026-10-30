# Reader document and status call coordination

Implemented 2026-10-30 after independent request budgets. This slice reduces
redundant desktop work while preserving fresh revisions, service activity,
privacy, content leases and heard-position semantics. It adds no HTTP routes,
schema migration or runtime dependency.

## Read ownership and freshness

- One `ReaderServiceClient` shares overlapping health, capability, voice and
  document-metadata GETs with the same complete request identity. Credentials,
  privacy sessions, URI and result type are part of a hashed in-memory key.
  Different clients/transports do not share reads. No completed/error HTTP
  response cache is kept. Writes separate read generations before/after sending.
- Every logical caller owns its cancellation. One cancelled waiter leaves the
  other readers intact; abandoning the final waiter retires and cancels the
  physical read. Groups have at most sixteen waiters and the registry at most
  thirty-two pending identities. Existing per-budget HTTP admission still applies.
- Fresh revision checks use `GetDocumentFreshAsync`, bypassing overlapping
  metadata reads. Block pages are deliberately excluded from the HTTP sharing:
  an old delayed page must not be reused after an external writer changes the
  source. Service activity/maintenance and saved-position reads remain fresh too.

## Document and viewport work

`ReaderDocumentLoader` accepts an already-read metadata snapshot from library,
handoff or playback checks, avoiding another initial metadata GET. It still
validates fresh metadata after all pages, retries at most twice and reuses the
failed attempt's final metadata. Pages remain sequential; character accounting
is incremental. Cancellation is checked around every network await, including
the final metadata fence, before anything is published.

Ordinary continuous editing retains its 1,000,000-character/20,000-block limits.
Large/structured article opening reads one 64-block window. Superseded document,
workspace, close and privacy-clear work is cancelled. The old visible editor is
kept until a complete valid replacement is ready. Library/folder refreshes also
capture their client/pager and check cancellation/ownership after every await.

Overlapping follow events use one pending reading window while it covers their
target. New navigation invalidates that window; late/out-of-order replies cannot
replace Current. A fully abandoned request is not reused even if its transport
ignores cancellation. Highlight continuations recheck playback/run, pager,
revision, document-load generation and latest-highlight sequence after awaiting,
so a delayed page cannot scroll a paused or replaced view.

No active nonempty Word Highlighter terms means no whole-source download.
Explicit Find and active highlighting retain full-article matching/counts. Their
existing revision cache is shared after serialized loading and fresh final
validation; invalidation prevents late cache publication. This application cache
is distinct from HTTP read sharing. These full-source operations still load the
whole article; they are not server-side incremental search.

## Polling

Browser handoff polling is skipped while playback/transition, edits or document
operations make opening unsafe. At the configured ten-second cadence this avoids
six background GETs per minute throughout those busy periods. Checks also run
after awaits, and poll/read/open/ack remain bound to the original workspace.
Switch/close cancels the old sequence without acknowledging through a new client.

Service Center already serialized monitor ticks, so it retains truthful polling
and fresh activity checks before maintenance. It now schedules the actual
bounded `retry_after_seconds` instead of adding a fixed 65-second wait.

## Measured isolated evidence

`py -3 scripts/check_desktop_reader.py --require-dotnet --skip-build` runs the
compiled client against an isolated loopback service with synthetic source:

| Observation | Result on 2026-10-30 |
| --- | --- |
| Source article | 2,182,414 characters |
| Open using supplied metadata | 2 HTTP calls: one page and one fresh fence |
| Retained initial source | 64 blocks / 85,946 characters |
| Eight overlapping capability reads | 1 physical HTTP call |
| Eight overlapping follow events | 1 page HTTP call |
| Observed initial load elapsed | 31.74 ms |
| Observed client allocations during load | 499,160 bytes |

Timing and allocations describe this fixture/run; allocations are not peak RSS
or a universal memory/latency bound. The WPF lifecycle probe separately opens a
2,002,000-character/2,000-block article with empty, inactive and whitespace-only
highlighter terms and verifies exactly one 64-block page. Active highlighting
reads four 500-block pages; subsequent Find reuses the same revision without
another block read. Fake held responses exercise external cancellation,
workspace replacement and late UI delivery without private data or real audio.

## Remaining work

This does not add service response-byte quotas or incremental full-source
Find/highlighter execution. A single large source block can still make a block
page large; a block-count limit is not a byte limit. Existing position-save
throttling and immediate terminal flushes remain intact. Page-based chapter
navigation, import-part controls, metadata sizing and append-scaling measurement
remain separate unchecked tasks. PWA, U8 and audiobook production stay inactive.
