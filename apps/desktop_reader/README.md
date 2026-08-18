# TTS Platform Reader Desktop

This directory contains the Windows-native Reader Workstation client. It uses
C#, XAML, WPF, and .NET 10 while retaining the Python service as the only owner
of synthesis and the canonical Reader database.

## Current feature boundary

The Milestone 9 Reader beta provides:

- strict `http://localhost` or `http://127.0.0.1` service validation;
- a token-file source (the bearer token is never copied into settings JSON);
- actionable service, token, Reader, and voice readiness states;
- paged library browsing and title search;
- continuous editing for plain-text, clipboard, selection, and text-file
  documents, including atomic cross-paragraph selection deletion plus durable
  Undo and Redo through integer row versions;
- read-only display for structured source types;
- protected Reader WebSocket playback with strict mark/binary validation;
- NAudio 2.3 shared-mode WASAPI PCM output with a continuous two-second target
  across speech fragments, a hard ten-second memory limit, and played-byte
  checkpoints for a truthful Pause resume position;
- Play/Pause/Stop, whole-document section navigation that stays hidden for
  single-section articles, a 64-block reading viewport, layout-stable
  source-span highlighting with no font-weight changes, durable Pause resume
  from the last fully played UTF-16 cursor, Stop-to-beginning behavior, and a
  separate explicit `Start at cursor` action;
- active-stream content leases, next-window continuation, and a consistent
  SQLite preview-snapshot command;
- explicit Read Clipboard without monitoring or document persistence;
- clipboard prompt mode, off by default, with Read, append, create, Inbox,
  ignore, and executable-block actions; the prompt is activated above other
  windows and appears in the taskbar so a browser cannot hide it behind Reader;
- a configurable automatic-prompt minimum (50 trimmed characters by default,
  with 0 disabling the threshold), plus Ignore for 5 minutes, a visible expiry,
  and Resume now; explicit clipboard-reading actions bypass these filters;
- opt-in Copy Selection and Read with a one-second timeout, secure-desktop
  refusal, one-shot `Ctrl+C`, loop prevention, and best-effort safe clipboard
  restoration;
- one-operation clipboard append that preserves paragraph boundaries, with
  durable Undo/Redo and an actionable playback-lock refusal;
- configurable nonfatal global hotkeys, a tray menu with clean Exit, and an
  optional always-on-top compact controller;
- privacy mode enabled by default, with monitoring state kept visible and raw
  clipboard text excluded from logs, tray text, compact controls, and taskbar;
- English and Danish resource files.
- offline TXT, Markdown, HTML/HTM, DOCX, and EPUB import with a bounded preview,
  cancellation, duplicate detection, durable warnings, and optional managed
  source-file copies;
- Markdown fences labeled `text`, `txt`, `plain`, `plaintext`, or `prose` are
  read literally, while programming-language code fences remain skipped in the
  current article-style playback; legacy bracketed system notifications are
  recognized so existing imports retain their spoken content;
- non-fetching HTML import, archive/XML safety limits, and active-content
  removal before anything reaches the Reader library;
- structure-aware read-only rendering with 64-block pages, recycling WPF
  virtualization, optional follow-reading scroll, ahead-of-playback page
  prefetch with retained reading context, and duplicate-as-editable plain text.
- a refreshed high-contrast WPF shell with a focused two-card library/reader
  layout, a dedicated bottom playback bar, restrained article tools, and
  code-native vector icons; the ImageGen reference mockup is design-only and is
  not loaded by the application at runtime.
- a multi-resolution navy/teal Reader application icon, embedded in the Windows
  executable and used by the main window, taskbar, clipboard prompt, shortcuts,
  and portable package; its transparent source PNG remains beside the `.ico`.
- engine-independent speech-rule sets with deterministic scope, stage, priority,
  enable/disable, language/engine/voice/document filters, and durable versions;
- literal and regex replacement, skip, spell, pause, and preserved phoneme rules
  compiled before the existing language normalizer while retaining source spans;
- a protected 4,096-character rule preview with spoken result, ordered trace,
  per-character UTF-16 mapping, typed timeout warnings, and no text logging;
- hard regex and total-window budgets, bounded expansion, and a direct disable
  action for a warned preview rule;
- WPF rule-set/rule management, Create rule from selection, and dry-run-first
  JSON import plus JSON export using the documented open Reader interchange.
- title and content search with a transparent SQLite FTS5/portable fallback;
- inbox, reading, finished, and archive filters with reversible state actions,
  plus confirmed recoverable article deletion that also removes queue entries
  without deleting an external source file;
- a durable, reorderable reading queue with single-item activation and optional
  auto-advance;
