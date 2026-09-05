# Reader folder visibility checkbox

- User specified Open checked = show articles, unchecked = hide them, and closed
  Reader for deployment. Confirmed no Reader process, zero active content leases
  or streams and only completed exports before stopping the exact verified
  service listener. No unrelated Python process, live grant or article changed.
- Implemented Open as a local, persistent per-workspace presentation preference.
  Closed folders remain in the manager; library/search/paging omit their articles,
  and direct reading waits for the folder to reopen. Privacy lock stays separate;
  its controls now require an actual configured lock, not merely accessible data.
- Raw service/API/contracts/database are unchanged. Root articles remain visible.
  Queue/export records are retained, not deleted or treated as protected secrets.
  Folder closing preserves unsaved edits and active/paused playback; a settings
  save failure leaves the old visibility intact. In-flight loads/play starts are
  guarded against reopening closed content.
- Added five .NET regression cases for defaults/persistence/workspace isolation,
  search/paging/refresh/reopen, mutation replacement, bounded hidden-only scans,
  non-advancing cursors and pending-response filtering. Added an opt-in synthetic
  WPF smoke and wired it into the existing desktop package render gate.
- The first WPF run caught a read-only binding crash; made status bindings
  explicitly OneWay. The next run exposed Click-only handling of UI Automation
  toggles; switched to checked/unchecked changes with an initial-binding guard.
  These were caught in the isolated development build before shortcut deployment.
- Validation passed: 172 .NET tests (43 client, 90 application, 39 Windows),
  537 Python tests / 2 optional skips; Ruff, touched Python formatting, solution
  format verification, desktop source-shape gate and zero-warning WPF build.
  Formatted the touched desktop-check script, including its existing style drift.
- Published win-x64 self-contained output to the exact root-shortcut executable
  directory, not only the development output. The actual shortcut executable
  passed all synthetic checkbox checks, including Options rendering, hide after
  refresh, editor clearing, settings reload, reopen, unsaved-edit preservation,
  save-failure rollback and read-only service calls. Both synthetic screenshots
  were visually inspected. Artifacts remain in ignored
  `logs/folder-open-20260905-1`; no real article or credential is in them.
- Reproduce the focused test with the published executable's `--smoke-test`,
  `TTS_PLATFORM_READER_FOLDER_SMOKE=1` and an isolated absolute
  `TTS_PLATFORM_READER_SMOKE_MARKER` path. The ordinary
  `scripts/check_desktop_reader.py` package-render gate now includes this test.
- Final runtime verification: zero Reader processes and no port-7777 listener.
  The requested slice is complete; no automatic import, service restart or U8
  continuation is authorized. Commit/push this validated slice by repository policy.
- Windows commands use `py -3` and the verified per-user .NET 10 SDK. Existing
  user-owned `models/MANIFEST.json` remains excluded. No dependency or security
  model change. Service and Reader should remain stopped at handoff.
