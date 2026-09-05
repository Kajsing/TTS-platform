# Service Center dashboard and guarded local controls

Implemented the next T1 slice of `docs/reader_service_center_plan.md`.

- Independent WPF status panel using the existing icon/theme. Tray, header and
  single-instance Service Center activation all open it without requiring a
  Reader window; closing it leaves the tray/service alone.
- Authenticated local status polling: no redirects/proxies, four-second HTTP
  timeout, serialized requests/commands, 5/15-second visible/hidden polling,
  30-second failures and 65-second rate-limit backoff. Saved local connection is
  used independently of Reader's active remote workspace. Settings failures do
  not re-enable controls from a stale successful snapshot.
- CPU, working-set RAM, uptime, voice readiness and separate overlapping work
  counters are labelled honestly. Unknown/first CPU samples display unavailable.
  Metrics and logs contain no article/clipboard text or credentials.
- `LocalServiceCoordinator` owns readiness, confirmation, reservation deadline,
  release-on-refusal/failure and restart postconditions. The deadline includes
  request latency and is checked again inside the OS adapter before stop.
- `LocalServiceProcessControl` verifies the existing persisted launcher PID,
  exact executable/path/start time and chronological service ancestry. Toolhelp
  parent IDs alone are not trusted (PID reuse); process handles/start times are
  checked. Only the exact owned launcher tree is eligible for termination.
  Microsoft API reference: https://learn.microsoft.com/en-us/windows/win32/api/_toolhelp/
- Start checks the selected local port and existing ownership first, then uses
  the existing hidden local launcher with explicit loopback host/selected port.
  Stop confirms process exit and endpoint shutdown; restart awaits actual voice
  readiness. Unknown listener state is not absence. No unrelated Python kill.
- Removed the old task-name-only scheduled Run/End fallback. A legacy scheduled
  or terminal-started service without a valid ownership lease can be monitored,
  but is safely refused for stop and explains where to stop it. Exact legacy
  scheduler reconciliation remains work for T1.3, not silently claimed finished.
- Reader's existing header Start/Stop routes through the same coordinator.
  Confirmed local maintenance stops buffered/paused playback, temporarily
  inhibits playback/close, and preserves unsaved edits. Remote Reader state is
  not stopped by local maintenance. The independent host owns tray menu state.

Validation (Windows, `py -3` substituted for the Store-alias `python3`):

- .NET solution: 199 tests passed (45 client, 108 application, 46 Windows).
- Python: 549 passed, 2 optional skips. Ruff passed.
- Three real, isolated Windows process-tree tests start only synthetic
  PowerShell launcher/child fixtures on ephemeral ports, verify ownership,
  expired-stop refusal, duplicate-start refusal and exact-tree shutdown.
  Fixtures use their own settings/lease paths, no production service or Python.
- Desktop checker: real isolated status/reservation HTTP and existing Reader
  playback/import/edit flows; portable folder/lifecycle WPF smoke passed.
- Actual root shortcut target published for win-x64, then lifecycle/dashboard
  smoke passed with isolated settings/activation scope. Marker and rendered
  panel: `logs/service-center-dashboard-20260906/shortcut.json` and
  `service-center.png`. Values in the visual snapshot are synthetic.
- Physical audio/clipboard/global-hotkey integration remains opt-in and was not
  run; these checks did not touch the user's clipboard or active applications.

No production service/startup registration was changed. Existing machine-local
`models/MANIFEST.json` remains user-owned and unstaged. T1.3 and T2 are outstanding;
U8 remains parked. Safe to continue with the approved startup slice.
