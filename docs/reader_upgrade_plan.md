# Reader Upgrade Plan

## Status

The user approved this upgrade track on 2026-08-17. U1 is the active target.
This track is prioritized ahead of the still-incomplete Reader Milestones 10
and 11. It does not mark PDF extraction or release-candidate work complete.

The existing v1 service, Reader library, Chrome integration, localhost security
defaults, playback behavior, source mapping, and revisioned editing remain
protected baselines.

## Product principles for this track

- Search and highlighting must not rewrite article text, alter line wrapping,
  move the playback position, or invalidate source offsets.
- Private article text, clipboard contents, search terms, folder names, access
  codes, and remote credentials must not appear in ordinary logs.
- Future multi-computer access must use Reader APIs and content revisions. Never
  synchronize the live SQLite file.
- Localhost remains the default. Planning a remote mode does not authorize
  exposing the current plain-HTTP service.
- The local `C:\project\Word-Highlighter` project is a product-behavior
  reference for U3: stable term colors, active toggles, occurrence counts, and
  jump-to-next behavior. Reader receives its own tested implementation rather
  than copying browser DOM code into WPF.
- Each upgrade is a separate validated vertical slice. Later work must not be
  pulled into an earlier upgrade merely because it is adjacent.

## Execution order

### U1: Current-article Find panel

**Purpose:** Find a word or phrase inside the open article without confusing it
with library-wide search.

Implementation scope:

- Add a compact Find bar above the article surface.
- Open it with `Ctrl+F`; close it with `Escape`.
- Support literal word and phrase matching by default.
- Add optional case-sensitive, whole-word, and regex modes.
- Navigate with Enter or `F3` for next and `Shift+F3` for previous.
- Show the current result and bounded total, for example `3 of 17`.
- Search the complete article, including documents larger than the current
  rendered page or continuous-editor limit.
- Scroll the selected result into view and show a non-layout-changing active
  match overlay.
- Bound regex pattern length, execution time, input work, and returned results.
  Invalid or timed-out regexes produce a clear non-fatal message.
- Keep ordinary user selection, Word Highlighter ranges, and playback ranges as
  separate visual concepts. Playback keeps the highest visual priority.

Acceptance criteria:

- Literal words and phrases find every expected occurrence in a multi-block
  article.
- Case-sensitive and whole-word options produce deterministic results.
- A valid regex finds expected results; invalid and pathological regexes cannot
  freeze the desktop UI.
- Next and previous navigation wrap predictably and report the current count.
- Find works across a document that exceeds the visible reading window.
- Opening, navigating, and closing Find do not edit text, create an Undo entry,
  change the saved Reader cursor, or start/stop playback.
- Highlighting does not change font weight, line height, wrapping, or paragraph
  spacing.
- Keyboard behavior and screen-reader names are covered by tests or explicit
  Windows smoke evidence.

Validation:

```powershell
py -3 -m pytest -q
py -3 -m ruff check .
dotnet test apps\desktop_reader\TtsPlatform.Reader.sln -c Release
dotnet format apps\desktop_reader\TtsPlatform.Reader.sln --verify-no-changes
py -3 scripts\check_desktop_reader.py --require-windows-integration
```

Also build the Release `win-x64` WPF target and manually verify literal,
phrase, regex, next, previous, close, playback coexistence, and a long article.

### U2: Clipboard prompt threshold and five-minute snooze

**Purpose:** Suppress low-value clipboard interruptions without weakening the
explicit clipboard-reading workflow.

Implementation scope:

- Add a configurable non-negative character threshold to desktop settings.
- Define the setting in user language as ignoring automatic prompts at or below
  the configured trimmed-text length. `0` disables the threshold.
- Apply the threshold only to automatic `New clipboard text` prompts. Explicit
  Read Clipboard and copy-selection hotkeys remain available.
- Add `Ignore for 5 minutes` to the clipboard prompt.
- Show the snooze-until time and a `Resume now` action in Reader status.
- Do not replay clipboard changes that occurred during the snooze.
- Persist only preference/timing metadata, never clipboard text.

Acceptance criteria:

- Text at or below the threshold does not open an automatic prompt.
- Text above the threshold still follows the existing prompt workflow.
- Manual clipboard actions ignore the automatic-prompt threshold.
- Snooze and resume are deterministic under an injectable clock.
- No clipboard text is added to settings or logs.

### U3: Persistent Word Highlighter

**Purpose:** Make recurring names, terms, and phrases visually scannable while
reading.

Implementation scope:

- Begin with one Reader-owned global term list.
- Allow terms and phrases, active/inactive toggles, stable automatic colors,
  occurrence counts, and jump-to-next behavior.
- Prefer longer overlapping phrases before shorter terms.
- Match Unicode words consistently and keep matching case-insensitive by
  default.
- Persist highlighter configuration through the Reader service so a future
  remote client can share it through APIs.
- Render background-only ranges without changing document text or metrics.
- Preserve this visual priority: playback, normal selection, word highlights.
- Defer arbitrary persistent-regex highlighting until literal/phrase behavior
  is stable; U1 already provides bounded ad-hoc regex Find.

Acceptance criteria:

- Colors remain stable across Reader restarts.
- Counts and next-match navigation cover the full article.
- Toggling one term does not rebuild or move article text.
- Playback remains unambiguous when it overlaps a word highlight.
- Structured and oversized reading views behave consistently with the
  continuous editor.

Decision gate before expansion: confirm whether per-article term additions are
needed after the global-list version.

### U4: Folder-backed library organization

**Purpose:** Organize articles without coupling folders to filesystem paths.

Implementation scope:

- Add a versioned Reader schema migration, domain model, repository operations,
  protected API contracts, and desktop folder navigation.
- Start with flat folders and an implicit root called `All articles`.
- Create, rename, list, and delete folders with row-version conflict handling.
- Move one or multiple articles between a folder and the root.
- Filter library paging and search by folder.
- When deleting a folder, offer either move its articles to the root or delete
  the folder and its articles through one explicit transactional operation.
- Show affected article counts before destructive confirmation.

Acceptance criteria:

- Folder changes are transactional and survive restart.
- Articles appear in exactly one folder or the implicit root.
- Search, paging, queue, playback, editing, bookmarks, and exports remain valid
  after a move.
- Folder deletion cannot strand article rows or partially delete content.

### U5: Batch import and text-only HTML workflow

**Purpose:** Import several articles efficiently and place them directly in the
right folder.

Existing baseline: single-file TXT, Markdown, HTML, DOCX, and EPUB import is
already implemented. HTML import is offline and semantic-text-only; it removes
scripts, styles, forms, and navigation and performs no network fetches.

Implementation scope:

- Enable multi-select in the file picker and multiple-file drag/drop.
- Add a bounded import queue with one destination folder selection.
- Preview validation and warnings per file.
- Continue past individual failures and provide a final success/failure report.
- Support cancelling files that have not yet committed.
- Keep each successful document as its own transaction and article.

Acceptance criteria:

- A mixed-format batch imports every valid file and reports invalid files.
- HTML produces readable semantic text with no active content or network use.
- Imported articles land in the selected folder.
- Cancellation leaves committed documents intact and unstarted files absent.

### U6: Folder privacy lock

**Purpose:** Hide selected folders inside Reader until the user supplies an
access code.

This is a security decision gate. The recommended first version is an honest
application-level privacy lock, not encryption at rest. Article text would
still exist in the local database and backups. True encryption is a separate
architecture requiring search, playback, export, backup, recovery, and key
management design.

Minimum privacy-lock requirements if approved:

- Never store the access code in plaintext; store a salted slow password hash.
- Unlock through a bounded session and support automatic relocking.
- Require an unlocked session to list titles, search, read, move, export, or
  delete protected articles.
- Require the current code to remove or change the lock.
- Define forgotten-code and owner-recovery behavior before implementation.
- Label the feature `Privacy lock`, not `Encrypted folder`.

### U7: Remote Reader security and architecture decision

**Purpose:** Design single-owner access from another computer without weakening
the protected localhost baseline.

This milestone is documentation, threat modeling, and a bounded feasibility
spike before product implementation. The existing
`--allow-non-local-host` flag is not a finished server mode: the service uses
plain HTTP, one shared bearer token, and the desktop client intentionally
rejects non-localhost addresses.

Required decisions and spike evidence:

- Limit the first product to the owner's trusted LAN; internet access should use
  a user-managed VPN rather than direct public port exposure.
- Choose HTTPS/WSS certificate creation and client certificate-pinning behavior.
- Design one-time pairing, per-device credentials, revocation, and rotation.
- Decide which Reader APIs a remote device may use and how rate limits apply per
  device.
- Preserve revision conflicts for simultaneous edits.
- Define reversible Windows Firewall setup/removal.
- Keep Chrome-extension remote access out of the first server slice unless
  explicitly approved later.

Acceptance criteria:

- A written threat model and ADR amend the current localhost-only assumptions.
- The spike proves encrypted Reader HTTP and WebSocket traffic on Windows.
- No code path silently enables remote binding or plain-HTTP remote tokens.
- The user approves the security design before U8 begins.

### U8: Secure LAN server beta

**Purpose:** Let a paired Reader desktop on another computer use the service,
library, folders, and TTS engine on the owner-controlled server computer.

Implementation scope depends on U7, but must include:

- Explicit disabled-by-default LAN server profile and selected bind interface.
- HTTPS/WSS only for non-loopback clients.
- One-time pairing and per-device protected credentials.
- Connected-device list, last-used metadata, revocation, and rotation.
- Remote connection profiles in the desktop Reader.
- Reversible firewall configuration and clear diagnostics.
- Windows integration smoke using two logical clients and conflict tests.

The server beta is not multi-user collaboration, cloud sync, or public-internet
hosting. Remote clients use the server-owned library; they do not synchronize
SQLite files or maintain an offline replica in this milestone.

## Deferred Reader milestones

Reader Milestone 10 (PDF text extraction) and Reader Milestone 11 (backup,
packaging, accessibility, security, and release candidate) remain incomplete.
They resume only after the user completes or deliberately pauses this upgrade
track.

## Current resume point

Start U1. Do not begin U2 until U1 acceptance criteria and validation pass or
the user deliberately reorders the track.
