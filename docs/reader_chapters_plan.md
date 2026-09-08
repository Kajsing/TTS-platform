# Reader chapters - approved implementation plan

User direction confirmed on 2026-09-07; implementation approved on Sep 8 after
the separate pause/sleep reliability run. The user explicitly approved independent
chapter markers rather than repurposing import sections. No app goal was requested.
U8 remains parked.

- One article contains ordered chapter markers anchored by stable block ID and
  character offset, with no duplicate copies of its text. Existing import
  sections retain their current meaning. Markers use versioned, bounded document
  metadata and transactional edit-history snapshots; no destructive migration.
  Internal offsets are Unicode code points, explicitly named in the metadata;
  desktop cursor/mutation requests retain the existing UTF-16 wire convention.
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

## Implemented behavior (Sep 8)

- The toolbar above the article offers a chapter dropdown, navigation arrows,
  **One chapter at a time**, and **Chapter tools**. Navigation does not start or
  restart speech. Normal Play/Stop/Start at cursor keep their existing meanings.
- **Chapter tools > Start chapter at cursor** creates a boundary at the exact
  insertion caret. Rename changes only its title. Merge with previous removes
  only the boundary, after confirmation; it does not delete either chapter's text.
- Clipboard **Add to open article** defaults to **Start a new chapter**. Uncheck
  it to append more text to the last chapter. One append remains one Undo step.
- In chapter view, editing reconstructs the full canonical paragraph before
  saving. Hidden prefixes, suffixes and other chapters are preserved. Existing
  paragraph-at-a-time save rules still apply; save/revert before changing views
  or chapter boundaries. A range deletion can cross chapter boundaries in whole
  article view. Undo/Redo restore both the text and exact chapter marker IDs.
- Find defaults to the whole article; **Current chapter only** is explicit.
  A whole-article match can open a hidden chapter. Save/revert an edit before
  switching to another chapter or searching only the current chapter.
- Follow reading opens the next chapter when its first audio becomes audible.
  Merely preparing audio does not advance the chapter view. Paused/completed
  reading retains the last mark; no bold/font/line-height changes are introduced.
- Chapter views use the existing continuous editable-text path (at most
  1,000,000 characters and 20,000 blocks). Larger articles retain the existing
  bounded page-based reader. Structured imports remain read-only until explicitly
  duplicated as editable text. These pre-existing bounds are not raised here.
- View mode is session-local. No networking setup, credentials, voices or
  automatic chapter inference are changed. U8 remains parked.

## Contract and compatibility

`POST /v1/reader/documents/{document_id}/chapters` uses owner authentication,
folder privacy checks, the content lease and optimistic `expected_row_version`.
Its body contains `action` (`add`, `rename`, `merge`), optional `chapter_id`,
`title`, `block_id` and UTF-16 `character_offset`. The response is the ordinary
Reader mutation response with the updated document. An add requires a valid
owned block/caret; the first chapter cannot be merged away. Titles are trimmed
and limited to 300 characters, with at most 1,024 chapters per article.

The document response carries `metadata.chapter_markers_v1`, an ordered list
of `{id, title, block_id, codepoint_offset}`. Missing metadata means one implicit
`root` chapter, not guessed import boundaries. There is no SQL schema change.
Marker edits advance content revision and row version without altering text.
Edit history includes marker snapshots in its byte budget and retains only a
contiguous undoable suffix. Whole-paragraph saves preserve boundaries in their
unchanged prefix and suffix. Deleting content collapses coincident/empty final
boundaries; Undo restores them.

Append accepts optional `new_chapter` (API default false for old clients) and
`chapter_title`. Reader sends true by default. MCP `deliver_chapter` always adds
one marker with its delivery title; retries still return the original receipt
without appending text or another marker. Previous receipts are not replayed or
retroactively converted. Existing import sections keep their original meaning.
The already authenticated remote Reader gateway explicitly allows the same
chapter mutation route; no listener/firewall/VPN is enabled by this change.

Speech compilation splits its input at chapter anchors, including those inside
a paragraph, so one audible highlight cannot span two chapters. Source block
counts, window limits, character accounting and continuation cursors remain
unchanged. MP3 export remains whole-article/queue export.

Deploy Reader and service together. An old service can still read the database,
but does not maintain new chapter anchors during edits: do not use old binaries
to edit chaptered articles. Back up the service-owned database before a deliberate
rollback. This run does not rewrite or reset the live library.
