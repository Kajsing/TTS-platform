# V1 Completion Audit

This file records the pre-final completion audit for the local reader v1 goal:
a Windows-friendly localhost TTS service, local model-management flow, and
Chrome extension reader for long web-page text.

Status: pre-final audit.

Final security-focused pass: pending until the completion audit and any
remaining blockers are closed.

## Audit Summary

| Field | Value |
| --- | --- |
| Non-security done criteria | Ready for final validation |
| Final security-focused pass | Pending |
| Can mark v1 complete | No |
| Next step | Run the real final security-focused pass after any blockers from this audit are fixed |

## Done When Evidence

| # | Criterion | Current audit status | Authoritative evidence |
| --- | --- | --- | --- |
| 1 | Local server runs the intended TTS pipeline through stable localhost HTTP and WebSocket contracts. | Ready for final validation | `scripts/smoke_service.py`, `scripts/check_local_service_bootstrap.py`, `apps/tts_service/tests/test_api.py`, `apps/tts_service/tests/test_streaming.py`, and `scripts/release_check.py` local service bootstrap coverage. |
| 2 | Long page reading through the Chrome extension is covered by structural and service-level smoke checks. | Ready for final validation | `scripts/check_extension_reader_flow.py`, `scripts/check_extension.py`, `scripts/check_extension_onboarding.py`, and skip-aware `scripts/check_chrome_extension_smoke.py`. |
| 3 | Model management covers catalog listing, download/install, activation, checks, removal, checksum behavior, and safe archive handling. | Ready for final validation | `scripts/check_model_management_flow.py`, `apps/tts_service/tests/test_cli_models.py`, default `models/catalog.json`, and `docs/backend_model_setup.md`. |
| 4 | Windows first-run, bundle install, launchers, and per-user Task Scheduler service/autostart contracts are documented and tested. | Ready for final validation | `scripts/check_windows_bundle_bootstrap.py`, `scripts/check_windows_bundle_install.py`, `scripts/check_windows_launchers.py`, `scripts/check_windows_service_task.py`, and Windows bundle docs. |
| 5 | Security defaults for localhost binding, token auth, origin validation, model archive extraction, extension base URL handling, and release packaging are verified. | Ready for final validation | `scripts/check_security_defaults.py`, `scripts/check_extension.py`, model archive regression tests, release packaging checks, and the pre-final security hardening pass. |
| 6 | A final security-focused review has been run and accepted findings are fixed or explicitly recorded. | Pending | The pre-final security hardening pass does not replace this gate. Run the real final security-focused pass after this audit and any remaining blockers. |
| 7 | Documentation is updated to match actual repo behavior. | Ready for final validation | `README.md`, `TESTING.md`, `docs/backend_model_setup.md`, `docs/v1_readiness.md`, and `docs/codex/Documentation.md`. |
| 8 | Relevant automated validation passes are available and documented. | Ready for final validation | `python3 -m pytest -q`, `python3 -m ruff check .`, `python3 scripts/release_check.py`, and `python3 scripts/check_v1_readiness.py`. |
| 9 | Repo-level definition of done from `AGENTS.md` is satisfied for implemented slices. | Ready for final validation | Current code, tests, docs, release gates, and pushed commits satisfy the implemented-slice rules; final project completion still waits on the final security-focused pass. |

## Remaining Gates Before V1 Complete

1. Run any narrow fixes found by this completion audit.
2. Run the real final security-focused pass.
3. Fix or explicitly record accepted final security findings.
4. Run the required validation commands again.
5. Mark the goal complete only if every `Done When` item is proven by current
   evidence.

## Useful Commands

```bash
python3 scripts/check_v1_completion.py
python3 scripts/check_v1_completion.py --require-complete
python3 scripts/check_v1_readiness.py
python3 scripts/release_check.py
```

On Windows, use `py -3` when `python3` is unavailable.
