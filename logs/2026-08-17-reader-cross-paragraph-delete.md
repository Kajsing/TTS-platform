# Reader cross-paragraph selection deletion

## Completed

- Allowed a normal continuous-editor selection deletion to cross hidden Reader
  paragraph boundaries.
- Kept the changed text local until Save, matching existing edit behavior.
- Added one atomic range mutation through the existing content endpoint using
  an optional end-block anchor.
- Added one-step Undo/Redo with transactional restoration of removed blocks,
  ordinals, positions, bookmarks, and later content.
- Preserved UTF-16 offsets at the HTTP/.NET boundary and compatibility with the
  existing schema and single-paragraph edit requests.
- Kept cross-paragraph replacement text out of scope; only contiguous selection
  deletion is accepted across blocks.

## Validation

- `py -3 -m pytest -q`: 419 passed.
- `.NET Release tests`: 100 passed.
- Ruff, .NET formatting, and `git diff --check`: passed.
- Complete Windows desktop integration check: passed, including live C#
  cross-paragraph Delete plus one-step Undo, WASAPI, clipboard/hotkeys/tray,
  self-contained packaging, and packaged WPF rendering.
- Manual WPF check: Ctrl+A followed by Delete enabled Save/Revert, and Revert
  restored the editor without persisting the temporary deletion.

## Assumptions and deviations

- Editable Reader documents use one section; the repository rejects a range
  crossing section ownership rather than silently flattening structured text.
- The existing `replace` edit type carries explicit range metadata, avoiding a
  schema migration while retaining bounded history and old-client behavior.
