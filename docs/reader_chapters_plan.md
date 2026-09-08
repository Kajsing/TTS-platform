# Reader chapters - draft, not yet implemented

User direction confirmed on 2026-09-07. This is a future side quest, not an
active implementation goal. Article-switch/deletion safeguards were completed
on Sep 7; the user then approved a separate pause/sleep reliability run on Sep 8.
Chapters remain the next separate run, not part of that deployment.
U8 remains parked.

- One article contains ordered chapters, with stable identities and no duplicate
  copies of its text. Existing service sections are the candidate foundation;
  verify their editing/cursor contracts before committing to a schema change.
- Clipboard Append normally starts a new chapter; offer a deliberate way to
  continue the current chapter instead. Preserve paragraph structure and Undo.
- Allow chapter names and manual boundaries after capture (start chapter at the
  caret and merge with the preceding chapter without deleting its text).
- Two views: one chapter at a time or the complete article. Switching view must
  preserve the heard cursor, selection where meaningful, and viewport context.
- **Confirmed:** playback automatically continues into the next chapter in
  either view. Viewing one chapter does not restrict playback to that chapter.
  Any optional stop-at-chapter-end setting is separate from the view setting.
- Keep a chapter list/navigation and a visible paused reading position. Preserve
  the Sep 8 pause/completion viewport and retained-marker safeguards when adding
  chapter view transitions; those fixes now have isolated WPF regression tests.
- Find must have explicit current-chapter versus whole-article scope.
- Reconcile MCP chapter deliveries with real chapter structure while preserving
  their existing retry-safe receipts. Do not silently infer old chapter borders
  from every paragraph or reconstruct missing history; old unstructured articles
  may start as a single chapter.

Proposed slices: chapter data and editing; views and continuous playback; then
capture/import/MCP integration. Chapter-specific audio export, chapter
reordering/deletion and automatic heading detection need later scope decisions.
