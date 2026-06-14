# V1 Completion Audit

This file records the final completion audit for the local reader v1 goal: a
Windows-friendly localhost TTS service, local model-management flow, and Chrome
extension reader for long web-page text.

Status: v1 complete.

Final security-focused pass: complete. Accepted final security findings were
fixed in the working tree and recorded in `docs/v1_final_security.md`.

## Audit Summary

| Field | Value |
| --- | --- |
| Done criteria | 9 ready |
| Final security-focused pass | Complete |
| Can mark v1 complete | Yes |
| Completion gate | `python3 scripts/check_v1_completion.py --require-complete` |

## Final Security Evidence

The final security-focused review ran as scan
`a1645b6_20260614T200121`. Its rendered report is:

- `C:\tmp\codex-security-scans\TTS-platform\a1645b6_20260614T200121\report.html`
- `C:\tmp\codex-security-scans\TTS-platform\a1645b6_20260614T200121\report.md`

The final report has 0 open reportable findings. Five candidates were accepted
and fixed during the pass:

- `CAND-SERVICE-API-001`
- `CAND-MODEL-CORE-001`
- `CAND-MODEL-CORE-002`
- `CE-COV009-AUDIO-QUEUE-DOS-001`
- `CE-COV009-DOM-EXTRACTION-DOS-001`

See `docs/v1_final_security.md` for the stable repository summary.

## Done When Evidence

| # | Criterion | Current audit status | Authoritative evidence |
| --- | --- | --- | --- |
| 1 | Local server runs the intended TTS pipeline through stable localhost HTTP and WebSocket contracts. | Ready | `scripts/smoke_service.py`, `scripts/check_local_service_bootstrap.py`, `apps/tts_service/tests/test_api.py`, `apps/tts_service/tests/test_streaming.py`, and `scripts/release_check.py` local service bootstrap coverage. |
| 2 | Long page reading through the Chrome extension is covered by structural and service-level smoke checks. | Ready | `scripts/check_extension_reader_flow.py`, `scripts/check_extension.py`, `scripts/check_extension_onboarding.py`, and skip-aware `scripts/check_chrome_extension_smoke.py`. |
| 3 | Model management covers catalog listing, download/install, activation, checks, removal, checksum behavior, and safe archive handling. | Ready | `scripts/check_model_management_flow.py`, `apps/tts_service/tests/test_cli_models.py`, default `models/catalog.json`, and `docs/backend_model_setup.md`. |
| 4 | Windows first-run, bundle install, launchers, and per-user Task Scheduler service/autostart contracts are documented and tested. | Ready | `scripts/check_windows_bundle_bootstrap.py`, `scripts/check_windows_bundle_install.py`, `scripts/check_windows_launchers.py`, `scripts/check_windows_service_task.py`, and Windows bundle docs. |
| 5 | Security defaults for localhost binding, token auth, origin validation, model archive extraction, extension base URL handling, and release packaging are verified. | Ready | `scripts/check_security_defaults.py`, `scripts/check_extension.py`, model archive regression tests, release packaging checks, and the final security pass. |
| 6 | A final security-focused review has been run and accepted findings are fixed or explicitly recorded. | Ready | `docs/v1_final_security.md`, the scan report paths above, and the focused regression tests listed there. |
| 7 | Documentation is updated to match actual repo behavior. | Ready | `README.md`, `TESTING.md`, `docs/backend_model_setup.md`, `docs/v1_readiness.md`, `docs/v1_final_security.md`, and `docs/codex/Documentation.md`. |
| 8 | Relevant automated validation passes are available and documented. | Ready | `python3 -m pytest -q`, `python3 -m ruff check .`, `python3 scripts/release_check.py`, `python3 scripts/check_v1_readiness.py`, and `python3 scripts/check_v1_completion.py --require-complete`. |
| 9 | Repo-level definition of done from `AGENTS.md` is satisfied for implemented slices. | Ready | Current code, tests, docs, release gates, and pushed commits satisfy the implemented-slice rules. |

## Useful Commands

```bash
python3 scripts/check_v1_completion.py
python3 scripts/check_v1_completion.py --require-complete
python3 scripts/check_v1_readiness.py
python3 scripts/release_check.py
```

On Windows, use `py -3` when `python3` is unavailable.
