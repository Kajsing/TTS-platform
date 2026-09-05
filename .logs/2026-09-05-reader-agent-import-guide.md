# Reader chapter import guide and offline preflight

- User requested a reusable skill/guide explaining the slow first field import.
- Diagnosed orchestration failures: direct HTTP 403 with ordinary browser access
  available, distinct browser/Windows clipboards causing URL-only deliveries,
  unsupported browser content export, and a navigation-read race.
- Added a sanitized public import guide, MCP-doc cross-link and current-status
  correction. No article content, production IDs, keys or reading URLs committed.
- Created personal `reader-chapter-import` instructions and browser-transfer
  reference using skill-creator. Kept automatic discovery enabled and imported
  no data while developing the skill.
- The personal source is under `.codex/skills`; a same-user directory junction
  exposes that one copy under the currently documented `.agents/skills`
  discovery location. Both entrypoint hashes match. No Codex config was changed.
- Added an offline-only package checker with synthetic regression tests for
  URL-only bodies, truncation, hash/count/order/identity errors, Unicode, Reader
  normalization and exact full readback. This is an orchestration helper, not a
  new Reader API, scheduler, website scraper or live integration test.
- Validation: 15 new offline regression cases passed; full `py -3 -m pytest -q`
  passed (537 tests, 2 pre-existing optional skips). `py -3 -m ruff check .`,
  formatting checks and `git diff --check` passed. Skill Creator's validator
  accepted the completed personal skill.
- Windows used `py -3` rather than `python3`. The skill validator needed PyYAML,
  which was installed only into ignored `logs/skill-validation-runtime`, not
  the active service or agent environment. No production import was repeated.
- Preserved the user's unrelated `models/MANIFEST.json` changes unstaged.
