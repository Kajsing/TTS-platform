# Service Center goal and planning - 2026-09-05

- User approved service tray/status, compatible voices and optional Windows
  autostart; explicitly requested a goal, without a token budget.
- Registered the active app goal. Wrote `docs/reader_service_center_plan.md`
  with T1/T2 boundaries, lifecycle/security constraints and acceptance checks.
- Updated execution order, live status and the old tray backlog to agree.
- Reviewed MainWindow/tray ownership, service process leases/controller, health,
  desktop settings and the CLI/catalog. Existing tray dies with MainWindow;
  lifecycle separation and single-owner activation are the first code slice.
- Current compatible download catalog has one entry. Reuse and verify the
  installer rather than presenting arbitrary models as supported.
- Preserve unrelated dirty `models/MANIFEST.json`. No Reader, service, Windows
  task, token, article, installed model or user setting was changed here.
- Validation: documentation links/scope and `git diff --check` before commit.
  No runtime changes in this planning slice; runtime tests are T1/T2 acceptance,
  not claimed as performed for a documentation-only update.
- Remaining: all T1/T2 implementation and acceptance. Goal remains active;
  U8 remains parked. Safe to proceed with the documented T1.1 slice.
