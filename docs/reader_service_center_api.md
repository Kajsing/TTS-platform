# Local Service Center contract v1

This is an additive local-owner API. Existing health, Reader and synthesis
contracts are unchanged. Its desktop dashboard/control wiring is still in
progress; these routes do not themselves stop a Windows process.

All three routes require the existing owner bearer token, enabled token
authentication, a native loopback client, and no Origin header. Folder-scoped
MCP credentials and remote-device credentials are not owner tokens. The remote
gateway explicitly denies these routes. No public-server or U8 setup is enabled.

| Method and path | Body | Result |
| --- | --- | --- |
| GET `/v1/service/status` | None | Status object below |
| POST `/v1/service/maintenance` | `{"instance_id":"..."}` | `reservation` and `expires_in_seconds` |
| POST `/v1/service/maintenance/release` | `{"reservation":"..."}` | `{"released":true}` or `false` |

## Status fields

- `contract_version`: integer, currently 1. Reject unsupported versions.
- `instance_id`: opaque string, changes whenever the service application starts.
  It is not a process-ownership proof or a credential.
- `backend_ready`, `default_voice_loaded`, `reader_ready`: booleans taken from
  the existing backend/registry/Reader readiness state. A response alone does
  not mean the backend can speak. Registry readiness is not a latency promise.
- `default_voice_id`, `default_voice_name`: string or null; installed voice
  metadata only. `voice_count` is the registered voice count, not package count.
- `uptime_s`: nonnegative integer seconds since application initialization.
- `maintenance`: whether an unexpired reservation is held. The reservation
  secret itself is never included in status.
- `activity`: nonnegative counts `active_requests`, `active_streams`,
  `content_leases`, `pending_exports`, and `pending_jobs`. These categories can
  overlap; do not sum them and label the result as distinct jobs.
- `resources`: `scope` is `service_process`; `process_id` identifies the API/
  synthesis host process. `cpu_seconds` is cumulative process user+kernel CPU,
  `sample_monotonic_s` is the service clock sample, `logical_processors` is the
  host processor count or null, and `working_set_bytes` is current Windows
  process working-set RAM or null if unavailable. External child processes are
  not included. No title, clipboard text, article body or file path is returned.

CPU percent is the change in CPU seconds divided by elapsed monotonic seconds
and logical processor count, times 100. The desktop compares only samples from
the same instance/process. First samples, absent processor counts, nonpositive
elapsed time or invalid counters are unavailable, not zero. RAM is working set,
not committed memory or historical peak. Unsupported platforms return null RAM.

The snapshot reads memory counters and bounded live-worker collections. It does
not perform SQLite integrity checks, enumerate document titles or filter job
activity by unlocked folders. Completed export futures are removed from the
live collection. A cancellation flag is not proof that its worker has exited.

## Safe maintenance protocol

1. The desktop verifies the exact local launcher/task ownership and selected
   local service target. Do not use a returned PID as permission to kill it.
2. Check any locally buffered/paused Reader playback and obtain the required
   user confirmation. This API cannot see audio already buffered in clients.
   Active exports must finish or be explicitly cancelled through their normal
   UI; they cannot be silently discarded by a service restart.
3. Request a reservation using the last observed instance ID. The service holds
   a lock across the check for in-flight HTTP/WS requests, active streams,
   content leases, live queued/running exports and jobs, and the reservation.
   Active work produces HTTP 409 `service_busy` without stopping anything.
4. On success, new application HTTP work is rejected with HTTP 503
   `service_maintenance` and `Retry-After: 15`; new WebSockets are rejected with
   ASGI close code 1013 before acceptance (a network handshake can surface this
   as HTTP 403). Existing health/voice reads and these control routes remain
   available. The status HTTP call itself is not counted as activity.
5. The reservation currently expires after 15 seconds. The desktop must derive
   a conservative local deadline from the time BEFORE issuing the request, and
   check it again immediately before any stop. If verification/confirmation/
   scheduling takes too long, release/reacquire; never stop on an expired lease.
6. Stop only the verified Windows owner, then verify the expected service is
   gone. If stopping is refused or fails, release in `finally`. Never log the
   reservation or put it in a URL. A lost desktop cannot permanently lock the
   service: expiry automatically restores acceptance of new work.
7. Restart only after verified shutdown. Wait for actual readiness, not merely
   a process launch result. A changed instance ID invalidates old status samples.

`service_instance_changed` (409) requires refresh; `service_maintenance_busy`
(409) means another reservation is held. Wrong or expired release secrets return
false and cannot release another reservation. Local-only failures are 403,
missing/invalid owner auth is 401, and disabled token auth is 503. Existing rate
limiting still applies; the dashboard policy backs off after 429.

## Acceptance evidence and remaining integration

`test_service_control.py` exercises auth/native/remote boundaries, no database
scan, busy/cancelled workers, request/WS tracking, invalid/expired reservations,
and real current-process resource sampling. The .NET client tests cover auth,
serialization, busy/rate-limit errors; dashboard tests cover state mapping,
CPU math, unknown values and polling policy.

The normal desktop verifier enables `TTS_PLATFORM_SERVICE_CENTER_SMOKE=1` only
for its isolated live fixture. The compiled .NET smoke reads real HTTP status,
reserves idle maintenance, observes a blocked Reader request, releases it and
continues normal Reader paging/synthesis/editing. It never stops the fixture or
touches the user's service. Production dashboard and Windows command ownership/
deadline enforcement are the next T1.2 slice, not yet delivered by this API.
