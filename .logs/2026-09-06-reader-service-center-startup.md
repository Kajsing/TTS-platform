# Optional Windows startup slice

Implemented T1.3 of `docs/reader_service_center_plan.md`; the whole goal remains
active. T1 still needs the legacy scheduled-owner integration before its final
audit, and T2 voice management is not implemented yet.

Changes:

- Added `UserStartupRegistration` and a narrow native Task Scheduler adapter.
  No new package, administrator prompt, Windows password, cloud dependency or
  machine-wide service. Registration is off by default and per-user.
- The Windows startup tab displays actual registration; creation is create-only,
  removal/update verifies matching XML, and foreign/changed definitions are
  refused. Missing/moved executable and runtime are reported.
- Default legacy service-task conflicts block new registration and do not alter
  the legacy task. This is not yet a claim of discovering every custom-named
  launcher; broader legacy discovery remains in the next slice.
- Actual native testing found two Windows serialization details: missing tasks
  map to .NET FileNotFoundException, and saved XML omits defaults / canonicalizes
  trigger account names. Fixed both using exact current-user checks and explicit
  schema defaults, not permissive string matching.
- Added ten-second observation bounds with retained operation ownership while a
  native call remains pending. A timeout never causes a duplicate registration
  or a false rollback claim. Failures re-read actual state or show unknown.
- Added `--autostart`, distinct from background/Reader activation, over the
  current-user single-instance channel. A matching enabled registration is
  required; the flag cannot enable itself. Startup stays hidden, reuses an
  existing service, and launches an absent service at most once.
- Options has an explicit save-and-open startup entry. WPF smoke verifies saved
  preferences survive that navigation. Tab styling is local to Service Center;
  visual inspection caught a selected-header foreground inheriting into page
  text, which is fixed and now has a contrast regression assertion.

Validation on Windows:

- .NET solution: 216 tests passed (45 client, 108 application, 63 Windows).
- Python: `py -3 -m pytest -q`: 549 passed, 2 optional skips (57.03 seconds).
- Ruff passed; zero-warning build and actual win-x64 shortcut publish passed.
- Desktop checker: isolated live HTTP/status/reservation/Reader workflows and
  portable WPF lifecycle smoke passed. Physical audio/clipboard/hotkey checks
  remain opt-in and were not run against the user's applications.
- Actual shortcut startup/lifecycle smoke passed. Evidence:
  `logs/service-center-startup-20260906/shortcut.json`,
  `service-center-startup.png` and `service-center.png` (synthetic preview values).
- The native test only registers a uniquely named disabled fixture task, never
  the production task. One early normalization-test fixture was left disabled
  after its assertion failed; its exact name/action/disabled state were verified
  before removal. Subsequent round trips clean up normally. Verified zero
  production Service Center startup entries, zero temporary startup-test tasks,
  and no default legacy startup task after tests.

No production service was launched/stopped, no startup enabled, no article,
clipboard, token or installed model changed. `models/MANIFEST.json` is the
pre-existing user-owned change and remains outside commits. Continue with
legacy scheduled-task ownership/control + conflict discovery, then T1 audit/T2.
