# Service Center T1.1 - 2026-09-05

## Completed

- App-owned `DesktopServiceCenterHost` retains one tray icon while a genuinely
  closed Reader disposes its window/clipboard/hotkey/playback resources. Reopen
  loads current saved settings into a fresh window. Existing minimize/compact
  behavior remains available. The real executable icon replaces the generic one.
- `ReaderInstanceChannel` uses an exclusive first named-pipe instance, scoped
  by current user/session/settings location. Both endpoints use CurrentUserOnly.
  Only three one-byte activation intents are accepted; no paths, text, tokens
  or executable commands are transmitted. Client/stalled-server waits are bounded.
- Reader close protects dirty edits and active dialogs/document operations.
  Explicit host exit explains the service stays running; a refused Reader close
  cancels host exit. Background activation creates no Reader window.
- Added four Windows unit tests and an isolated WPF lifecycle smoke with a real
  tray plus a second executable activation probe. The normal desktop verifier
  now runs this smoke with bounded process timeouts, alongside folder checks.

## Validation

- Per-user .NET SDK 10.0.202: solution build passed, zero warnings/errors.
- .NET tests: 176 passed (43 client, 90 application, 43 Windows).
- .NET solution formatting verified. Python uses `py -3` on Windows:
  537 pytest tests passed, 2 optional tests skipped; Ruff passed.
- `py -3 scripts/check_desktop_reader.py --require-dotnet --dotnet
  <per-user-dotnet> --skip-build` passed source, isolated live service paging/
  edits/streaming/import/rules, preview DB, portable package, folder visibility
  and WPF service-center lifecycle. Optional physical audio/clipboard/hotkey
  integration was not requested or rerun; user clipboard was not touched.
- Resolved the root `.lnk` and published self-contained Release win-x64 to its
  actual target, after confirming no Reader process and no port 7777 listener.
- Actual shortcut executable lifecycle marker:
  `logs/service-center-lifecycle-20260905/shortcut-final.json` (ignored synthetic
  artifact). All checks passed: one tray, real second-process activation, fresh
  Reader, dirty-edit refusal, active-dialog guard, settings reload, minimized
  restoration, compact cleanup, hidden background mode, tray disposal and
  ownership release. Test settings are isolated and service API calls are absent.

## Findings and remaining work

The first smoke exposed a reentrant WPF Closing event when Stop completed
synchronously. Confirmed close is now dispatched after the first event unwinds;
both development and self-contained executable smokes pass that path.

T1.2 dashboard/metrics and safe activity-aware service controls, T1.3 autostart/
Options, and all T2 voice-library work remain. The existing Service Status tray
action still opens Reader connection status for now. No production autostart,
service lifecycle or model-manifest change was made. Reader and service remain
stopped after testing. Preserve unrelated dirty `models/MANIFEST.json`.
No architectural deviation: this is a desktop lifetime refactor; Python remains
the synthesis and data authority. Safe to continue with T1.2; goal stays active.