- bookmark creation, listing, deletion, and position jumps for the open document;
- persistent single-document and queue WAV/MP3 exports with format discovery,
  progress, cancellation, safe output names, and service-owned completion after
  the desktop closes; MP3 uses a separately installed, validated FFmpeg command;
- Reader diagnostics for database integrity, search capability, document states,
  stream leases, queue size, export states, and low-sensitivity metrics.
- bounded JSONL playback diagnostics containing chunk arrival gaps, submission
  time, PCM duration, WASAPI buffer duration, and suspected underrun counts at
  `%LOCALAPPDATA%\TTSPlatform\Reader\logs\playback-performance.jsonl`; no
  document title, text, token, or imported-file path is recorded.
- persistent browser-open handoffs polled from the protected local service; a
  saved web document opens only after unsaved edits and active playback are clear.
- current-article Find with literal, phrase, whole-word, case-sensitive, and
  bounded regex modes, keyboard next/previous navigation, and layout-stable
  active-result overlays across complete articles;
- one service-owned global Word Highlighter list with literal words/phrases,
  active toggles, stable colors, full-article counts, next-match navigation, and
  longer-phrase priority. Its background-only ranges do not edit source text or
  change font metrics, and playback remains visually dominant.

## Project boundaries

- `TtsPlatform.Reader.Client` is cross-platform and owns DTOs, strict base-URL
  validation, typed failures, bearer attachment, and Reader HTTP calls.
- `TtsPlatform.Reader.Application` is cross-platform and owns onboarding,
  paging, conflict-safe editor behavior, and the playback state machine.
- `TtsPlatform.Reader.Windows` owns `%LOCALAPPDATA%` settings, file-token reads,
  fixed Windows service actions, and NAudio output behind `IAudioOutput`.
- `TtsPlatform.Reader.App` is the WPF composition and presentation layer.
- `tests` contains xUnit coverage; `tools/TtsPlatform.Reader.Client.Smoke`
  proves paging against a live temporary local service.

The desktop must not own SQL, document parsers, speech-rule semantics, or TTS
backend inference.

The service emits one low-sensitivity `reader_stream_performance` summary per
Reader stream window when observability is enabled. It reports first-audio and
generation timing, audio duration, real-time factor, maximum backend chunk gap,
and slow-chunk count without logging source text or document titles.

## Build and check on Windows

With a .NET 10 SDK on `PATH`:

```powershell
dotnet restore apps\desktop_reader\TtsPlatform.Reader.sln
dotnet build apps\desktop_reader\TtsPlatform.Reader.sln -c Release --no-restore
dotnet test apps\desktop_reader\TtsPlatform.Reader.sln -c Release --no-build
py -3 scripts\check_desktop_reader.py --require-windows-integration
```

The check starts an isolated Python service, verifies paging, UTF-16 edits,
source-mapped Reader streaming, position resume, immediate speech without
document persistence, repeated clipboard append plus one-step Undo, a consistent
preview snapshot, live safe structured import with durable warnings and an
editable copy, source-mapped speech-rule preview plus the regex timeout guard,
the Milestone 8 desktop queue/bookmark/export wiring and Milestone 9 protected
browser-open handoff wiring, the default Windows audio endpoint,
clipboard-listener and
hotkey registration, tray lifecycle, a self-contained `win-x64` package, and a
packaged WPF render. It does not read or write the current clipboard and does not
use or alter the installed Reader library.

The application-level Notepad/browser/Word/no-selection verification is kept in
[`docs/reader_milestone5_manual_checklist.md`](../../docs/reader_milestone5_manual_checklist.md).

When a real local voice is installed in the project `.venv`, the short audible
end-to-end check is:

```powershell
.\.venv\Scripts\python.exe scripts\check_reader_real_voice_playback.py
```

For a per-user SDK installed outside `PATH`, set `TTS_PLATFORM_DOTNET` to the
`.NET 10` executable or pass `--dotnet` to the check. The current development
machine uses `%LOCALAPPDATA%\TTSPlatform\dotnet\dotnet.exe`.

## WSL behavior

Client and application projects and tests are cross-platform. WPF projects use
`EnableWindowsTargeting=true`, so an SDK with the Windows reference pack can
compile them from WSL. `check_desktop_reader.py` reports the WPF render check as
skipped outside Windows; a real Windows render pass is required for milestone
completion.

## Development package and license gate

Until the repository license is selected, only a clearly marked local
development archive can be built:

```powershell
py -3 scripts\package_desktop_reader.py --development-only
```

Without `--development-only`, packaging fails when `LICENSE` is absent. Do not
publish a desktop binary outside development testing until the public project
license has been chosen and recorded.
