# Service Center T2: voice menu and helper ownership

Date: 2026-09-06. Coherent UI slice completed; T2 overall is not complete.

## Completed

- Added Application local voice/package contracts and a tray-owned controller.
- Added Windows JSON-lines adapter using the existing launcher root/Python
  preferences, separate arguments and hidden helper processes. Bounded protocol
  parsing, stderr draining, strict terminal/exit confirmation and serialized
  actual process lifetime; cooperative stdin cancellation for installation.
- Added Service Center > Voices with Installed/Available packages, model/language/
  size/license/source details, explicit selection-specific license review,
  progress and cancellation. Already-present package files are not overwritten.
- Closing the panel preserves the operation. Reopening restores progress.
  Host exit and local service lifecycle commands wait for model operations;
  neither installation nor panel close interrupts Reader or restarts the service.
- Selected-card contrast, initial tab load, minimum-window scrolling, license
  reset and cancellation/exit guards are asserted in isolated WPF smoke.

## Validation

- .NET 10.0.202: 45 Client + 116 Application + 81 Windows = 242 tests passed.
- `py -3 -m pytest -q`: 593 passed, 2 optional skips, 58.15s.
- Ruff, .NET format verification and Git diff checks passed; build 0 warnings/errors.
- Real synthetic PowerShell helpers test explicit cancellation, timed cancellation,
  keeping the gate after early terminal output, malformed/version/duplicate/
  truncated/oversized output and credential-free errors. No real installation.
- Read-only real C# adapter -> Python bridge probe: 5 installed voices, 1 catalog
  package, valid config, manifest hash unchanged. Probe source is under ignored
  `logs/service-center-voices-20260906/bridge-probe/`.
- Actual shortcut target re-resolved and published while Reader was absent:
  `apps/desktop_reader/src/TtsPlatform.Reader.App/bin/Release/net10.0-windows/win-x64/TtsPlatform.Reader.App.exe`.
- Exact published executable marker:
  `logs/service-center-voices-20260906/shortcut.json`; all lifecycle/startup and
  five new voice-library markers true. Synthetic screenshots in the same folder
  cover installed/packages/progress and small-window scrolling, visually reviewed.
- `check_desktop_reader.py --require-dotnet --dotnet <verified SDK> --skip-build`
  passed isolated live HTTP, portable packaging and WPF folder/lifecycle checks.
  Physical audio, clipboard and global-hotkey probes remain opt-in and were not run.

## Scope and next work

Only the desktop implementation/tests and documentation changed. The unrelated
machine-local manifest edit remains unstaged. No user article, config, token,
installed voice, production service or Windows startup registration changed.
No paid/cloud dependency, security/architecture change or U8 work was introduced.
Reused the existing icon/theme; no image-generation skill was appropriate.

T2 is incomplete: expand the catalog (research pointers are in
`docs/reader_voice_catalog_review.md`), add guarded fixed-text preview and clearly
separated service-default selection, validate and republish, then audit the whole
goal. Safe to continue autonomously within the approved scope.
