# Reader Upgrade Track A (U2 and U3)

## Completed

- Added a configurable automatic clipboard-prompt minimum, defaulting to 50
  trimmed characters; 0 disables the threshold.
- Added a persistent five-minute clipboard-prompt pause, visible expiry, and
  Resume now without storing or replaying clipboard content.
- Added Reader schema migration 007 and protected revisioned GET/PUT APIs for
  one global highlighter term list.
- Added stable service-owned colors, active toggles, literal word/phrase
  matching, longer-overlap priority, full-article counts, and next navigation.
- Added a Word Highlighter desktop dialog and separate background-only visual
  ranges for the continuous editor and structured/oversized reading pages.
- Preserved visual priority: playback, normal text selection, word highlights.

## Validation

- `py -3 -m pytest -q`: 423 passed.
- .NET Release solution tests: 123 passed.
- Standalone WPF build: passed with zero warnings.
- Ruff, .NET formatting, Reader contracts (15), and `git diff --check`: passed.
- Required Windows integration check: audio, clipboard listener, hotkeys, tray,
  package, packaged WPF render, live Reader flows, and schema 7 passed.

## Decisions and boundaries

- U3 starts with one global list; per-article terms remain a later decision.
- Persistent arbitrary regex highlighting remains deferred; U1 Find supplies
  bounded ad-hoc regex search.
- No architecture, security, licensing, deployment, cloud, or model change was
  introduced. The unrelated local `models/MANIFEST.json` change was preserved.
