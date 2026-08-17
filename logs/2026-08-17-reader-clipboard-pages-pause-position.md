# Reader clipboard pages and pause position

## Completed

- Split future multi-paragraph clipboard appends into normal Reader blocks so
  the bounded reading window can advance between them.
- Kept each complete clipboard capture as one atomic Undo/Redo operation.
- Remapped saved playback positions and bookmarks safely when a grouped append
  is undone.
- Kept compatibility with legacy single-block append history.
- Made the reading view bring the exact highlighted sentence into view inside
  legacy oversized blocks.
- Mapped the last fully heard playback cursor back to the continuous editor
  caret and viewport on Pause.

## Validation

- `py -3 -m pytest -q`: 417 passed.
- `.NET Release tests`: 98 passed.
- `py -3 -m ruff check .`: passed.
- `.NET format --verify-no-changes`: passed.
- `git diff --check`: passed.
- `py -3 scripts\check_desktop_reader.py --require-windows-integration`:
  passed, including live Reader flows, Windows integration, packaging, and WPF
  rendering.

## Assumptions and deviations

- A natural clipboard paragraph boundary remains a blank line, matching the
  existing plain-text document parser.
- Existing oversized blocks were intentionally not rewritten because a data
  migration would add cursor, bookmark, and edit-history risk. Exact in-block
  scrolling provides compatibility without changing user content.
- No API, database schema, model, voice, security, licensing, or deployment
  change was needed.
