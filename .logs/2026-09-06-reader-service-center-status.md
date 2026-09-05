# Service Center T1.2 status/safety foundation - 2026-09-06

Previous goal turn was progress: T1.1 was implemented, tested, published and
pushed. This turn advances T1.2; it does not complete T1 or redefine the goal.

## Implemented

- Native local owner-only `/v1/service/status`, plus short maintenance reserve/
  release routes, with explicit remote-gateway denial. Existing endpoints and
  credential scopes remain unchanged. See `docs/reader_service_center_api.md`.
- Low-sensitivity readiness/default voice/count/uptime/activity and measured
  Windows process CPU/current working-set data. No article/private path data.
- In-memory activity tracking across complete HTTP/WS lifetimes, queued/running
  jobs and exports, including workers whose cancellation has not yet finished.
  Completed export futures are cleaned up. No database scan per status poll.
- Atomic idle reservation blocks new work for at most 15 seconds, then expires
  even if the desktop disappears. It never kills a process. Windows ownership,
  reservation deadlines and client-buffered playback still need UI integration.
- Explicit .NET client DTOs/methods and tested dashboard state/resource/polling
  policy. Existing live .NET fixture now checks status and reservation/release.

## Why an additive status route

Initial reuse inspection found that Reader diagnostics calls repository.report
and filters export history by visible/unlocked folders. Polling it would do
expensive checks and could miss work in a locked folder. The local-owner status
projection reuses the existing readiness/counters, with new lightweight aggregate
worker counts. This is a supporting implementation detail, not a new architecture,
permission model, remote-access feature or replacement of Reader diagnostics.

## Validation

- Python: 549 passed, 2 optional skips; targeted status/remote tests passed.
- .NET: 182 passed (45 client, 94 application, 43 Windows). Solution build had
  zero warnings/errors. Used `py -3` and the verified per-user .NET 10 SDK.
- Desktop verifier passed isolated live service paging, synthesis, UTF-16 edits,
  streaming/resume, imports/rules and `live_service_center: true`. Portable WPF
  folder visibility and persistent-tray lifecycle also passed. Optional physical
  clipboard/hotkey/audio integration was not rerun or required for this slice.
- A direct Windows resource sample returned actual non-null working-set bytes,
  CPU seconds and logical processor count. Equal timestamp samples are possible
  at Windows clock resolution; the test and CPU policy treat that correctly.
- Full Python tests initially caught missing explicit remote route classification;
  added deny entries and reran successfully. No remote routes were enabled.
- Review found that ordinary job-history expiry could discard a cancelled
  worker's Future before it exited. Added a separately retained live-Future set
  and a real queued-worker/cancel/history-expiry regression. It remains busy
  until the worker actually finishes, even after its public job record is gone.
- Wrong non-ASCII reservation strings safely return false rather than causing
  a string-comparison exception. All 12 focused service-control tests passed.
- Ruff and .NET formatting verification passed; staged diff is checked before commit.

## Remaining / safety

Next: implement the actual WPF dashboard/monitor and connect all Reader/tray
start/stop/restart paths to serialized, ownership-verified, activity-aware Windows
commands with deadline checks and postcondition verification. Then T1.3 optional
Task Scheduler autostart/Options, then all T2 voice-library work. T1.2 is not done.
No production service restart/stop or Windows registration was performed here;
UI still has the T1.1 tray behavior. Existing machine-local manifest changes are
preserved and must remain unstaged. Safe to continue with T1.2; goal stays active.
