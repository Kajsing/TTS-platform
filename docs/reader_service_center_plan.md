# Reader Service Center

Status: user-approved active goal, 2026-09-05. T1.1 and the T1.2 dashboard/owned
launcher control slice are implemented and published. T1.3 and T2 remain
incomplete; legacy scheduler ownership integration remains a T1 follow-up.
This track precedes parked U8 and deferred Reader Milestones 10/11.

## Approved outcome and boundaries

- One persistent tray icon, including while Reader is open, with a compact,
  attractive service dashboard and a compatible-voice library.
- Opening Reader starts the service-center host. Closing the Reader window
  leaves that host available; closing the dashboard returns it to the tray.
  Reopening the shortcut activates the existing host, not another tray owner.
- Optional Windows autostart is **off by default**. Its label explains that it
  starts Service Center and the local service, without opening a Reader window.
  No startup registration merely because the program was installed or tested.
- Keep Python responsible for synthesis, models and article storage. Reuse the
  WPF desktop and existing icon/theme. No new synthesis backend, paid/cloud
  dependency, remote access, firewall setup or machine-wide Windows service.
- Service Center controls this computer's local service, not the remote
  workspace selected in Reader. Label that distinction clearly.
- Preserve article data, unsaved edits, credentials, installed voices, existing
  minimize-to-tray/compact mode, and active playback/export state.
- No article titles/text, clipboard content or tokens in metrics and logs.
- Never adopt or kill arbitrary Python processes. Validate process ownership,
  executable/launcher identity and start time; refuse ambiguous ownership.
- Stop/restart checks activity and requires explicit confirmation for disruption.
  Unknown activity is not idle. Do not restart beneath an active export or use
  a silent forced fallback. Exiting only the tray host leaves the service running
  and says so; stopping it is an explicit, separately confirmed action.

## T1 - Persistent tray and local service dashboard

### T1.1: Lifecycle

Implemented and validated on 2026-09-05. Evidence and boundaries are in
`.logs/2026-09-05-reader-service-center-lifecycle.md`.

Move tray ownership out of the Reader window's lifetime. Prefer reusing the
desktop executable with a background entry mode over a second application.
Closing/reopening Reader and launching the shortcut twice must preserve exactly
one tray owner. Any activation channel is current-user-only, cannot execute
arbitrary commands and carries no credentials.

Keep Reader playback/clipboard controls while Reader is open or deliberately
minimized. A genuinely closed Reader releases its window, playback and clipboard
resources; service presence does not depend on retaining a hidden editor.
Protect dirty edits and distinguish closing Reader from exiting the tray host.
Existing isolated smoke modes must not touch live settings, service state,
tray ownership or Windows startup registration.

### T1.2: Dashboard and controls

Status/safety foundation and the WPF dashboard/owned-launcher controls are
implemented on 2026-09-06. See `reader_service_center_api.md` and
`.logs/2026-09-06-reader-service-center-status.md`. Existing Reader diagnostics
proved unsuitable for polling/global work safety (database integrity scan and
folder-filtered export counts), so an additive native-owner status projection
and short atomic maintenance reservation reuse the existing runtime counters.

The dashboard opens independently from Reader, polls at 5 seconds visible / 15
seconds hidden, backs off on failures and rate limits, and displays unavailable
values rather than stale/zero metrics. Tray and Reader controls now use one
serialized coordinator. Stop/restart requires current idle activity, confirmed
Reader cleanup, an unexpired reservation and a verified launcher/service process
tree. The old task-name-only Run/End fallback has been removed. Legacy scheduled
or terminal-started services without a matching ownership lease remain visible
but are refused with an explanation; they are not silently adopted by PID. The
remaining startup slice must reconcile legacy tasks without changing them merely
to pass validation. See `.logs/2026-09-06-reader-service-center-dashboard.md`.

Provide service readiness, default voice, voice count, uptime, activity, CPU and
working-set RAM, plus Open Reader and start/stop/restart. Show stopped, starting,
ready, busy, degraded and unreachable states honestly: a process or HTTP response
alone is not evidence of voice readiness. Unmeasurable fields show unavailable,
not zero. Measure only the verified service process/tree, not unrelated Python
processes or the Reader UI, and label the measurement scope.

Reuse health and Reader diagnostics. Use bounded requests, serialized lifecycle
commands, cancellation on exit, modest polling and failure/rate-limit backoff.
Do not scan models/database per tick. If showing synthesis latency, identify the
server metric: time-to-first-chunk is not audible playback startup time.
Cover scheduled, externally started and previously Reader-started services,
stale ownership records, missing launchers and unavailable authentication.

