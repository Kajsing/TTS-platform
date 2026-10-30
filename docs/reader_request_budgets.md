# Reader request budgets

Implemented 2026-10-30 for the existing Windows Reader and localhost service.
Playback and background traffic have independent, enforced sliding 60-second
budgets per client host. Folder-scoped agent traffic retains its separate shared
120/minute budget. Authentication, origins, privacy, content leases, revisions
and transactional capture/chapter receipts are unchanged.

## Configuration and classification

```toml
[limits]
requests_per_minute = 30          # Background work; existing configuration key.
playback_requests_per_minute = 120
```

The existing key now controls background work only. Existing local overrides
remain effective for that class. The new independent playback default covers
up to one heard-position save per second plus window reads/admission; it is
still a finite limit, not a throughput guarantee. Both settings must be positive
and support the normal `TTS_PLATFORM__LIMITS__...` environment override.
No local configuration file is rewritten. Restart the service normally to load
the new implementation; use the updated desktop client for isolated cooldowns.

| Budget | Operations |
| --- | --- |
| Playback | `POST /v1/tts`; Reader and TTS WebSocket admission; `GET /v1/reader/documents/{id}` and its `/blocks` and `/position`; `PUT .../position`; `POST /v1/reader/queue/advance/{id}` and `/queue/items/{id}/activate` |
| Background | Other protected HTTP operations: library/status/handoff polling, edits, captures, imports, exports, rules, agent-grant administration and asynchronous TTS jobs/status/results |
| Agent | Existing native-loopback folder-scoped `/v1/reader/agent/*` operations |

Public health/voice discovery retains its previous server policy. Route and
method select the budget; a client-supplied budget header cannot promote an
import or administrative operation. Unknown operations use the background
class. Document metadata/pages share playback's budget because they also serve
playback startup and ahead-of-playback windows; excessive document-window reads
can still exhaust playback. The route matrix is frozen in
`contracts/reader/request_budget_cases.json` and tested by Python and .NET.

## Rate responses and desktop behavior

HTTP 429 retains `error.type = rate_limited` and `Retry-After`. The service adds
`X-TTS-Request-Budget: playback|background|agent` and
`error.details.request_budget`. WebSocket errors carry the budget and
`retry_after_seconds` in the existing error details; the audio protocol version
and cursor/mark semantics do not change.

Desktop clients for the same service authority share separate playback and
background deadlines. A background 429 prevents further background calls while
playback remains available. The client honors both delta and date Retry-After,
never shortens an existing deadline and coordinates HTTP/Reader WebSocket
playback failures. Older services or gateways without a recognized budget tag
retain conservative shared cooldown behavior. U8's gateway still has its own
device limits; this work does not change its networking/security policy.

Each desktop HTTP budget allows at most two in-flight requests and sixteen
total in-flight/waiting requests across clients sharing that coordinator.
Waiting callers support cancellation and recheck cooldown after admission;
queued calls do not storm a service that has just returned 429. A full local
queue returns `reader_request_queue_full` (503) without sending the request.
Ordinary writes are never automatically retried. The existing durable capture
outbox keeps its own receipt-based retry policy.

## Validation and remaining scope

- Python saturation test seeds an isolated article over two million characters,
  exhausts 30 background calls plus 50 denied calls, fetches a bounded two-block
  page, saves 60 positions and completes two source-mapped stream windows.
  It also verifies playback enforcement, header-spoof rejection and independent
  agent admission. Clock/concurrency tests verify the Retry-After deadline.
- .NET tests cover the shared route matrix, independent deadlines, legacy
  fallback, cancellation, queue bounds/recovery and queued-call suppression.
- `py -3 scripts/check_desktop_reader.py --require-dotnet --skip-build` runs a
  real HTTP/WebSocket service with separate 8/20 limits and the compiled client:
  saturated background traffic permits metadata/pages, PCM/source spans,
  persisted resume and immediate WAV speech; playback itself remains limited.

The subsequent 2026-10-30 desktop call-coordination slice is documented in
`reader_document_calls.md`: metadata/read-window coordination and cancellation
are complete there, while broader service-byte/full-source bounds remain open.
The budget slice itself does not complete bounded document-load work, request coalescing,
page-based chapter navigation, configurable import parts, metadata preflight,
or append-scaling measurement. There is no new memory/latency benchmark or claim
that all historical audio faults are fixed. Real listening remains a field test.
