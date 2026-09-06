# Service Center T2: deferred default voice

Date: 2026-09-06. Coherent slice complete; overall T2 is not complete.

## Delivered

- Added `tts_service/model_defaults.py` and the `model_manager set-default` verb.
  Fixed config/manifest paths, reviewed fingerprints, installed asset validation,
  manifest/config locks, byte-preserving scalar editing and semantic comparison
  of every unrelated TOML value. Never contacts/restarts the running service.
- Same-directory staging receives the original DACL before secret-bearing config
  content is written. Flushed replacement uses Windows ReplaceFileW without
  ignored ACL/merge errors; documented partial failures restore or retain a
  private recovery copy. Config staging/lock/recovery files are Git-ignored.
- Application controller and Windows helper adapter expose deferred selection,
  validate the matching terminal voice/result, retain the gate until actual
  process exit and invalidate uncertain/stale inventory before another attempt.
- Installed voice UI confirms the choice and explains that it is saved for the
  next explicit restart, independently of Reader's preference. Current speech,
  paused reading, exports and installed files are untouched. Host exit/lifecycle
  actions cannot race a pending local save. Temporary busy warnings clear again.

## Validation

- `py -3` substitutes for the Windows Store `python3` alias: 615 Python tests
  pass, 2 optional skips; Ruff passes. 47 focused defaults/model-manager checks.
- 248 .NET tests pass (45 Client, 118 Application, 85 Windows), including reviewed
  intent, duplicate/in-flight guards, privacy, matching result/activation and
  cooperative late cancellation with real synthetic helper exit.
- Real Windows protected-DACL fixture verifies staging permissions before commit
  and final DACL after replacement. Tested stale metadata, absent assets, invalid
  config, cancellation, concurrent edit, ordinary failure and simulated partial
  replacement/recovery. Fixtures only; no production config/ACL was modified.
- .NET format verification and zero-warning self-contained win-x64 publication.
  Verified root shortcut points to App/bin/Release/net10.0-windows/win-x64/
  TtsPlatform.Reader.App.exe with no arguments and no live Reader before publish.
- Actual shortcut lifecycle smoke includes default confirmation cancellation,
  serialized save, exit refusal, deferred result and removal of stale busy text;
  all assertions pass. Evidence: logs/service-center-default-20260906/shortcut.json
  and service-center-voices-installed.png (synthetic metadata).
- Read-only actual LocalVoiceLibrary -> Python bridge: 5 installed voices,
  1 catalog package, config valid, production manifest hash unchanged.
- Portable bundle + isolated HTTP paging/service/stream/import/edit checks and
  WPF folder/lifecycle smoke pass. Physical audio/clipboard/global-hotkey tests
  remain explicitly opt-in, not claimed as exercised here.

## Boundaries and next work

No production service/process/config/default/startup/model/article changes,
downloads or license acceptance. Preserve the user's dirty models/MANIFEST.json.
No new dependencies, engine, network/security mode or U8 work.

This slice stages configuration rather than live activation: safe explicit
restart already exists. Unconventional TOML and encrypted/linked config files
require manual editing; the GUI refuses rather than normalizing or weakening
them. Non-cooperating external config editors can race a final snapshot check;
avoid concurrent manual edits. Recovery files are not silently adopted on reopen.

Next: guarded short fixed-text preview, broader verified catalog metadata, then
final T2 acceptance and publication. Preview must refuse active/paused Reader
audio and global service/export work without stopping it. Existing maintenance
reservations block ordinary synthesis too; do not reserve then call /v1/tts and
mistake the expected refusal for a backend fault. Investigate the narrowest safe
admission path before implementation. Safe to continue autonomously in scope.