### T1.3: Optional Windows startup

Expose an autostart checkbox in Service Center and an entry from Reader Options.
Show actual registration state rather than only a saved boolean. Use reversible
current-user Task Scheduler registration, without elevation. Detect existing
service autostart and avoid competing owners; do not silently overwrite another
installation's task. Report enable/disable failures and revert the display.
Use the exact published executable path with correctly quoted arguments.
Cover spaces, moved/missing installations and repeated enable/disable.
Test with an isolated named registration target or fake scheduler, never by
enabling production autostart just to pass a check.

### T1 acceptance

- [x] One persistent icon; second-process activation tested using the actual
  shortcut executable with isolated settings and activation scope.
- [x] Reader close/reopen, compact/minimized mode, dirty-edit refusal, active
  dialog guards and host disposal pass the isolated WPF lifecycle smoke.
- [x] Dashboard metrics have verified sources and truthful unavailable states.
- [ ] Start/stop/restart are ownership-safe and protect active work.
- [ ] Autostart defaults off, is reversible and reflects actual registration.
- [ ] Relevant regression tests, WPF lifecycle smoke and actual-shortcut
  publication pass while the user's Reader is safely closed.

## T2 - Compatible voice library

Begin after T1 acceptance. Reuse the existing catalog/install/check pipeline.
Separate installed voices from downloadable packages: one model can contain
several voices. Display language, model family, size, source and license before
installation. Begin with verified formats supported by the existing sherpa-onnx
backend and the current Piper/Kokoro workflow, not arbitrary Hub repositories.
Review/expand the small catalog using verified primary upstream metadata,
checksums and voice-specific license terms; a code license is not a voice license.

Installation is an explicit action with download/verification/install progress,
bounded operations and cancellation. Stage partial downloads/extraction; a
failure must preserve the previous manifest and working voices. Readiness is
shown only after checks pass. Do not change the active engine mid-playback.

Preview uses a short fixed, non-private sample and must not unexpectedly overlap
Reader playback. Distinguish a service-default change from Reader's existing
voice preference. Separate installation from activation: if safe activation
needs a restart, show it as pending until explicitly approved and idle.
Do not automatically remove voices, overwrite machine-local manifest changes,
download large models or accept license terms merely for a smoke test.

### T2 acceptance

- [ ] Installed/available voices and accurate package/license metadata.
- [ ] Verified installation with visible progress and safe cancellation.
- [ ] Tests for bad checksums, failed extraction, unavailable downloads,
  existing-package conflicts and manifest preservation.
- [ ] Preview/default selection respect playback/export activity.
- [ ] Published desktop smoke and relevant Python/.NET regressions pass.

## Validation and delivery

Use `py -3` for the Python golden commands on this Windows machine. Use the
verified per-user .NET 10 SDK and publish `win-x64` to the actual shortcut target.
Record current results per slice, not historical test counts. Update
`docs/codex/Documentation.md` and a concise `.logs/` entry; commit and push
validated coherent slices, leaving unrelated manifest edits out.

## Inspection and resume point

The goal remains active. `DesktopServiceCenterHost` now owns one tray icon and
reloads settings when recreating a genuinely closed Reader. Normal startup uses
an exclusive current-user/current-session named-pipe activation channel; smoke
tests use separate scopes/settings and cannot contact the real service. Closing
Reader no longer shuts down its host. Exiting Service Center confirms that the
service stays running and checks dirty Reader edits before shutting down.
The root shortcut binary is updated and passed the isolated lifecycle smoke.
The Service Center tray command and Reader header entry open the independent
dashboard. Existing Start/Stop header controls no longer bypass reservations.
Autostart is not registered or exposed. `LocalServiceProcessControl` uses the
existing process-lease format and verifies the service is a chronological
descendant of its exact owned launcher before stopping it.
Health already includes uptime/readiness/backend/streaming data; Reader
diagnostics includes content leases and export counts. Current Task Scheduler
and model-management code lives in `apps/tts_service/src/tts_service/cli.py`.
The downloadable catalog currently contains one entry. The machine-local
`models/MANIFEST.json` has an unrelated pre-existing change: preserve it.

The API, coordinator and dashboard now pass unit, isolated real HTTP, real
synthetic Windows launcher-tree and WPF lifecycle tests. No live service was
started or stopped for these checks. Next: T1.3 Windows autostart and Options
entry, including legacy scheduled-task reconciliation/ownership, then T2.
Recheck live processes before publication.
U8 stays parked. After this track,
return its remaining acceptance to the user before any networking changes.
