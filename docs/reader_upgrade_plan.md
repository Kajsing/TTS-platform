# Reader Upgrade Plan

## Status

The user approved this upgrade track on 2026-08-17. Track A (U1 through U3),
Track B (U4 through U6), and the U7 remote-security decision are complete. On
2026-08-19 the user approved an optional remote workspace over owner-managed
WireGuard while preserving the existing local Reader as the default. That
approval is not authorization to expose the current service remotely or begin
U8 unless the user also asks to continue.
This track is prioritized ahead of the still-incomplete Reader Milestones 10
and 11. It does not mark PDF extraction or release-candidate work complete.

On 2026-09-05 the user reaffirmed parking U8 and selected Reader Agent Access
M1 as the next project target. See `reader_agent_access_plan.md`; its local MCP
integration is now complete. U8's pending acceptance is preserved below.
The user manually stopped the U8 app goal, M1 registration succeeded, and the
user asked to revisit U8 after M1. Confirm its intended network setup then.

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
- Local and remote workspaces remain separate in the first remote version. A
  remote connection must not overwrite, migrate, or disable the local library.
- WireGuard is the recommended first private-network transport, but it remains
  outside the Reader protocol and can be replaced without changing Reader data
  or API contracts.
- The local `C:\project\Word-Highlighter` project is a product-behavior
  reference for U3: stable term colors, active toggles, occurrence counts, and
  jump-to-next behavior. Reader receives its own tested implementation rather
  than copying browser DOM code into WPF.
- Each upgrade is a separate validated vertical slice. Later work must not be
  pulled into an earlier upgrade merely because it is adjacent.

## Execution order

### U1: Current-article Find panel — complete

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

### U2: Clipboard prompt threshold and five-minute snooze — complete

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

### U3: Persistent Word Highlighter — complete

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

### U4: Folder-backed library organization — complete

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

Follow-up (2026-09-05): **Article folders -> Open** is a clickable visibility
preference, not a Privacy-lock status. Checked shows the folder's articles;
unchecked excludes them from the local library, search and paging until reopened.
The folder remains in Article folders. The setting is remembered per desktop
workspace/profile and service URL, defaults open for existing folders, and does
not modify articles, grants, Privacy-lock sessions, or other clients. Existing
queue/export records are not deleted; opening/playing a closed folder's article
requires reopening the folder. This is not a confidentiality boundary.

Closing the current folder clears its displayed article only after saving the
preference. Active/paused playback, loading or unsaved edits block the operation
with guidance; settings-save failure restores the checkbox. Hidden-only paging
scans at most five service pages per action, then retains Load more if needed.
The isolated WPF smoke covers the actual checkbox, hide/reopen, settings reload,
editor clearing, unsaved edits and save failure without accessing live data.

### U5: Batch import and text-only HTML workflow — complete

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

The user approved an honest application-level privacy lock as the first
version, not encryption at rest. Article text would
still exist in the local database and backups. True encryption is a separate
architecture requiring search, playback, export, backup, recovery, and key
management design.

Minimum privacy-lock requirements:

- Never store the access code in plaintext; store a salted slow password hash.
- Unlock through a bounded session and support automatic relocking.
- Require an unlocked session to list titles, search, read, move, export, or
  delete protected articles.
- Require the current code to remove or change the lock.
- Forgotten-code recovery uses a high-entropy one-time recovery key shown only
  during setup, code change, or a successful recovery. The key can set a new
  code without the old code, is stored only as a salted slow hash, and is
  rotated after every use.
- Label the feature `Privacy lock`, not `Encrypted folder`.

Implemented session and safety boundary:

- Codes and recovery keys use PBKDF2-SHA256 with independent random salts and
  310,000 iterations; plaintext credentials never enter the database or logs.
- Successful setup/unlock/recovery creates an opaque, folder-bound session held
  only in service memory for 15 minutes. Several folders may be unlocked at
  once, with a hard 32-session request bound.
- Relock, code change, lock removal, session expiry, and service restart
  invalidate access. The desktop hides an open protected article when its local
  session ends and clears sessions when it stops or loses the service.
- Five failed code/recovery attempts within five minutes are throttled. Locked
  folders conceal names and article counts, and protected documents are absent
  from list/search/queue/export/diagnostic/open-request results until unlocked.

### U7: Remote Reader security and architecture decision — complete

