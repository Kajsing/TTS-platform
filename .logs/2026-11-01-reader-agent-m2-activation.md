# 2026-11-01: Reader Agent M2 runtime activation

The owner explicitly requested service restart and MCP reconnection after M2.
No feature code changed in this activation slice.

## Execution

- Verified old service PID 43372, its Python parent and Reader-owned PowerShell
  launcher PID 32160 against the recorded `service-process.json` lease.
- Public health reported schema 11, healthy voice/backend and no active streams.
  The service-control status then confirmed zero active requests, streams,
  content leases, exports and jobs before maintenance.
- Computer Use could read/activate Reader but both permitted input attempts
  failed with `coordinate input geometry is unavailable`. No UI mutation was
  observed. Switched to the existing service-control classes, not raw process
  termination or a replacement control protocol.
- An ignored headless .NET runner invoked the production LocalServiceCoordinator
  and LocalServiceProcessControl. Their normal idle/instance/ancestry checks,
  maintenance reservation, stop confirmation, hidden launcher start and new
  persisted process lease all remained in force. No token was printed/copied.
- Restart succeeded. New service PID 11980 and launcher PID 35004; health is OK,
  Reader schema 13, backend/default voice/database ready. The temporary runner
  exited; the recorded normal service launcher remains running independently.

## Fresh MCP verification

Initialized a new real stdio MCP session using the unchanged existing
Agent-import connection configuration and protected grant. Verified:

- 16 tools, including all seven additive M2 tools.
- Workspace features: retry-safe creation, managed imports, story status,
  chapter text, literal search and busy details; default part limit 900,000.
- Seven existing Battlemage articles and exactly 360 unique chapter receipts.
- Unchanged article versions: Parts 01..07 = 61, 60, 61, 60, 61, 21, 43.
- Part 07 has 43 current structural chapters; reading Chapter 319 returned a
  bounded 120-character page with the expected heading. Literal search finds
  that heading through the new endpoint. No prose retained in the result log.

All probes were read-only: no live article, plan or grant was created or edited.
Reader PID 23952 stayed open. No application binary publication, configuration,
network, voice MANIFEST or unrelated work occurred. The additive database upgrade
was performed by ordinary service startup. Generated runner and nonsecret results
are ignored under `logs/reader-agent-m2-activation/`.

Validation: zero-warning helper build, successful production restart result,
schema/health checks, real MCP initialization and live read-only capability probes.
Documentation-only link/whitespace checks apply to this status update; no feature
test rerun is needed. M2 implementation acceptance remains in the prior log.
