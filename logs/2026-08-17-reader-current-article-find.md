# Reader Upgrade U1 — Current-Article Find

## Completed

- Added a compact current-article Find bar with literal/phrase, match-case,
  whole-word, and regex modes.
- Added `Ctrl+F`, `Enter`/`F3`, `Shift+F3`, and `Escape` behavior with wrapping
  next/previous navigation and bounded result counts.
- Added a pure bounded Find engine, full-document paging loader, cursor mapping,
  and revision-aware cache for structured and oversized articles.
- Added separate teal Find highlighting in the continuous editor and paged
  reader. Playback remains the highest-priority overlay and neither overlay
  changes font metrics or wrapping.
- Extended desktop source-shape validation and added engine, navigation,
  mapping, timeout, Unicode whole-word, and paging/cache tests.

## Validation

- `py -3 -m pytest -q`: 419 passed.
- `py -3 -m ruff check .`: passed.
- .NET solution tests: 116 passed.
- .NET format verification: passed.
- Release self-contained `win-x64` publish: passed.
- Full Windows Reader checker with required integration: passed, including
  Windows audio, clipboard/hotkey/tray lifecycle, portable package, and WPF
  render.
- Live UI smoke on a 105,328-character, 445-block article confirmed phrase,
  case, whole-word, regex, invalid-regex, next/previous, close, caret preservation,
  and playback coexistence.

## Notes

- The initial full package check encountered a file lock from the live Reader
  test process. The exact check passed after that process was closed.
- No plan deviation was required.
- `models/MANIFEST.json` was not changed or included by this work.
- U2 is the next planned upgrade and was not started.
