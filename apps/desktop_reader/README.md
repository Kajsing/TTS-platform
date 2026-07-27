# TTS Platform Reader Desktop

This directory contains the Windows-native Reader Workstation client. It uses
C#, XAML, WPF, and .NET 10 while retaining the Python service as the only owner
of synthesis and the canonical Reader database.

## Current feature boundary

The Milestone 7 Reader MVP provides:

- strict `http://localhost` or `http://127.0.0.1` service validation;
- a token-file source (the bearer token is never copied into settings JSON);
- actionable service, token, Reader, and voice readiness states;
- paged library browsing and title search;
- direct block editing for plain-text, clipboard, selection, and text-file
  documents, including durable Undo and Redo through integer row versions;
- read-only display for structured source types;
- protected Reader WebSocket playback with strict mark/binary validation;
- NAudio 2.3 shared-mode WASAPI PCM output with two-second backpressure and a
  hard ten-second memory limit;
- Play/Pause/Stop, bounded section navigation, a 64-block reading viewport,
  source-span highlighting, and durable resume from the last fully played
  UTF-16 cursor;
- active-stream content leases, next-window continuation, and a consistent
  SQLite preview-snapshot command;
- explicit Read Clipboard without monitoring or document persistence;
- clipboard prompt mode, off by default, with Read, append, create, Inbox,
  ignore, and executable-block actions;
- opt-in Copy Selection and Read with a one-second timeout, secure-desktop
  refusal, one-shot `Ctrl+C`, loop prevention, and best-effort safe clipboard
  restoration;
- one-operation paragraph append with durable Undo/Redo and an actionable
  playback-lock refusal;
- configurable nonfatal global hotkeys, a tray menu with clean Exit, and an
  optional always-on-top compact controller;
- privacy mode enabled by default, with monitoring state kept visible and raw
  clipboard text excluded from logs, tray text, compact controls, and taskbar;
- English and Danish resource files.
- offline TXT, Markdown, HTML/HTM, DOCX, and EPUB import with a bounded preview,
  cancellation, duplicate detection, durable warnings, and optional managed
  source-file copies;
- non-fetching HTML import, archive/XML safety limits, and active-content
  removal before anything reaches the Reader library;
- structure-aware read-only rendering with 64-block pages, recycling WPF
  virtualization, optional follow-reading scroll, and duplicate-as-editable
  plain text.
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
the default Windows audio endpoint, clipboard-listener and
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
