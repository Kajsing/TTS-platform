# Service Center T2: local voice installation foundation

Date: 2026-09-06. Partial T2 delivery; full goal remains active.

## Completed

- Added fixed local JSON-lines `model_manager` list/install bridge, reusing the
  CLI and repository catalog. No new HTTP/MCP management endpoint or dependency.
- Added bounded metadata, package-specific license/catalog review, installed
  inventory, progress, cooperative cancellation/owner-pipe closure, sanitized
  failure events and explicit restart-required outcome without activation.
- Added shared installer controls, bytewise download/hash/extraction checkpoints,
  staged structural/type/nonempty asset checks, optimistic manifest comparison,
  cross-process commit lock and flushed atomic manifest replacement.
- Fixed the old installer gap where manifest failure could leave published files
  without a registered voice. Caught commit failures now roll back new files and
  restore an explicitly overwritten legacy CLI package.
- Multi-voice catalog entries publish one shared package and all speaker entries
  together. CLI remove/overwrite protects dependent entries; removal participates
  in the same lock. Redirected install directories are rejected.
- Added `docs/reader_service_center_voices.md` with bridge contract, truthful
  readiness/cancellation semantics and remaining UI/preview/default work.

## Validation

- `py -3 -m pytest -q apps/tts_service/tests/test_cli_models.py
  apps/tts_service/tests/test_model_installation.py
  apps/tts_service/tests/test_model_manager.py`: 109 passed in 2.71s.
- `py -3 -m pytest -q`: 593 passed, 2 optional skips in 56.00s.
- `py -3 -m ruff check .`: passed. `git diff --check`: passed.
- Synthetic archives and mocked HTTP covered checksum/download/extraction
  failures, missing/empty/wrong-type assets, cancellation at precommit phases,
  late cancellation, manifest-write failure and overwrite rollback, concurrent
  manifest edits, review changes, existing-voice conflicts and shared packages.
- Real helper subprocess tests covered JSON-lines result/error output, explicit
  stdin cancellation and pipe closure without forced process termination.
- Read-only production inventory: contract 1, result success, 5 installed voices,
  1 catalog package already present, 0 installable packages, valid config;
  manifest SHA-256 unchanged before/after.
- Reader process and port 7777 listener were absent at the read-only check.
  No real service/model/clipboard/article/config/startup mutation occurred.

## Assumptions and boundaries

The local subprocess is a supporting implementation choice within the approved
Python/WPF architecture and local-only security boundary. No product, license or
network direction changed. A future GUI must use fixed arguments and retain its
helper until cancellation/commit actually finishes, not kill on an observation
timeout. Asset checks are not native engine readiness or audible quality tests.
The package/manifest protocol is not a power-loss transaction across paths;
uncertain staging/backup directories require review, not automatic destruction.

No .NET code changed or desktop binary was republished in this slice. The
previously validated/published T1 tray and autostart remain the desktop version.
Preserved the unrelated machine-local `models/MANIFEST.json` worktree change.

## Next

Connect WPF installed/packages UI, progress/cancellation and helper ownership;
verify/expand primary-source catalog metadata; implement non-overlapping preview
and explicit service-default selection; run desktop smoke and exact-shortcut
publication while safely closed. Continue autonomously within the approved T2
boundaries. Do not complete the goal or resume U8 yet.
