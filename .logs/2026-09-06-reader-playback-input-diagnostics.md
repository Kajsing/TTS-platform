# Playback input diagnostics - 2026-09-06

## Scope and evidence

The user reports intermittent pauses apparently associated with clicking away
from Reader while gaming and explicitly requested more logging. They closed
Reader and its persistent tray host for deployment. Existing bounded logs show
ordinary Pause requests at 15:20:20 and 16:22:09 local time, a service-unavailable
fault at 15:45:05, and a separate 429 at 16:58:42. None proves mouse input or a
particular hotkey caused the stop. Windows LastWriteTime was stale while the
JSONL writer was open; the content had current entries.

## Implementation

- Application: versioned closed-enum interaction contract, monotonic ages,
  sequence and sampled non-control input; sink errors cannot interrupt commands.
- WPF: observe own Reader/compact activation, focus, mouse down/up, playback
  button Space/Enter and capture/hover context; label button/tray/hotkey/local
  shortcut/internal/automatic command sources. No event is consumed by logging.
- Record failed reading-position saves with a fixed operation label, sanitized
  error category/code, HTTP status and request ID. Preserve existing behavior.
- Reuse existing JSONL rotation/session/run IDs and immediate flushing. No text,
  arbitrary keys, screen coordinates, foreign window/process data, new global
  hook, service endpoint, dependency or settings change.
- Tests: pure observer correlation/sampling/failure/privacy, open-file JSONL,
  position-save 429, and real WPF routed/automation source attribution through
  the isolated lifecycle fixture. Synthetic routing does not claim physical
  mouse/game reproduction or identify the user's root cause.

## Validation and deployment

- `py -3 -m pytest -q`: **626 passed, 2 optional skips**. `py -3` is the
  Windows substitute for the golden Python command. Ruff passes.
- Local .NET 10 SDK: **276 tests pass** (51 Client, 133 Application, 92 Windows).
  Build/publish have zero warnings/errors; touched-file format verification and
  diff checks pass. No buffering, synthesis or input policy was changed.
- Initial new fixtures exposed two test-setup errors: reading an open writer
  needs FileShare.ReadWrite on Windows, and an empty Reader's Play button must
  be enabled for synthetic automation. Both fixtures were corrected; no
  production file-sharing or button-enablement behavior was changed.
- Development and exact root-shortcut win-x64 self-contained executables pass
  the isolated lifecycle/input fixture, including real WPF mouse routing,
  button automation, Space, unrelated-key pass-through, global-command/tray/
  compact source labels, automatic-pause privacy and focus-only non-action.
  Evidence: `logs/playback-input-20260906/shortcut.json` and bounded synthetic
  `interaction-smoke-*.jsonl` files. No physical gaming click was reproduced.
- `py -3 scripts/check_desktop_reader.py --require-dotnet --dotnet <local SDK>
  --skip-build`: isolated HTTP, paging, position resume, edit/undo, synthetic
  streaming, portable package and WPF lifecycle/input checks all pass. Optional
  physical-audio/global-Windows integration gates were not requested for this
  logging-only slice; no user clipboard or live audio was exercised.
- The actual `TTS Platform Reader.lnk` target was rechecked and published:
  `apps/desktop_reader/src/TtsPlatform.Reader.App/bin/Release/net10.0-windows/win-x64/TtsPlatform.Reader.App.exe`.
  The user closed both Reader/tray and service; none was restarted for delivery.
  Open the normal shortcut to collect the new diagnostic schema on next use.

No goal/security/licensing/deployment architecture change. U8 remains parked;
the user's unrelated `models/MANIFEST.json` remains unstaged. Wait for a new
field trace before identifying or fixing the pause cause. The separate observed
429 is documented, not silently tuned or reported as fixed.