**Purpose:** Design single-owner access from another computer without weakening
the protected localhost baseline.

This milestone is documentation, threat modeling, and a bounded feasibility
spike before product implementation. The existing
`--allow-non-local-host` flag is not a finished server mode: the service uses
plain HTTP, one shared bearer token, and the desktop client intentionally
rejects non-localhost addresses.

Required decisions and spike evidence:

- Limit the first product to an owner-controlled private network. Internet
  access uses self-hosted WireGuard rather than direct public Reader exposure.
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

Completed design and spike evidence:

- `docs/reader_remote_security.md` defines the threat model, a separate secure
  gateway that preserves localhost, ECDSA P-256 server identity with SHA-256
  SPKI pinning, out-of-band one-time pairing, per-device credentials,
  revocation/rotation, route classification, per-device limits, revision
  conflicts, VPN boundary, and reversible Windows Firewall design.
- `scripts/check_reader_secure_transport.py --require-windows` proved the
  actual Reader application over pinned HTTPS and WSS on Windows. It negotiated
  TLS 1.3, rejected a wrong pin and plain HTTP, completed protected Reader HTTP
  plus marked PCM WebSocket playback, bound only to `127.0.0.1`, changed no
  firewall state, and removed all temporary files.
- U7 added no production listener, remote credential, config profile, firewall
  rule, cloud/paid dependency, or change to the desktop localhost validator.
- On 2026-08-19 the user approved the revised design: the current local Reader
  remains available and default, remote access is an optional mode, and
  self-hosted WireGuard is the recommended first transport. The user started U8
  on 2026-08-19 and deliberately parked it on 2026-08-24 while playback
  diagnostics are collected.

### U8: Secure private-network server beta - parked, acceptance incomplete

**Purpose:** Let a paired Reader desktop on another computer use the service,
library, folders, and TTS engine on the owner-controlled server computer.

Implementation scope depends on U7, but must include:

- Explicit disabled-by-default remote server profile and selected private or
  WireGuard bind interface.
- HTTPS/WSS only for non-loopback clients.
- One-time pairing and per-device protected credentials.
- Connected-device list, last-used metadata, revocation, and rotation.
- Named Local and Remote connection profiles in the desktop Reader. Local is
  the default, continues to use the existing localhost service and library,
  and remains healthy when remote access is unavailable or disabled.
- Reversible firewall configuration and clear diagnostics.
- Windows integration smoke using two logical clients and conflict tests.
- WireGuard setup remains an external, replaceable prerequisite; Reader does
  not install, configure, or require a hosted VPN control service.

The server beta is not multi-user collaboration, cloud sync, or direct public
Reader hosting. It may be reached across the internet only inside the approved
private network. Remote clients use the server-owned library; they do not
synchronize SQLite files or maintain an offline replica in this milestone.

## Deferred Reader milestones

Reader Milestone 10 (PDF text extraction) and Reader Milestone 11 (backup,
packaging, accessibility, security, and release candidate) remain incomplete.
They resume only after the user completes or deliberately pauses this upgrade
track.

## Service Center - promoted to active goal

On 2026-09-05 the user requested considering a tray icon for the local service,
because Reader can be closed while the service remains running unnoticed.
The user subsequently approved two stages: T1 persistent tray/status and safe
service controls, then T2 compatible-voice installation/selection. They explicitly
requested a goal and an optional Windows-autostart setting, off by default.
`reader_service_center_plan.md` is now the active scope and acceptance plan.
Reader's existing minimize-to-tray option is not independent service presence.
No autostart is enabled merely by recording this plan or testing the feature.

## Current resume point

Reader Agent Access M1 is complete; see `reader_agent_access_plan.md` and
`reader_agent_mcp.md`. Before more remote-access work, bring U8's remaining
acceptance back to the user and confirm the intended WireGuard environment.
The active next work is Service Center T1.1, followed by the remaining T1 checks
and T2. The new goal is registered, but implementation is not yet deployed.

U1 through U7 are complete. U8 implementation and its isolated live gateway
smoke are complete; final acceptance awaits a reversible elevated firewall
create/status/remove pass on the owner's intended WireGuard interface. The
milestone is deliberately parked until the user asks to resume it. The working
local Reader remains the default and remote access remains disabled
until that explicit setup. U3 deliberately begins with one global
literal/phrase list; the per-article expansion decision remains deferred until
the global behavior has been used in practice.
