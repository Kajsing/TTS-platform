# Story-only default for future agent chapter imports

- Owner approved omitting clearly marked author notes by default for future
  imports. Updated the personal `reader-chapter-import` skill, its browser
  reference, repository import guide and current-status documentation.
- Notes require verified boundaries; ambiguous or mixed story/commentary stays.
  Explicit keep-notes requests override the default. Existing articles are not
  edited, and this change adds no Reader setting, parser, service filter or
  authorization to import a new story.
- Raw source and reviewed removal provenance remain separate from the cleaned
  delivery payload/hash. Full readback still requires exact equality with the
  cleaned bundle; duplicate receipts and retry payload rules are unchanged.
- Validation passed: Skill Creator validator; all 15 existing offline checker
  cases (`py -3 -m pytest -q apps/reader_agent/tests/test_chapter_bundle_check.py`);
  `py -3 -m ruff check .`; and `git diff --check`. Windows uses `py -3` in place
  of `python3`. The skill's source and discovery-junction hashes match.
- Manually reviewed the instruction boundaries for opening/closing notes,
  mid-chapter notes with subsequent prose, dialogue and mixed ambiguous text.
  No classifier code changed or live note-filtering import was tested. Existing
  checker tests establish payload/readback integrity, not note classification.
- No live Reader, service, browser, credential or article access was required.
  User-owned `models/MANIFEST.json` is excluded. No scope deviation or remaining
  implementation work; a future import still requires its own user request.
