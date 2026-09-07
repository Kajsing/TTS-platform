# Article switch and deletion reliability

## Scope and field evidence

User reported switching folders/articles during playback, deletion followed by
a temporary unresponsive UI, a stale article row/editor and lost reading position.
The 17:54:15 local trace records `DocumentLoad` followed by
`restart_from_beginning: true`, moving the heard cursor from block 363 to zero.
The offline database confirms the requested deletion succeeded at 17:54:20.
The screenshot shows a different selected library row and displayed title, plus
the revision-conflict load error. The precise duration/cause of the reported
UI stall was not captured; no model/backend crash is proven by this incident.

## Changes

- `ReaderPlaybackCoordinator.LeaveDocumentAsync` preserves the heard position,
  cancels/releases the old run, then detaches its document. Transition ownership
  spans final cancellation/position persistence so a concurrent command cannot
  steal the document while it is being released. Explicit Stop still rewinds.
- Navigation, close, service preparation and privacy-session end use that path.
- `ReaderDocumentLoader` fetches current metadata, stages bounded blocks, checks
  revisions and deletion, and retries one revision race. UI publication checks
  the selection generation and folder visibility. A failed load retains the
  old editor mapping/text and restores its matching row or clears the selection.
- Delete confirmation names the article. Identity/version and operation guards
  are checked again after the modal loop, and concurrent delete/load is blocked.
  The confirmed deletion is removed locally before refresh; late list responses
  cannot reinsert it. Deleted/unavailable editor state and reading-page caches
  are cleared. Late playback visuals cannot overwrite another article's view.
- Added bounded metadata-only load/delete diagnostic outcomes.
- Draft chapter plan records automatic next-chapter playback in both views.
  No chapter implementation or U8 work is included.

## Local cleanup (explicit user authorization)

Verified Reader and port 7777 were stopped. Used the existing consistent SQLite
backup helper, with integrity OK. One of the two articles was already deleted;
soft-deleted the single remaining active article with an exact ID/version guard
using the existing Python repository operation. Read back zero active articles
and integrity OK. Historical soft-deleted rows, folders, grants, rules, settings,
voices and the user-owned dirty MANIFEST were preserved. Backup and trace are
local/ignored, not committed. The user can recover the articles from that backup.

## Validation

Final validation: 285 .NET tests passed (51 client, 142 application, 92 Windows).
Full Python: 626 passed, 2 optional skips; Ruff, scoped .NET format verification
and diff checks passed. Used `py -3` for the Windows Golden Commands, and the
per-user .NET 10 SDK instead of PATH's .NET 8. Zero-warning Release build and
self-contained win-x64 publish passed. Development WPF lifecycle smoke includes
`document_switch_safety=true` for stale rows, delayed/superseded load, failed load,
concurrent delete, failed refresh and externally deleted article. An initial WPF
build rejected three ambiguous reference comparisons in the new test harness;
made the intended identity checks explicit and rebuilt with zero warnings/errors.

`scripts/check_desktop_reader.py --require-dotnet --dotnet <per-user SDK>
--skip-build` passed isolated live HTTP paging/stream/resume/edit/append/delete
Undo, service/preview, portable package and WPF lifecycle/folder checks. Physical
Windows audio/integration gates were explicitly skipped, not claimed as passing.
Read the real root shortcut target and ran the newly published executable with
the isolated lifecycle fixture: `logs/article-switch-20260907/shortcut.json`
records `document_switch_safety=true` and all lifecycle/input/preview markers.
Production database readback still shows zero active articles and integrity OK.

No physical speaker/game-click reproduction or production model playback is
part of the automated smoke. Reader and service remain closed after publication.
Safe next step: ordinary user testing of the deployed shortcut. Broader chapter
work remains a draft awaiting an implementation go-ahead; U8 is unchanged.
