# Reader document/status coordination

User explicitly selected the next reliability item and permitted subagents.
Base main ac0a844; one document agent, one status agent and an independent read
reviewer worked on bounded ownership areas. Root integrated client read sharing,
measurement, validation and delivery. No runtime dependencies or HTTP contracts
were changed. Existing local MANIFEST SHA-256 remains
C0556F885B9AE3D881DDCB8A131B852263DCFC1045872F50F451CDAEC0C95DE8.

Implemented per-client overlapping safe metadata/health/capability/voice reads,
hashed full credential/privacy/URI identities, no completed HTTP cache, mutation
epochs and bounded waiter/identity groups. Fresh revision and activity reads
bypass sharing. Physical message lifetime is independent of each caller; only
the last cancellation cancels/retire its network work. Reviewer found that
shared block pages could cross external revisions, so block GET sharing was
removed and an ignored old-page/external-writer regression proves isolation.

Document loading reuses caller metadata, reads sequential bounded windows and
fresh final metadata, cancels superseded operations and keeps the old editor
until safe publication. Follow loads share a current candidate, reject late
responses and retire abandoned work. Empty/inactive/whitespace-only highlighter
terms avoid hidden whole-article loading. Active highlighter/Find retain full
source counts and share the existing revision cache after serialized/fenced
loading. Folder/library/handoff paths capture client lifetime, cancel and guard
after awaits. Busy handoff polling saves six GETs/minute at its 10s cadence.
Service Center uses exact bounded retry metadata; maintenance still fresh-reads.

Review caught three cancellation issues: rejoining an abandoned page, accepting
a cancelled final metadata reply and applying a highlight page after Pause or
workspace replacement. Guards and deterministic regressions were added. The
first integrated .NET run failed an old Find test double which did not implement
fresh document metadata; the fixture now supplies metadata without weakening
the production fence. Root's first LibraryPager regression used an init-only
test property after setup; changed the test fixture property to settable. The
desktop checker initially rejected replaced fixed-one-minute wording; its
source marker now accepts the actual Retry-After message. These failed checks
precede the passing integrated results below; they were not hidden by retries.

Passed: 689 Python tests / 2 optional skips; 386 .NET tests (99 Client, 183
Application, 104 Windows); zero-warning Release build; Ruff. Compiled desktop
checker passed live HTTP/WS edits/import/rules/chapters/capture and rate-budget
regression, SQLite preview schema11/integrity, portable packaging and WPF folder/
library-lifetime/tray/document-switch lifecycle checks. Real audio/global
clipboard/hotkeys were skipped. Evidence is ignored
`logs/document-calls-20261030/desktop-check.json` and its stderr log.

Measured live fixture: 2,182,414 characters, metadata-hint open = two GETs;
64 retained blocks / 85,946 source characters; eight overlapping capability
reads = one HTTP call; eight follow events = one page call. Initial load 31.74ms,
observed allocations 499,160 bytes (not peak RSS or a universal bound). WPF fake
fixture has 2,002,000 chars / 2000 blocks: inactive terms => one page of 64; active
highlighter => four pages of 500; following Find => zero additional block reads.

Broader service response-byte quotas/incremental active full-source operations
remain open, along with chapter navigation/part controls/metadata/append scaling.
That distinction is explicit in Plan.md; this does not mark the whole original
large-document item complete or activate PWA/U8/audiobook work.
Exact shortcut deployment and final source delivery are recorded below.

Published the exact existing root Reader shortcut target under
`apps/desktop_reader/src/TtsPlatform.Reader.App/bin/Release/net10.0-windows/win-x64/`.
Its hidden isolated folder/library-lifetime and lifecycle/document-switch/
pause-viewport probes exited 0 with passing markers under ignored
`logs/document-calls-20261030/shortcut/`. Scoped .NET whitespace verification,
20 payload contracts and security-default checks pass. Production Reader and
port7777 listener remain stopped. MANIFEST hash is unchanged; no local config,
articles, playback positions, networking or autostart were modified.
