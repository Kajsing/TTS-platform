# Reader Upgrade Track B — U4 and U5

Date: 2026-08-18

## Completed

- Added schema 8 flat Reader folders and nullable document membership.
- Added protected, versioned folder CRUD, atomic multi-document moves,
  folder-filtered paging/search, and transactional folder deletion modes.
- Added WPF folder filtering, management, counts, and multi-article moves.
- Added destination-aware single import and bounded 1–100 file batch import via
  picker or drag/drop.
- Added per-file preview warnings/status, continue-on-error, and cancellation
  that preserves committed articles and omits unstarted files.
- Updated API examples, structural checks, Reader docs, and automated tests.

## Validation

- `py -3 -m pytest -q`: 425 passed.
- `py -3 -m ruff check .`: passed.
- `.NET Release tests`: 127 passed (31 client, 75 application, 21 Windows).
- Standalone WPF Release build: passed with 0 warnings.
- `.NET format --verify-no-changes`: passed.
- `py -3 scripts\check_reader_contracts.py`: 18 fixtures passed.
- `git diff --check`: passed.

## Assumptions and deviations

- The root remains implicit; an article has one folder id or no folder id.
- Batch work is orchestrated by the desktop over the existing preview/commit API
  so each successful file remains an independent transaction.
- No architecture, security, licensing, deployment, cloud, or dependency change.
- U6 is intentionally paused before implementation because its plan requires a
  forgotten-code recovery decision.
- The pre-existing `models/MANIFEST.json` change was not modified or included.
