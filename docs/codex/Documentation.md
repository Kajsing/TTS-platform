# Documentation

This file is the live status log and shared memory for future Codex loops.

## Current Status

- Date: 2026-07-27
- Workflow status: `docs/codex/` is the Codex source of truth for project spec, execution order, operating rules, and resume context. After a successful run, Codex should commit and push the completed slice by default.
- Project status: Phases 1 through 7 and the v1 local reader are complete at the
  repository behavior and test-contract level. The active post-v1 product track
  is now the Reader Workstation defined in
  `design_doc/reader_workstation_design_v1.md`.
- Runtime context: the intended end platform is Windows. Codex sessions may run from Windows PowerShell or WSL, so commands and docs should avoid assuming only one shell.
- Current loop target: Reader Workstation Milestone 7, engine-independent
  speech rules, deterministic compilation and preview, safe rule interchange,
  and playback integration.
- Current loop result: Milestone 6 is complete and validated. The user explicitly authorized autonomous
  milestone-by-milestone work through Reader Milestone 9, with a decision check
  before continuing whenever product direction, architecture, security,
  licensing, or a material UX choice would change.
- Reader Workstation resume point: execute and validate Milestone 7, then repeat
  the decision check before Milestone 8.
- Reader Milestone 6 implementation details:
  - `packages/document_import` now parses TXT, Markdown, HTML/HTM, DOCX, and
    EPUB into ordered Reader sections and blocks using the Python standard
    library. HTML never fetches remote resources and removes scripts, styles,
    navigation, forms, hidden content, and other non-reading/active elements;
  - ZIP/XML imports enforce file, expanded-byte, member, character, block, and
    timeout quotas. Traversal and absolute paths, backslashes, links,
    encryption, duplicate members, DTD/entities, and excessive expansion are
    rejected with typed failures;
  - protected multipart preview/direct-import/commit/cancel endpoints expose
    bounded previews, typed duplicate handling, optional managed source copies,
    durable structured warnings, and privacy-safe operation metrics;
  - the .NET client and WPF app support file selection and drag/drop, automatic
    cancellable preview, title/language/source-copy choices, duplicate consent,
    import warnings, and duplicate-as-editable plain text;
  - structured documents render read-only through recycling WPF virtualization
    and explicit 64-block pages. Heading/list/quote/code styles survive import,
    playback can optionally follow the active source span, and users can turn
    follow scrolling off;
  - `python-multipart` 0.0.32 is the only new direct runtime dependency. Its
    Apache-2.0 license is recorded in `THIRD_PARTY_NOTICES.md`; DOCX, EPUB,
    Markdown, and HTML parsing add no third-party parser dependencies;
  - the Windows source launchers and bundle now include `document_import`.
    The existing unresolved repository-license choice still prevents claiming
    external-distribution readiness but does not block Milestones 7 through 9.
- Reader Milestone 6 validation passed on 2026-07-27:
  - `py -3 -m pytest packages\document_import\tests packages\reader_core\tests apps\tts_service\tests -q`: 329 passed;
  - `py -3 -m pytest -q`: 361 passed;
  - `.NET Release` build: 0 warnings, 0 errors; solution tests: 54 passed;
  - `py -3 -m ruff check .`, `dotnet format ... --verify-no-changes`,
    `git diff --check`, and `py -3 scripts\check_reader_contracts.py` passed;
  - `py -3 scripts\check_desktop_reader.py --require-windows-integration --skip-build`
    passed live paging/edit/stream/resume, clipboard regressions, safe live HTML
    import and editable copy, WASAPI, privacy-safe Windows integration,
    self-contained packaging, and packaged WPF rendering;
  - `py -3 scripts\check_windows_bundle_bootstrap.py` passed with the importer
    package present and the isolated service setup healthy;
  - the required post-archive security review found zero open Milestone 6
    findings. Representative/adversarial fixtures cover all supported formats,
    archive attacks, active HTML, durable warnings, cancellation/limits, and a
    20,000-block book-scale document.
- Reader Milestone 5 implementation details:
  - `AddClipboardFormatListener` is registered only while prompt monitoring is
    enabled. Clipboard text is never read while monitoring is Off; the explicit
    Read Clipboard command and hotkey do not depend on monitoring;
  - immediate clipboard speech uses authenticated synchronous `/v1/tts` in
    bounded 800-character requests, a separately cancellable two-minute local
    synthesis client, in-memory WAV decode, and WASAPI output. It creates no
    Reader document and clears replay text on completion or Stop;
  - Copy Selection and Read sends `Ctrl+C` once, waits at most one second for a
    sequence change, refuses the secure desktop and blocked executables, never
    retries, suppresses its own clipboard notifications, and restores prior
    string/byte/stream formats only when they fit safe bounded serialization;
  - the prompt offers Read now, Append to open document, Create new document,
    Save to Inbox, Ignore, and Always ignore this app. Privacy mode hides the
    preview, and prompt state retains no text after the action completes;
  - append calls the existing revisioned Reader append endpoint once. Each copy
    is a separate paragraph/edit, one Undo removes exactly the newest selection,
    and `reader_document_locked` becomes an actionable pause-or-stop message;
  - tray, main-window, compact-controller, local keyboard, and configurable
    global hotkey controls share Play/Pause/Stop. Hotkey conflicts are reported
    without disabling other controls; tray Exit performs async playback stop and
    resource shutdown while leaving the local service running;
  - the compact controller is optional, always-on-top by default, remembers its
    position when enabled, and uses a neutral private-text label rather than raw
    clipboard content. The main header and tray menu visibly expose monitoring;
  - a Milestone 4 pause race was fixed while testing this slice: cancellation is
    now signaled before releasing audio output, and a cancelled frame cannot
    advance the durable last-heard cursor;
  - `docs/reader_milestone5_manual_checklist.md` covers Notepad, Chrome/Edge,
    Word when installed, unsupported/no-selection behavior, repeated append,
    privacy, hotkeys, tray, and shutdown.
- Reader Milestone 5 validation passed on 2026-07-27:
  - a real local launch used `.venv\Scripts\python.exe scripts\dev_run.py`, the
    configured token file, and the per-user .NET 10 runtime. Service health was
    `ok`, the real voice backend and Reader database were ready, authenticated
    capabilities/document requests succeeded, and the WPF window remained open;
  - that launch exposed and fixed a WPF startup crash: `LibraryPager` now retains
    the caller synchronization context before mutating its UI-bound
    `ObservableCollection`, with a regression test that forces asynchronous page
    completion and verifies collection notifications remain on the calling
    thread;
  - `py -3 scripts\check_desktop_reader.py --require-windows-integration`:
    live paging/edit/stream/resume, immediate speech without document creation,
    three separate clipboard appends plus one exact Undo, preview snapshot,
    real Windows audio, listener stop/restart, nonfatal hotkey failure, tray
    lifecycle, self-contained package, and packaged WPF render passed;
  - `dotnet test apps\desktop_reader\TtsPlatform.Reader.sln -c Release`: 52
    passed across Client, Application, and Windows test projects;
  - the pause timing regression passed ten consecutive focused runs;
  - `py -3 -m pytest -q`: 339 passed;
  - `py -3 scripts\check_reader_contracts.py`: six version-1 fixtures passed;
  - `py -3 -m ruff check .`, `dotnet format --verify-no-changes`, and
    `git diff --check`: passed.
- Reader Milestone 5 assumptions and deviations:
  - no cloud, paid, backend-specific, or new third-party runtime dependency was
    introduced. Windows Forms is used only from the .NET Windows desktop
    framework for clipboard/tray integration;
  - unattended integration smoke intentionally registers infrastructure but
    never reads or writes the installed clipboard. A visible application-matrix
    attempt was aborted when another running application took foreground focus;
    no Notepad/browser/Word result is claimed. The documented matrix remains a
    human pre-alpha check on an idle desktop;
  - the existing uncommitted `models/MANIFEST.json` installation-state change
    remains user-owned and excluded from this milestone.
- Reader Milestone 4 implementation details:
  - `WS /v1/reader/stream` requires the existing loopback, origin, rate-limit,
    and bearer protections; desktop tokens are sent only in the Authorization
    header and never in a WebSocket URL;
  - stream protocol version 1 emits one JSON mark before each binary PCM frame,
    with byte count, stream/document identity, monotonic stable cursor, UTF-16
    source spans, and section identity. The .NET parser rejects missing/doubled
    marks, byte mismatches, format/identity changes, and cursor regression;
  - source-mapped normalization retains original spans across newline,
    whitespace, symbol, abbreviation, segmentation, and planner-inserted
    whitespace transformations. Long documents use keyset block reads bounded
    to 64 blocks and 32,000 source characters per server window;
  - active Reader streams hold a ref-counted document lease. Content replace,
    append, Undo, and Redo return `reader_document_locked` until every stream
    cancels/releases; raw `/v1/tts` and Chrome streaming are unchanged;
  - Reader positions and bookmarks now convert UTF-16 offsets explicitly at
    every HTTP boundary, including surrogate-pair rejection;
  - the cross-platform application state machine maintains one active stream,
    applies two-second audio backpressure, drains a fragment before advancing
    its durable cursor, throttles playing saves to at most once per second, and
    flushes immediately on pause, stop, completion, and shutdown;
  - NAudio 2.3.0 is isolated behind `IAudioOutput` in the Windows project. It
    uses shared-mode WASAPI, mono PCM16 validation, a two-second target, and a
    hard ten-second buffer. Its MIT terms are recorded in
    `THIRD_PARTY_NOTICES.md` and included in desktop output/publish artifacts;
  - WPF renders a bounded 64-block reading viewport and marks current source
    text with background, bold, and underline cues. Editing is disabled during
    active playback and restored after pause/stop; Space and Escape provide
    local keyboard playback control;
  - `scripts/create_reader_preview_snapshot.py` builds seeded or explicit-source
    snapshots only through SQLite's backup primitive; the desktop check validates
    snapshot integrity without touching the installed Reader library;
  - deterministic fake protocol/audio tests cover pause-at-last-fully-heard,
    idempotent stop, next-window continuation, one-at-a-time audio consumption,
    stream leases, UTF-16 spans, and error handling.
- Reader Milestone 4 validation passed on 2026-07-27:
  - `py -3 scripts/check_desktop_reader.py --require-dotnet
    --require-windows-audio`: live paging/edit, 31 paired PCM frames, source
    spans, position resume, preview snapshot, default WASAPI endpoint,
    self-contained package, third-party notice, and packaged WPF render passed;
  - `.\.venv\Scripts\python.exe scripts\check_reader_real_voice_playback.py`:
    audible Piper `vits-piper-en_US-lessac-high` playback completed through the
    Reader WebSocket, application state machine, and NAudio shared-mode WASAPI;
    92 highlight events advanced to UTF-16 character offset 58;
  - focused Python streaming/API/text tests: 35 passed after final typed-error
    regression coverage; `py -3 -m pytest -q`: 339 passed;
  - `dotnet test apps\desktop_reader\TtsPlatform.Reader.sln -c Release`: 35
    passed across Client, Application, and Windows test projects;
  - `py -3 scripts\check_reader_contracts.py`: six version-1 fixtures passed
    with Reader stream protocol capability 1;
  - `py -3 -m ruff check .`, `dotnet format --verify-no-changes`, and
    `git diff --check`: passed.
- Reader Milestone 4 assumptions and deviations:
  - the approved NAudio 2.x choice resolved to stable version 2.3.0; no cloud,
    paid, or non-Windows runtime dependency was introduced;
  - the WPF viewport is deliberately bounded rather than full-book materialized.
    Full import-aware virtualization remains Milestone 6;
  - `packages/speech_rules/tests` does not exist before Milestone 7, so the
    equivalent current Reader/core/service suites are run without inventing an
    empty directory;
  - the existing uncommitted `models/MANIFEST.json` installation-state change
    remains user-owned and excluded from this milestone.
- Reader Milestone 3 implementation details:
  - `apps/desktop_reader/TtsPlatform.Reader.sln` separates cross-platform Client
    and Application projects from Windows infrastructure and WPF composition;
  - the Client accepts only HTTP with the exact `localhost` or `127.0.0.1` host
    and rejects credentials, non-root paths, queries, and fragments;
  - settings live at `%LOCALAPPDATA%\TTSPlatform\Reader\settings.json` and store
    only a token-file path. Atomic settings writes, file-token reads, and fixed
    per-user scheduled-service startup are isolated in the Windows project;
  - onboarding distinguishes unavailable service, missing or rejected token,
    disabled/degraded Reader storage, unsupported contract, and degraded voice
    backend states without exposing tokens or raw service details;
  - the library uses opaque keyset cursors and preserves loaded state on failed
    requests. Plain-text, clipboard, selection, and text-file blocks are
    editable; structured sources remain read-only;
  - edit requests send integer document row versions and UTF-16 code-unit
    offsets. A revision conflict keeps the WPF edit buffer intact and requires
    an explicit reload; server Undo/Redo is disabled while local edits are
    unsaved;
  - the Python HTTP boundary now explicitly converts UTF-16 edit offsets to
    internal Python indices and converts mutation metadata back. Tests cover
    Danish text, combining marks, emoji, surrogate boundaries, and invalid
    offsets;
  - English and Danish resource files, keyboard-accessible controls, automation
    names, virtualized library rows, and an `asInvoker` manifest establish the
    initial accessibility and no-admin shell baseline;
  - the desktop check starts an isolated live Python service, proves two-page
    .NET client paging and a UTF-16 edit, publishes a self-contained `win-x64`
    development archive, verifies it contains no token/settings files, and
    launches the packaged WPF executable through a render marker;
  - external desktop packaging fails while `LICENSE` is absent unless the
    explicit `--development-only` switch is used. Development packages contain
    a warning and are deleted after the smoke check.
- Reader Milestone 3 validation passed on 2026-07-27:
  - .NET 10.0.202 restore and Release build passed with zero warnings;
  - `dotnet test apps\desktop_reader\TtsPlatform.Reader.sln -c Release
    --no-build`: 25 passed across Client, Application, and Windows projects;
  - `py -3 scripts\check_desktop_reader.py --require-dotnet`: live paging,
    live UTF-16 edit, self-contained portable package, and Windows WPF render
    passed; the package correctly reported `external_distribution_ready=false`;
  - `py -3 -m pytest -q`: 326 passed;
  - `py -3 scripts\check_reader_contracts.py`: six fixtures ready;
  - `py -3 -m ruff check .`, `dotnet format --verify-no-changes`, and
    `git diff --check`: passed.
- Reader Milestone 3 assumptions and deviations:
  - .NET 10.0.202 was installed per-user under
    `%LOCALAPPDATA%\TTSPlatform\dotnet` because the machine-wide SDK is .NET 8;
    no administrator access or PATH change was needed;
  - the broader source-map compiler remains Milestone 4, but UTF-16 conversion
    for the already-public edit route moved forward because WPF editing would
    otherwise split surrogate pairs at the API boundary;
  - xUnit, its Visual Studio runner, and Microsoft.NET.Test.Sdk are test-only
    dependencies. The desktop runtime added no third-party audio or capture
    dependency in this milestone;
  - the existing uncommitted `models/MANIFEST.json` change remains user-owned
    and excluded from this milestone.
- Previous loop result: Reader Milestone 2 complete. The service initializes Reader storage in
  an isolated runtime state, exposes authenticated `/v1/reader/*` routes for
  capabilities, documents, revisioned content changes, blocks, positions,
  bookmarks, and queue operations, and reports sanitized Reader readiness from
  public health without changing backend readiness. No WPF, import parser,
  speech-rule, export, or Reader-stream implementation was added.
- Locked Reader Workstation architecture: preserve the existing Python TTS
  service as the single synthesis authority; use a thin WPF/.NET 10 Windows
  client; keep canonical reader persistence in service-owned SQLite through a
  new `reader_core` domain; add protected `/v1/reader/*` contracts rather than
  changing existing TTS endpoints; and preserve structured source mapping before
  reuse of the existing `tts_core` synthesis pipeline.
- Reader Milestone 2 implementation details:
  - every `/v1/reader/*` read and write passes through the existing bearer,
    origin, and rate-limit middleware; public health remains unauthenticated;
  - Reader startup failure is sanitized and disables Reader operations only;
    it does not falsify or disable existing backend, voice, or TTS readiness;
  - the additive version-1 API covers document create/get/list/search/update,
    soft-delete/restore, block keyset paging, edit/append/Undo/Redo, idempotent
    positions, bookmark CRUD, and transactional queue operations;
  - content mutation responses intentionally omit original and replacement text;
    structured Reader logs contain operation names, entity IDs, and sizes but
    never document titles, document text, clipboard text, SQL, tokens, or paths;
  - duplicate plain-text content is rejected by source hash unless the caller
    explicitly sets `allow_duplicate`;
  - typed failures include disabled/unavailable/busy storage, missing documents
    and blocks, invalid/stale cursors, duplicates, state conflicts, and integer
    row-version conflicts;
  - capabilities truthfully advertise schema version 1 and the current text
    library. Imports, Reader streaming, rules, search, and exports remain marked
    unavailable until their planned milestones;
  - six JSON fixtures in `contracts/reader/` round-trip through Python schemas;
  - source launchers, smoke checks, Windows bundle source paths, and packaging
    now include `packages/reader_core/src`. Temporary smoke repositories set an
    explicit temporary Reader home instead of touching installed user data.
- Reader Milestone 2 validation passed on 2026-07-27:
  - `py -3 -m pytest apps\tts_service\tests packages\reader_core\tests -q`:
    287 passed.
  - `py -3 scripts\check_reader_contracts.py`: six fixtures ready.
  - `py -3 -m pytest -q`: 318 passed.
  - `py -3 -m ruff check .`: passed.
  - `git diff --check`: passed; line-ending notices are informational.
- Reader Milestone 2 assumptions and deviations:
  - the capabilities route returns zero/empty values for not-yet-implemented
    subsystems instead of promising the future example response early;
  - file upload/import remains Milestone 6 even though the complete design lists
    its eventual route alongside the broader API surface;
  - existing test and smoke launchers gained the new source root as a necessary
    packaging/runtime support change; no dependency or security model changed.
- Reader Milestone 1 implementation details:
  - migration `001_reader_library.sql` creates the seven Reader tables and
    indexes plus version/checksum tracking in `schema_migrations`;
  - every repository connection enables foreign keys, WAL, normal synchronous
    mode, and a 5-second busy timeout; writes use short immediate transactions;
  - document content mutations compare integer `row_version`, increment both
    row and content revisions, and update blocks plus edit history atomically;
  - one clipboard append creates one paragraph block and one undo entry;
  - edit history is bounded by configurable operation and UTF-8 byte limits and
    can be explicitly cleared; this is ordinary deletion, not a secure-erasure
    guarantee;
  - persisted positions and bookmarks remap inside the content transaction;
    external old cursors remap over intact monotonic edit history or return the
    typed `ReaderStaleCursorError` after a branch or trimmed history;
  - list operations use `(updated_at, id)` keyset cursors and indexed queries;
    the 10,000-document test does not use SQL `OFFSET`;
  - resolving Reader paths has no filesystem side effect. Explicit repository
    initialization creates the database parent and runs migrations, while
    disabled initialization returns without touching storage;
  - the SQLite backup API writes a temporary consistent snapshot and atomically
    installs it at the requested destination. User-facing restore remains a
    later milestone.
- Reader Milestone 1 validation passed on 2026-07-27:
  - `py -3 -m pytest packages\reader_core\tests -q`: 36 passed.
  - focused Reader/config/disabled-mode tests: 55 passed.
  - `py -3 -m pytest -q`: 305 passed.
  - `py -3 -m ruff check .`: passed.
  - `py -3 scripts\check_v1_completion.py --require-complete`: passed with
    all nine protected v1 criteria ready.
  - `git diff --check`: passed; line-ending notices are informational.
- Reader Milestone 1 assumptions and deviations:
  - editable source types at this layer are plain text, clipboard, selection,
    and text files; structured-format snapshot editing remains with import work;
  - operation and byte limits were added to `[reader]` because the approved
    persistent Undo/Redo design requires bounded retention;
  - no product, architecture, security, licensing, deployment, or dependency
    direction changed. Only Python standard-library modules were added.
- Reader product clarifications approved on 2026-07-27:
  - plain-text, clipboard, and selection documents are directly editable;
  - active playback locks content, while edit operations provide persistent
    Undo/Redo and revision-aware cursor remapping;
  - installed Reader data defaults to
    `%LOCALAPPDATA%\TTSPlatform\Reader`;
  - future multi-computer sharing is API-based and remains out of current scope;
  - TextAloud dictionary migration is removed rather than preserved;
  - repeated explicit `Ctrl+C` append into an open document is a primary daily
    workflow;
  - OCR is not required for 1.0;
  - dependencies and packaging must preserve the option of a public release.
- Reader plan-refinement validation passed on 2026-07-27:
  - `py -3 -m pytest -q`: 261 passed.
  - `py -3 -m ruff check .`: passed.
  - `py -3 scripts\check_v1_completion.py --require-complete`: passed with all
    nine v1 criteria ready.
  - `git diff --check`: passed; line-ending notices are informational.
  - design consistency checks found all required revised contracts and none of
    the superseded TextAloud/OCR/ordinal/timestamp contracts.
- No plan deviation remains. The specific public project license is deliberately
  deferred, but must be chosen before publishing a desktop binary; it does not
  block Reader Milestone 1.
- Reader Milestone 0 validation passed on 2026-07-27:
  - `py -3 -m pytest -q`: 261 passed.
  - `py -3 -m ruff check .`: passed.
  - `py -3 scripts\check_v1_completion.py --require-complete`: passed with all
    nine v1 criteria ready and `can_mark_v1_complete: true`.
  - `git diff --check`: passed; line-ending conversion notices are informational.
- The pre-existing local `models/MANIFEST.json` change records installed voice
  state and is intentionally excluded from the Reader Milestone 0 commit.
- Post-v1 exploration: the user asked whether TextAloud can use this platform
  through a Windows SAPI 5 voice. The agreed direction is an optional
  `apps/sapi_bridge/` Windows integration that registers a SAPI voice and
  bridges SAPI `Speak` calls to the existing localhost service. The durable
  plan is recorded in `docs/sapi_bridge.md`.
- Codex workflow files now explicitly treat SAPI/TextAloud as a post-v1
  optional integration track: `AGENTS.md`, `docs/codex/Prompt.md`,
  `docs/codex/Plan.md`, and `docs/codex/Implement.md` all point future loops
  at `docs/sapi_bridge.md` without reopening v1 completion scope.
- Current SAPI spike result: no Visual Studio C++ toolchain was found on PATH
  (`cl`, `msbuild`, and `vswhere` unavailable), `SAPI.SpVoice` did not
  enumerate temporary per-user `HKCU` voice tokens, and writing machine-level
  `HKLM` SAPI tokens requires elevated PowerShell. The first committed spike
  therefore uses reversible install/remove/check scripts for a dummy
  machine-scope SAPI voice alias instead of a native COM engine DLL.
- Manual TextAloud verification on 2026-06-15 passed: after running the
  elevated install script, TextAloud 3.0.117 displayed a `TTS Platform`
  provider with `TTS Platform Dummy Voice`, and playback produced Microsoft
  Zira audio as expected for the dummy alias token. This proves machine-scope
  custom SAPI voice tokens are visible to TextAloud on this machine.
- Current native SAPI progress: `apps/sapi_bridge/` now includes an ATL-free
  C++ COM DLL skeleton with `ISpTTSEngine`, `ISpObjectWithToken`, class
  factory exports, a `.vcxproj`, and dummy PCM tone output via
  `ISpTTSEngineSite::Write`. `scripts/check_sapi_toolchain.py` reports that
  this machine now has the native build prerequisites: `cl`, `msbuild`,
  `sapi.h`, and `sapiddk.h`. The toolchain check also reports Visual Studio
  installs, `vswhere`, Windows SDK include roots, `winget` availability, and
  the expected Visual Studio Build Tools 2022 install command. The native
  skeleton is ATL-free and deliberately avoids `sphelper.h`.
- `scripts/check_model_management_flow.py` now seeds its temporary manifest
  from a deterministic test fixture instead of copying the local working-tree
  `models/MANIFEST.json`, so local installed voices do not break full pytest
  validation.
- Native build/registration scripts are staged for the next toolchain pass:
  `scripts/windows/build_sapi_bridge.ps1`,
  `scripts/windows/install_sapi_native_voice.ps1`,
  `scripts/windows/check_sapi_native_voice.ps1`, and
  `scripts/windows/remove_sapi_native_voice.ps1`. After Visual Studio Build
  Tools 2022 was installed, `scripts/windows/build_sapi_bridge.ps1 -Platform
  Both -Configuration Release -RequireBuildTools` built both Win32 and x64
  Release DLLs. Manual elevated X86 native registration then succeeded:
  `check_sapi_native_voice.ps1 -Architecture X86` reports the token, CLSID,
  `InprocServer32`, and Win32 DLL path present. TextAloud 3.0.117 displayed
  `TTS Platform Native Dummy Voice` and playback produced the expected single
  dummy tone. X64 native registration is not installed. The next slice can
  manually verify the newly implemented localhost `/v1/tts` integration for
  the X86 engine path.
- Current SAPI localhost bridge progress: `TtsPlatformSapiEngine::Speak`
  collects SAPI text fragments, reads `config/token.txt`, posts JSON to
  `http://127.0.0.1:7777/v1/tts` with bearer auth through WinHTTP, decodes
  PCM16 WAV responses, and writes matching PCM to `ISpTTSEngineSite::Write`.
  It falls back to the native dummy tone on service/auth/format failures and
  writes non-sensitive diagnostics to `logs/sapi-bridge.log`. The code builds
  to a temp Win32 Release output and the normal x64 Release output; the
  registered Win32 DLL path must be rebuilt after closing TextAloud because
  TextAloud holds the loaded COM DLL. Manual verification now confirmed that
  TextAloud playback through `TTS Platform Native Dummy Voice` can reach
  `/v1/tts` and produce service voice output. The service reported HTTP 200,
  `default_voice = vits-piper-en_US-lessac-high`, `backend_ready = true`, and
  `default_voice_loaded = true`. Subjective quality is still not good enough;
  the next slice should compare direct service WAV output with TextAloud
  playback and then tune model/prosody/chunking/output settings.
- TextAloud reader playback later produced only the dummy tone while direct
  `/v1/tts` WAV quality was much better. `logs/sapi-bridge.log` showed HTTP
  400 responses from `/v1/tts`, consistent with the reader path sending text
  beyond the synchronous request limit. The native bridge now splits long SAPI
  text into bounded `/v1/tts` requests, writes each completed PCM chunk back to
  SAPI immediately, checks for SAPI abort requests between chunks, and inserts
  short silence between chunks.
- Validation status for the current loop:
  - `py -3 scripts\check_sapi_bridge.py` passed and reported the dummy token
    contract, x64/x86 registry views, elevated install requirement, native
    skeleton presence, dummy PCM fallback, and localhost integration wiring
    present but not yet manually verified in TextAloud.
  - `py -3 scripts\check_sapi_toolchain.py` passed in non-strict mode and
    reported the native skeleton project exists and the MSVC/SAPI build
    toolchain is now complete on this machine.
  - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\build_sapi_bridge.ps1`
    passed with `ok: true`, `built: true`, and Win32/x64 Release DLL outputs
    after Visual Studio Build Tools 2022 was installed.
  - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\check_sapi_native_voice.ps1`
    passed for X86 with `ok: true` after manual elevated install, and reported
    X64 not installed.
  - Manual TextAloud localhost verification passed: service log showed
    authenticated `POST /v1/tts` HTTP 200 from the SAPI path, and TextAloud
    produced service voice output rather than the fallback dummy tone.
  - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\check_sapi_voice.ps1`
    passed without requiring elevation and reported the dummy token absent,
    with Microsoft David/Zira visible through both current and WOW64 SAPI COM
    enumeration.
  - `py -3 -m pytest apps\tts_service\tests\test_sapi_bridge_check.py apps\tts_service\tests\test_sapi_toolchain_check.py -q`
    passed with 3 tests.
  - `py -3 -m ruff check .` passed.
  - `py -3 -m pytest -q` passed with 261 tests.
  - `py -3 scripts\check_v1_completion.py --require-complete` passed and
    reported 9 ready criteria, 0 pending final-security criteria, and
    `can_mark_v1_complete: true`.
  - `py -3 scripts\check_v1_readiness.py` passed with 46 checked files and
    55 readiness markers.
  - `py -3 -m pytest apps\tts_service\tests\test_v1_completion_check.py apps\tts_service\tests\test_v1_readiness_check.py apps\tts_service\tests\test_package_windows_bundle.py -q`
    passed with 5 tests.
  - `py -3 -m ruff check scripts\check_v1_completion.py scripts\check_v1_readiness.py scripts\package_windows_bundle.py apps\tts_service\tests\test_v1_completion_check.py apps\tts_service\tests\test_package_windows_bundle.py`
    passed.
  - `py -3 -m ruff check .` passed.
  - `py -3 -m pytest -q` passed with 258 tests.
  - `py -3 scripts\release_check.py --node-executable C:\Users\ckajs\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --require-js-syntax --package-out "$env:TEMP\tts-platform-prototype-release-check.zip" --windows-bundle-out "$env:TEMP\tts-platform-local-reader-release-check.zip"`
    passed. The default Chrome/MV3 smoke remained skip-aware because branded
    Chrome did not register the unpacked extension in this environment; all
    non-optional release, bundle, launcher, Task Scheduler, install,
    extension, reader-flow, model-management, completion, readiness, strict JS
    syntax, and service smoke gates passed.
  - `py -3 C:\Users\ckajs\.codex\plugins\cache\openai-curated\codex-security\c6ea566d\scripts\validate_report_format.py --report-md C:\tmp\codex-security-scans\TTS-platform\a1645b6_20260614T200121\report.md`
    passed.
  - `py -3 C:\Users\ckajs\.codex\plugins\cache\openai-curated\codex-security\c6ea566d\scripts\render_report_html.py --template C:\Users\ckajs\.codex\plugins\cache\openai-curated\codex-security\c6ea566d\assets\report_template_inlined.html --report-md C:\tmp\codex-security-scans\TTS-platform\a1645b6_20260614T200121\report.md --report-html C:\tmp\codex-security-scans\TTS-platform\a1645b6_20260614T200121\report.html --title "TTS-platform Codex Security Scan"`
    passed.
- Tooling status:
  - `python3 scripts/smoke_service.py --token-file config/token.txt` passed against a live local service.

## What Is Done

- Repo guidance, config loading, voice registry, backend abstraction, and service bootstrap exist.
- Stable localhost HTTP endpoints exist for health, voices, sync TTS, async jobs, job status, job cancellation, and job result retrieval.
- Token auth, token rotation, origin filtering, rate limiting, and localhost security baselines exist.
- WebSocket streaming exists with JSON control events and binary PCM16 frames.
- Observability, CLI tooling, benchmark modes, and audio regression tests exist.
- Chrome MV3 prototype work exists in `apps/chrome_extension/`.
- Phase 7 work already completed includes backend runtime config (`stub` / `auto` / `real`), manifest-side backend asset binding, more truthful backend readiness, health backend snapshots, fake-runtime coverage for sync/jobs/streaming, async job benchmarking, and a first chunk-planning component shared across sync/jobs/streaming.
- Early v1 model-management work now includes local catalog listing, model
  summaries with install metadata, artifact install with result metadata and
  pre-download overwrite refusal, checksum verification required by default,
  safe zip extraction against absolute paths, drive-qualified paths, and
  traversal entries, manifest update, default voice activation in
  `config/config.toml`, model removal, and safe model-id validation before
  install/remove path effects. Manifest backend asset paths are now contained
  to the installed model source before install writes, readiness checks, and
  real runtime loading.
- A new public-contract smoke script now exists:
  - `scripts/smoke_service.py` exercises `health`, `voices`, sync TTS, WebSocket streaming, and async jobs in one run.
  - `apps/tts_service/tests/test_smoke_script.py` verifies the smoke script orchestration with mocked public-contract clients.
- Milestone 1 is now complete:
  - `ChunkPlanner` can split long sentence-level segments at clause boundaries before the hard max when that produces a better early chunk.
  - oversized segments without clause punctuation now fall back to whitespace-aware hard-limit splitting.
  - split subchunks are kept explicit instead of being immediately merged back into a larger chunk.
  - tests now cover core chunk-boundary behavior plus service-level use of the shared chunk-planning entry point.
- Milestone 2 is now complete at the service layer:
  - `SynthesisService` streams through `backend.synthesize_stream()` instead of synthesizing WAV per planned chunk and slicing decoded PCM locally.
  - service streaming now remaps backend-local chunk indices into one global stream index sequence across the whole chunk plan.
  - service streaming validates sample-rate/channel consistency across streamed backend chunks.
  - regression coverage now fails if stream execution falls back to `backend.synthesize()` instead of the backend streaming contract.
- Milestone 3 is now complete at the service-contract level:
  - cancelling a queued or running job records terminal `cancelled` state immediately.
  - background job completion cannot overwrite a previously cancelled job with `completed`.
  - chunk-planned sync/job synthesis checks backend cancellation flags between planned chunks.
  - WebSocket cancellation raised from the stream generator is reported as a `cancelled` event.
  - synthesis observability now separates cancelled attempts from failures.
- Milestone 4 is now complete:
  - `docs/backend_model_setup.md` documents runtime files, backend modes,
    readiness behavior, manifest conventions, real `sherpa-onnx` backend config,
    catalog format, model-management CLI usage, long-text implications,
    cancellation limits, security notes, and troubleshooting.
  - `README.md` links to the backend/model setup guide from the CLI section.
- Milestone 5 is now complete:
  - the remaining Phase 7 streaming item is implemented through
    callback-driven real-runtime streaming when supported by `sherpa_onnx`;
  - the remaining Phase 7 real-backend cancellation item is implemented through
    generation callbacks that return `0` once cancellation is observed;
  - older runtimes and work between callback boundaries remain documented
    best-effort limits rather than hidden guarantees;
  - `TASKS.md`, `TESTING.md`, `README.md`, `docs/backend_model_setup.md`, and
    `docs/codex/Plan.md` now point future work toward v1 reader slices instead
    of stale Phase 7 execution.
- V1 reader track has started:
  - `tts.max_chars_per_stream` defaults to `48000` and is validated to stay at
    least as large as `tts.max_chars_per_request`.
  - WebSocket streaming now uses `prepare_stream_request()` with the stream
    limit, while HTTP and async jobs still use `prepare_request()`.
  - the Chrome extension page capture default is now `24000` characters, with a
    maximum of `48000`, matching the service's default stream ceiling.
  - tests cover stream acceptance above the HTTP/job limit and rejection above
    the stream limit.
  - stream events now expose `progress` metadata with planned text chunk count,
    completed text chars, and percent complete.
  - WebSocket start events now accept `start_text_chunk_index`, giving future
    extension UX a stable resume anchor.
  - the extension offscreen player stores stream progress in playback state and
    the popup displays it.
  - the popup now exposes `Resume Page`; background resume reuses the latest
    planned text chunk index and re-extracts current active-tab page text.
  - page playback now stores non-text capture metadata in session playback
    state, and the popup reports whether a long page was truncated at the
    configured character limit.
  - short article headings are now preserved in page capture even when they are
    below the normal body-block text threshold.
  - page playback now stores structure counts for headings, body blocks, list
    items, and quotes without storing heading text or raw page text.
  - the popup now exposes `Next Section`; background resolves the next heading
    offset from current reader progress, re-extracts the active tab from that
    section index, and starts page playback from there.
  - truncated page captures now include a non-textual next-section continuation
    marker when a later heading-backed section exists beyond the current
    capture limit, and `Next Section` uses it as a fallback.
  - the popup now exposes `Continue Page`; background uses the latest truncated
    page-capture `nextTextCharStart` offset and re-extracts the active tab from
    that character position, so flat long pages can continue without storing
    raw page text.
  - when a page playback segment finishes normally and the latest capture still
    has a `nextTextCharStart`, the background worker now starts the next
    segment automatically from the original source tab without storing raw page
    text.
  - the popup now displays a `Long Page` status line for truncated page
    segments, showing the current text offset, automatic continuation state,
    next continuation character, and next known section metadata when present.
  - the popup now disables unavailable resume, continue, previous/next section,
    and stop controls based on the latest non-text playback metadata.
  - the popup now exposes `Previous Section`; background resolves the previous
    heading-backed section from current reader progress and page-capture
    metadata, re-extracts the active tab from that section index, and starts
    page playback from there.
  - `scripts/check_extension_reader_flow.py` now verifies long-page reader
    wiring and streams a generated thousand-word article through the local
    service WebSocket contract.
  - the extension background now persists interrupted playback state if an
    active stream loses its offscreen document, and the reader-flow gate checks
    stop/restart recovery plus popup reopen-state fields.
  - `scripts/check_extension.py` now validates the structural resume wiring even
    when `node` is not installed.
- V1 model-management UX has started:
  - the committed default `models/catalog.json` now includes
    `vits-piper-en_US-lessac-medium`, an English Piper Lessac medium voice
    converted for sherpa-onnx and pinned to the official k2-fsa `tar.bz2`
    release artifact checksum.
  - `tts model-install` now supports zip and tar archives, including
    `tar.bz2`, while rejecting unsafe tar traversal, absolute paths, links, and
    non-file/non-directory entries before extraction.
  - `tts model-install --activate` updates the manifest and `config/config.toml`
    default voice in one command.
  - model install JSON output now reports installed file count, checksum
    verification status, warnings for missing checksums, and next steps.
  - `tts catalog-list` now reports catalog counts, model summaries, duplicate
    or incomplete-entry warnings, and install next-step guidance.
  - `tts catalog-list` and `tts model-install` now default to
    `models/catalog.json` when `--catalog` is omitted, and local missing-catalog
    failures explain how to create the default file or pass `--catalog`.
  - `tts model-install` now emits progress status lines to stderr and includes
    structured `install_steps` in its JSON stdout result.
  - `tts model-install` now requires `artifact_sha256` by default and only
    permits missing checksums through `--allow-missing-checksum` for trusted
    local artifacts.
  - remote HTTP catalogs can now use relative `artifact_url` entries; the
    installer resolves them against the catalog URL before download, matching
    local catalog-relative artifact behavior.
  - `tts model-install` now stages artifacts in a temporary file before
    checksum verification and zip extraction, improving large model install
    behavior without changing the CLI JSON contract.
  - `tts model-remove` now reports whether the removed model id is still
    configured as `[tts].default_voice`, with next-step guidance to activate
    another voice before service restart.
  - `tts model-check [model-id]` now reports read-only real-backend readiness
    diagnostics for the configured default voice or selected model id.
  - `tts model-check [model-id]` now also reports default `models/catalog.json`
    availability and uses it to omit redundant `--catalog` guidance when the
    default catalog exists.
  - `tts model-check` now inspects installable model ids in the default catalog
    and, when the configured/default voice is still the non-real development
    stub, suggests the concrete catalog model such as
    `tts model-install vits-piper-en_US-lessac-medium --activate`.
  - `tts model-list` now reports installed manifest voices, the configured
    default voice, backend-config presence, default catalog status, and
    catalog-aware next steps without starting the service.
  - `tts setup-local` and `tts model-list` now also report runtime status and
    suggest `python -m pip install sherpa-onnx` before real playback when the
    runtime package is missing.
  - `scripts/check_model_management_flow.py` now verifies catalog-list,
    default `models/catalog.json` discovery, offline `model-list`,
    relative-artifact download/install from a generated loopback HTTP catalog,
    activate, model readiness output, service smoke with the installed voice,
    and remove using a generated local artifact and temp repo root.
- Windows-friendly first-run setup has started:
  - `tts setup-local` bootstraps local config and token files without requiring
    the service to be running.
  - setup output reports the service base URL and whether the configured
    default voice is present in `models/MANIFEST.json`.
  - setup output deliberately reports only the token file path, not the bearer
    token value.
  - `tts serve` starts the local service from installed CLI tooling without
    needing `scripts/dev_run.py`.
  - `tts serve` uses config host/port/log level, supports explicit host/port
    overrides, and requires `--allow-non-local-host` before binding outside
    loopback hosts.
  - `scripts/windows/run_service.ps1` and `run_service.cmd` provide
    Windows-friendly local launchers for setup fallback plus service start.
  - `scripts/windows/run_service.ps1 -SetupOnly` now runs first-run setup and
    exits before service start; `run_service.cmd` delegates that mode to
    PowerShell.
  - `scripts/package_windows_bundle.py` builds a Windows-friendly local reader
    bundle with service/core source, Windows launchers, config example, docs,
    default model catalog, Chrome extension source, and a validated extension
    zip.
  - The generated Windows bundle README now includes explicit model-readiness
    handoff guidance: run `model-check`, install and activate a real model
    from a catalog, then re-check before expecting real acoustic output.
  - The Windows bundle intentionally excludes `config/token.txt` and installed
    model files under `models/voices/`.
  - `scripts/windows/install_local.ps1` and `install_local.cmd` now bootstrap
    an extracted bundle by creating `.venv`, installing the local package, and
    running `setup-local` without choosing a persistent service manager.
  - `scripts/windows/install_local.ps1 -InstallRealRuntime` now lets an
    extracted bundle install the optional `.[real]` runtime dependencies into
    the same `.venv` during first-run bootstrap, while the default installer
    path remains lightweight and release-friendly.
  - `scripts/windows/install_local.ps1` now installs the package's base
    dependencies by default for extracted bundles, reports
    `dependencies_installed`, and keeps `-NoDependencies` as an explicit escape
    hatch for already provisioned environments.
  - `tts service-install --user` now registers the local service as a per-user
    Windows Task Scheduler logon task after running `setup-local`.
  - `tts service-status --user`, `service-start --user`,
    `service-stop --user`, and `service-remove --user` now inspect and control
    that task through `schtasks.exe`.
  - `scripts/windows/run_scheduled_service.ps1` wraps the existing foreground
    `run_service.ps1` launcher and appends startup output to
    `logs/tts-service.log`.
  - `scripts/check_windows_service_task.py` verifies the Task Scheduler
    command shape, status parsing, scheduled wrapper, and log wiring without
    creating a real scheduled task.
  - `tts setup-local` next-step guidance now includes `tts model-check` so
    operators can verify configured/default voice readiness before expecting
    real acoustic output.
  - `tts setup-local` now reports default catalog readiness and suggests the
    concrete default English install command first when the current default
    voice is only a development stub.
  - `scripts/demo_real_voice.py` now automates an optional real English voice
    demo in ignored `dist/real-demo`: it seeds first-run files, installs and
    activates the default catalog model when needed, starts a temporary
    loopback service, runs public-contract smoke with `--token-file`, writes a
    WAV, and stops the service.
  - `scripts/demo_real_voice.py --install-real-runtime` can install `.[real]`
    into the selected Python environment before the demo setup/model checks.
  - real-runtime readiness now checks `numpy` in addition to `sherpa_onnx`,
    because the real async job and streaming callback paths can require
    `numpy` even when short sync synthesis succeeds.
  - `pyproject.toml` now exposes a `real` optional dependency extra containing
    `sherpa-onnx` and `numpy`, so local real-voice demos can install runtime
    dependencies with `python -m pip install -e ".[real]"`.
  - the extension content script now skips `aria-hidden`, `hidden`, and
    `inert` subtrees during page capture, reducing hidden UI noise during
    long-page playback while keeping extraction heuristic and metadata-only.
  - fallback plain-text page capture now uses the same filtered DOM text walk,
    so flat pages without enough reader blocks avoid hidden UI and chrome
    subtrees too.
  - readable-root selection now scores all matching article/main/content
    candidates instead of returning the first match, improving long-page capture
    on pages with multiple reader-like containers.
  - first-run/model readiness next steps now prefer
    `python -m pip install -e ".[real]"` when both `sherpa-onnx` and `numpy`
    are missing, while keeping targeted single-package guidance for partial
    installs.
  - optional Chrome/MV3 smoke can now discover the unpacked extension id from
    the temporary Chrome profile and execute from the extension popup CDP
    context, avoiding a false dependency on eager MV3 service-worker startup
    before page playback is exercised.
  - extension JavaScript syntax validation can now be made strict with
    `scripts/check_extension.py --require-js-syntax`, and Node.js can be
    supplied with `--node-executable` or `TTS_PLATFORM_NODE` when it is not on
    `PATH`.
  - `scripts/release_check.py` now accepts `--node-executable` and
    `--require-js-syntax`, propagating the Node path into package/bundle child
    checks so full release gates can require extension JavaScript syntax
    parsing.
  - `scripts/package_extension.py` and `scripts/package_windows_bundle.py` now
    accept the same `--node-executable` and `--require-js-syntax` options for
    strict standalone local package builds.
- Chrome extension onboarding has started:
  - the popup now includes a setup checklist for service reachability, saved
    token state, allow-list command/snippet readiness, voice discovery, backend
    readiness, default voice loading, and health status.
  - the popup service status now calls out backend readiness and default voice
    loading separately before showing the raw health-check JSON, so first-run
    model/runtime issues are visible without opening `/v1/health`.
  - the popup now includes a copyable allow-list command generated from the
    current Chrome extension origin, so first-run setup can copy
    `tts extension-allow-origin ...` directly.
  - `tts extension-allow-origin <chrome-extension-origin>` now updates
    `security.allowed_origins` for a copied extension origin without requiring
    manual TOML edits.
  - `scripts/check_extension.py` now validates setup-checklist wiring along
    with manifest, asset, and resume wiring.
  - `scripts/check_extension_onboarding.py` now validates the popup onboarding
    surface, config-loadable Chrome extension origin snippet, and service
    health/voice snapshot used by the popup, including explicit backend-ready
    and default-voice-loaded health checks. It also validates the
    `extension-allow-origin` CLI helper against a fresh `setup-local` repo.
  - `scripts/package_extension.py` now builds a validated local extension zip
    at `dist/chrome_extension/tts-platform-prototype.zip` by default.
  - the Chrome extension package now includes `INSTALL.md`,
    `TROUBLESHOOTING.md`, plus manifest/action PNG icons for local Chrome
    handoff builds.
  - the packaged extension install guide now points extracted Windows bundle
    users at `scripts\windows\install_local.ps1` before service launch,
    extension loading, origin allow-listing, and token save.
  - `scripts/check_chrome_extension_smoke.py` now provides an optional real
    Chrome/Edge MV3 smoke for page capture and playback startup evidence, and
    it uses `extension-allow-origin` for service allow-list setup.
  - `scripts/release_check.py --require-browser` now forwards strict Chrome/MV3
    browser-smoke requirements into that same smoke script, with
    `--browser-executable` and `--headed` pass-through support.
  - the extension manifest no longer requests `<all_urls>` in
    `host_permissions`; service host permissions are limited to localhost, while
    page access remains in the declared content script.
  - `scripts/check_extension.py` now validates extension manifest policy and
    privacy/layering boundaries, including blocking content-script service
    calls, popup/offscreen storage use, broad browser persistence APIs, and
    non-offscreen WebSocket creation.
  - `scripts/check_extension.py` now validates local installability assets:
    `INSTALL.md`, `TROUBLESHOOTING.md`, plus the manifest/action icon set.
- Release hardening has started:
  - `security.allowed_origins` entries are normalized for harmless trailing
    slashes and must be explicit `http`, `https`, or `chrome-extension` origins.
  - wildcard, `null`, path-bearing, query-bearing, fragment-bearing, and
    unsupported-scheme origin entries fail config load.
  - `scripts/release_check.py` now runs the local release gate without requiring
    live service credentials.
  - `scripts/release_check.py --live-smoke` can also run the public-contract
    smoke script against an already running service using `--token`,
    `--token-file`, and optional `--voice`.
  - `scripts/release_check.py --real-voice-demo` can also run the optional real
    English voice demo as an explicit acoustic-output gate, with
    `--install-real-runtime` available when the selected Python environment
    should bootstrap `.[real]` first.
  - `scripts/release_check.py` redacts inline `--token` values in its JSON
    summary so release logs do not echo bearer tokens.
  - `scripts/release_check.py` now validates the Windows local reader bundle in
    addition to ruff, pytest, extension validation, and extension zip packaging.
  - `scripts/check_security_defaults.py` now verifies `config/config.example.toml`
    and `.gitignore` keep the v1 local-reader defaults fail-closed: loopback
    host, token auth, repo-local token path, empty origin allow-list, rate
    limiting, metrics, long stream limit, local CPU backend defaults, and
    ignored local token/model artifacts.
  - `scripts/release_check.py` now runs the security-default verification as
    part of the local release gate.
  - `scripts/smoke_service.py` now accepts separate WebSocket stream text via
    `--stream-text`, `--stream-text-file`, and `--stream-text-repeat`, plus
    `--min-stream-text-chunks` to assert page-scale stream chunking without
    sending the same long input through the shorter HTTP/job contracts.
  - `scripts/release_check.py --live-smoke` forwards those long-stream smoke
    options and redacts inline `--text` / `--stream-text` values from its JSON
    summary.
  - `docs/v1_readiness.md` now records automated gates, manual gates, explicit
    product choices, and known not-yet-automated checks for the local reader v1
    target.
  - `scripts/check_v1_readiness.py` now verifies that readiness evidence stays
    wired into docs, release checks, extension validation, smoke tooling, and the
    Windows local reader bundle.
  - `scripts/release_check.py` now runs the v1-readiness verification as part of
    the local release gate.
  - `scripts/check_windows_bundle_bootstrap.py` now safely extracts a Windows
    local reader bundle, verifies the absence of local token/model artifacts,
    checks first-run/model-readiness guide markers, checks the embedded
    extension zip including install/troubleshooting guides and icons, and runs
    `setup-local` from the extracted source paths.
  - local service and Windows bundle bootstrap checks now expose and validate
    `setup-local` next-step guidance, including `tts model-check`, in their
    JSON summaries.
  - `scripts/release_check.py` now runs the Windows bundle bootstrap check after
    building the bundle.
  - `scripts/check_windows_bundle_install.py` now verifies a built/extracted
    Windows bundle through temporary `.venv` creation, package install,
    installed `tts setup-local`, installed `tts serve`, and public-contract
    smoke.
  - `scripts/check_windows_bundle_install.py` now exposes and validates the
    installed `setup-local` next-step guidance, including `tts model-check`, in
    its JSON summary.
  - Windows bundle bootstrap and install checks now also validate the default
    catalog model id and require the concrete default model install command to
    be the first setup next step.
  - `scripts/check_windows_launchers.py` now extracts a Windows bundle and
    verifies the bundled PowerShell/CMD launchers in setup-only mode when
    Windows launcher executables are available.
  - Windows launcher setup-only summaries now expose `setup-local` next-step
    guidance, including `tts model-check`, alongside config/token creation
    evidence.
  - Windows launcher setup-only summaries now also expose
    `catalog_single_installable_model`, matching bundle bootstrap/install
    summaries.
  - `scripts/check_windows_launchers.py` now also starts bundled PowerShell/CMD
    launchers as foreground services on reserved loopback ports, runs
    public-contract smoke, and stops the process trees.
  - `scripts/check_local_service_bootstrap.py` now starts a temp first-run
    loopback service and runs public-contract smoke without repo-local config
    or token side effects.
  - `scripts/check_local_service_bootstrap.py` now seeds the default catalog
    and validates that first-run setup output starts with the concrete default
    English model install command.
  - `scripts/release_check.py` now runs local service bootstrap and
    model-management flow smoke checks as deterministic offline readiness gates.
  - `scripts/release_check.py` now runs extension onboarding contract smoke as
    a deterministic local gate before extension packaging.
  - `scripts/release_check.py` now runs extension reader-flow smoke before
    extension packaging.
  - `scripts/release_check.py` now runs the skip-aware Chrome/MV3 browser smoke
    before extension packaging.
  - `scripts/package_windows_bundle.py` now includes the Chrome/MV3 smoke
    harness in the Windows local reader bundle.
  - The generated `WINDOWS_BUNDLE_README.md` now puts the default English
    `model-install` command before model readiness re-checking, matching
    `setup-local` next-step guidance.
  - The generated `WINDOWS_BUNDLE_README.md` now also uses the venv-local
    `python -m pip install -e ".[real]"` command before real playback
    readiness checks instead of listing duplicate single-package installs as
    the primary path.
  - The generated `WINDOWS_BUNDLE_README.md` now also includes direct
    bundle-compatible extension validation commands, including strict
    Chrome/MV3 smoke with `--require-browser` and `--browser-executable`, so
    extracted-bundle users do not need to infer repo-only release-check flows.
  - `scripts/check_local_reader_bundle.py` now provides a bundle-compatible
    local validation entry point that avoids repo-only `pytest` and `.gitignore`
    assumptions while still exercising service bootstrap, model management,
    extension onboarding, reader flow, Chrome/MV3 smoke, and optional real voice
    demo checks.
  - `scripts/check_local_reader_bundle.py` now keeps its own stdout to a single
    JSON summary by relaying child check output to stderr, so higher-level gates
    can consume it as a nested machine-readable check.
  - `scripts/check_windows_bundle_install.py --run-local-reader-check` now
    runs that bundled local-reader validation with the installed `.venv` Python
    after extracted-bundle install, installed `tts serve`, and public-contract
    smoke have passed.
  - `scripts/check_windows_bundle_install.py` now accepts
    `--node-executable`/`--require-js-syntax` for temporary no-`--bundle`
    package builds and forwards inherited or explicit `--local-reader-*`
    strict JavaScript/browser flags into the nested local-reader validation.
  - `scripts/check_extension_reader_flow.py` now covers stop/restart recovery
    and popup reopen-state wiring in addition to the generated long-page stream
    smoke.
  - `scripts/check_extension_reader_flow.py` now verifies `Continue Page`
    wiring and truncated text-offset continuation metadata in addition to
    truncated section continuation.
  - `scripts/check_extension_reader_flow.py` now verifies automatic truncated
    text-offset continuation wiring after normal page segment completion.
  - HTTP request logs now keep only low-sensitivity metadata: method, path
    without query string, status, duration, outcome, and request id.
  - Client-provided `X-Request-ID` values are reused only when they are short,
    simple identifiers and are not bearer-shaped or equal to the current auth
    token; unsafe values are replaced with server-generated ids.
  - async job submissions now enforce the configured in-memory job retention
    cap against queued/running work, returning `429` when the backlog is full
    instead of retaining unbounded futures/executions.
  - async jobs now enforce the configured `limits.max_job_seconds` lifetime by
    marking queued/running jobs failed, requesting backend cancellation, and
    preserving that terminal state if backend work finishes late.
  - sentence segmentation now bounds abbreviation lookbehind to the longest
    known abbreviation token, removing the quadratic punctuation-only path
    before backend synthesis.
  - remote model artifact downloads now enforce a maximum size, catalog
    `artifact_size_bytes` streaming cap, `Content-Length` validation, manual
    redirect destination checks, and credential-free HTTP(S) artifact URLs.
  - Windows CMD launchers now delegate to a trusted system PowerShell path
    instead of bare executable lookup.
  - the top-level release gate can now opt into installed-bundle local-reader
    validation with `--windows-bundle-local-reader-check`, forwarding strict
    Node/Chrome smoke flags to the nested bundle check.
  - manual Chrome reader page actions now guard against applying stored page
    progress to a different active tab; operators must switch back to the
    original page tab before using `Resume Page`, `Continue Page`, `Previous
    Section`, or `Next Section`.
  - the popup now exposes source-tab status for stored page playback and
    disables manual page actions when another tab is active.
  - the popup now exposes `Focus Page`, allowing the operator to return to the
    original source tab from stored page playback metadata without persisting a
    page URL or raw page text.
  - the extension background worker now validates saved service `Base URL`
    values as localhost-only HTTP origins before fetch/WebSocket use, and
    popup messaging surfaces background `ok: false` errors when settings are
    rejected.
  - `/v1/health` now exposes the active TTS request and stream text limits, and
    the Chrome extension uses the stream limit to clamp page-capture size before
    page playback.
  - the optional Chrome/MV3 smoke now verifies that the real browser `Speak
    Page` flow stores page-capture metadata capped at the service stream text
    limit when that limit is lower than the extension's configured page limit.
  - the extension offscreen audio scheduler now respects `highWatermarkMs`,
    bounding how far ahead browser audio is scheduled and topping up queued PCM
    chunks as scheduled sources finish.
  - a pre-final v1 security hardening pass found and fixed six local-reader
    gaps across protected HTTP request ordering, WebSocket startup timeout,
    sanitized validation errors, model archive extraction quotas, remote model
    artifact DNS/private-network checks, and Chrome extension resource
    exposure. The generated Codex Security report records zero open findings
    for the current working tree at this point in the project.
  - `docs/v1_completion_audit.md` now maps the `docs/codex/Prompt.md`
    `Done When` criteria to authoritative repo evidence, and
    `scripts/check_v1_completion.py --require-complete` verifies the final v1
    state. The audit shows all nine criteria ready and
    `can_mark_v1_complete: true`.
- This Codex memory structure is now in place:
  - `docs/codex/Prompt.md`
  - `docs/codex/Plan.md`
  - `docs/codex/Implement.md`
  - `docs/codex/Documentation.md`

## What Is Next

- Start Reader Workstation Milestone 1 from
  `design_doc/reader_workstation_design_v1.md`: implement the backend-agnostic
  Reader domain, explicit SQLite migrations, repositories, integrity/schema
  reporting, stable block cursors, revisioned content edits, Undo/Redo, the
  SQLite backup primitive, and `[reader]` per-user-home configuration without
  adding HTTP or WPF code.
- V1 remains complete at the repo/test-contract level and must stay green as a
  protected regression baseline throughout Reader work.
- If the service is intentionally exposed beyond loopback in a future milestone,
  run a new scoped security pass for origin, token, rate-limit, and WebSocket
  controls under that changed deployment model.
- If third-party remote catalogs become a supported end-user feature instead of
  an operator-controlled escape hatch, add signed catalog or pinned-host policy
  work before treating that channel as trusted.
- The Windows SAPI bridge in `docs/sapi_bridge.md` remains an optional
  compatibility client. It is not the active product track and must not shape
  Reader domain or desktop architecture.

## Decisions Made And Why

- The Reader Workstation design is now the active post-v1 product direction.
  It adds a service-owned local library and thin WPF client while preserving the
  existing TTS service as the single synthesis authority.
- Editable text uses stable block IDs, content revisions, integer row versions,
  and bounded edit operations. Playback owns a temporary content lease rather
  than forcing documents to be permanently immutable.
- `%LOCALAPPDATA%\TTSPlatform\Reader` is the installed data default. Future
  cross-device sharing must use APIs, not copied SQLite files.
- Clipboard append is a primary Reader workflow. TextAloud rule migration and
  OCR are not 1.0 gates.
- `docs/codex/` is now the Codex-oriented source of truth so future loops do not have to rediscover scattered instructions.
- `AGENTS.md` remains the entry point for repo rules, but it now points directly to the four Codex workflow files.
- Later phase trackers were treated as stronger than older summary docs when they conflicted.
- Existing legacy docs were mostly left in place as reference material to avoid disruptive rewrites.
- Windows is now recorded explicitly as the final target platform so future loops do not overfit to the current WSL development environment.
- Windows runner fallback is now documented in `AGENTS.md` because some Windows
  sessions resolve `python3` to the Microsoft Store alias.
- A repo-native smoke script was added because long-running Codex loops benefit more from one deterministic public-contract check than from repeated manual `tts` and benchmark commands.
- The chunk-plan improvement was implemented inside `ChunkPlanner` only, without changing public API schemas or service orchestration, so sync/jobs/streaming continue to share the same `prepare_request` entry point.
- This loop stayed focused on the Milestone 2 streaming architecture slice and did not start Milestone 3, even though the user allowed "more if you think you can handle it", because the repo runbook prefers validated milestone-sized slices over bundling unrelated behavioral changes.
- The service now uses the backend streaming contract as its primary streaming
  path. Real runtimes with generation callbacks can emit callback audio;
  stub mode and older runtimes still generate a full PCM buffer before chunk
  emission.
- Cancellation is terminal and observable at the service-contract level. Real
  runtimes with generation callbacks can stop at callback boundaries; hard
  interruption inside a callback interval remains best-effort.
- The real `sherpa_onnx` runtime callback API is feature-detected rather than
  assumed. Supported runtimes stream callback audio and can stop at callback
  boundaries; unsupported runtimes fall back to full-buffer generation while
  preserving public contracts.
- Long page playback should use WebSocket streaming with
  `tts.max_chars_per_stream` instead of raising `tts.max_chars_per_request` for
  every endpoint. This keeps sync HTTP and async job memory/latency expectations
  bounded while allowing the browser reader to handle page-scale text.
- Reader progress should stay tied to planned text chunks, not audio frame
  counts, because audio frame counts vary by backend/runtime while planned text
  chunks are stable enough to support resume UX.
- Extension resume should re-extract active-tab text and reuse the latest
  planned text chunk index instead of persisting raw page text in extension
  storage.
- Extension page-capture diagnostics should also avoid raw page text. Counts,
  extraction source, readable block count, and truncation status are enough to
  explain bounded long-page playback without creating a text-storage surface.
- Extension page-structure diagnostics should preserve useful section signals
  by keeping short headings in captured text and storing counts only in session
  metadata. Rich named reader outlines still need a later explicit UX slice.
- Extension section navigation should re-extract active-tab text from a section
  index rather than persisting raw page text. Current navigation is heading
  offset based; richer named outlines remain future UX work.
- Truncated-page continuation should remain metadata-only. A section index is
  enough for `Next Section` to ask the content script to re-extract from the
  active tab, while raw page text and heading text stay out of extension
  storage.
- Truncated flat-page continuation should also remain metadata-only. A
  character offset is enough for `Continue Page` to ask the content script to
  re-extract from the active tab, while raw page text stays out of extension
  storage.
- Automatic truncated flat-page continuation should reuse the same metadata
  boundary as manual `Continue Page`: source tab id, original
  `startSectionIndex`, and `nextTextCharStart`, never persisted raw page text.
- First-run model setup should prefer one clear local command where possible:
  `tts model-install <id> --catalog <catalog> --activate`.
- The first default English catalog voice should use the official
  sherpa-onnx-converted `vits-piper-en_US-lessac-medium` artifact instead of
  the raw Piper `.onnx + .onnx.json` files, because the converted archive
  includes `tokens.txt` and `espeak-ng-data` required by the current
  sherpa-onnx VITS backend contract.
- A successful real-model install should not be committed by writing the
  installed voice into `models/MANIFEST.json` without the corresponding ignored
  `models/voices/` assets. The committed catalog is the durable source; local
  installs may update the manifest as local machine state.
- `model-check` should prefer concrete installable catalog guidance over
  reinstalling the configured development stub when the stub is not real-ready.
  With one default catalog entry, the operator should see
  `tts model-install vits-piper-en_US-lessac-medium --activate` as the first
  useful recovery step.
- `setup-local` should reuse that same default-catalog guidance during
  first-run setup so Windows bundle users see the real-model install step
  before starting Chrome playback.
- Model-management CLI stdout should remain structured JSON for automation; any
  human progress chatter belongs on stderr.
- Relative model artifact paths should be resolved from the catalog source that
  declared them. Local catalogs use their parent directory; remote HTTP catalogs
  use the catalog URL as the download base.
- Model artifacts should be treated as large files during install. Stage them
  to temporary storage, hash them from disk, and extract from disk instead of
  keeping a full artifact-sized byte string in memory.
- First-run setup may create local config and token files, but should not choose
  a Windows service manager or persistence mechanism until that product
  direction is explicit.
- Installed CLI service startup should prefer `tts serve`; `scripts/dev_run.py`
  remains a development convenience.
- Windows launcher scripts are acceptable packaging progress without choosing a
  persistent service mechanism. Do not silently choose NSSM, Task Scheduler,
  pywin32, or startup-folder auto-run without an explicit product decision.
- A local `.venv` bootstrap script is acceptable packaging/install progress as
  long as it remains foreground/local and does not choose persistence or
  auto-start.
- The Windows local reader bundle is a source handoff package, not a persistent
  service-manager installer. It moves installability forward while preserving
  the explicit later choice around NSSM, Task Scheduler, pywin32, or auto-start.
- Extension onboarding should expose readiness state in the popup, while
  browser-specific behavior remains inside `apps/chrome_extension/`.
- Extension zip packaging is local handoff/installability only; Chrome Web Store
  signing or publishing is out of scope until explicitly chosen.
- Chrome extension local installability should be self-contained in the
  extension zip: manifest at archive root, `INSTALL.md`,
  `TROUBLESHOOTING.md`, and the packaged icon set referenced by the manifest
  and action.
- Browser allow-list config should fail closed. Empty `allowed_origins` remains
  the secure default; configured entries must be explicit origins, not wildcards
  or URL paths.
- The local release gate should avoid requiring live service credentials. Live
  public-contract smoke tests remain separate because they require a running
  service and token.
- Optional live smoke belongs behind an explicit release-check flag so local
  validation can stay deterministic when no service is running.
- Release-check summaries must not echo bearer-token values.
- HTTP request logs should preserve correlation without becoming a user-input
  echo surface. Short simple client request ids are acceptable; bearer-shaped,
  overlong, malformed, or current-token values are replaced before logging or
  response propagation.
- Under the current Codex sandbox, some service tests that depend on local socket/network capabilities needed unsandboxed execution to validate correctly. The repo itself passed once run without those sandbox limits.
- Because this repository is jointly owned by the user and Codex, successful
  Codex runs now default to committing and pushing the completed slice. Codex
  should still stop before pushing when validation fails, credentials are
  missing, branch/remote state is unsafe, or the user explicitly says not to.
- The project has reached v1 completion at the repo/test-contract level.
  Future Codex loops should treat release packaging, real-machine smoke, and
  post-v1 polish as follow-up work rather than blockers for the current goal.
- For v1 autostart, prefer a per-user Windows Task Scheduler task over a true
  Windows Service, NSSM, or Startup-folder shortcut. This matches the local
  desktop reader shape, avoids admin requirements, and keeps GPU/runtime/user
  environment behavior simpler for v1.
- The final security-focused pass was run with Codex Security workflows and
  subagents. Accepted findings were fixed in the working tree rather than left
  as open report items, and the final report records 0 open reportable
  findings.
- The v1 completion audit is now repo-native and final. It reports
  `can_mark_v1_complete: true` only because the final security evidence in
  `docs/v1_final_security.md` is present.
- This loop intentionally reordered one v1-enabling model-management slice
  ahead of Phase 7 Milestone 3 because the user restated the product goal as a
  local server plus Chrome reader for long web content; a usable voice install
  path is a prerequisite for that end state.
- The SAPI/TextAloud bridge should be an optional Windows client integration,
  not a core API redesign. Keep it isolated under `apps/sapi_bridge/` and have
  it call the existing localhost service.
- The first SAPI bridge slice should prove COM/SAPI registration and TextAloud
  visibility with dummy audio before connecting to `/v1/tts`. This prevents
  spending integration effort before resolving likely 32-bit vs 64-bit and
  registry-token issues.
- For the SAPI bridge MVP, prefer synchronous `/v1/tts` over WebSocket
  streaming. Streaming can be revisited after TextAloud visibility, basic audio
  output, stop handling, and long-text chunking are understood.

## Commands To Run And Smoke Test

Baseline validation:

```bash
python3 -m pytest -q
python3 -m ruff check .
python3 scripts/release_check.py
python3 scripts/release_check.py --windows-bundle-local-reader-check
python3 scripts/release_check.py --live-smoke --token-file config/token.txt
python3 scripts/release_check.py --real-voice-demo --install-real-runtime
python3 scripts/release_check.py --require-browser --browser-executable <path-to-browser>
python3 scripts/package_windows_bundle.py
python3 scripts/check_local_reader_bundle.py
python3 scripts/check_v1_readiness.py
py -3 scripts/check_desktop_reader.py --require-windows-integration
python3 scripts/check_windows_bundle_bootstrap.py --bundle dist/windows/tts-platform-local-reader.zip
python3 scripts/check_windows_launchers.py --bundle dist/windows/tts-platform-local-reader.zip
python3 scripts/check_windows_bundle_install.py --bundle dist/windows/tts-platform-local-reader.zip
python3 scripts/check_windows_bundle_install.py --bundle dist/windows/tts-platform-local-reader.zip --run-local-reader-check
python3 scripts/check_windows_bundle_install.py --node-executable <path-to-node> --require-js-syntax --run-local-reader-check
```

First-run setup:

```bash
tts setup-local
```

Service start:

```bash
scripts/windows/install_local.cmd
tts serve
python3 scripts/dev_run.py
scripts/windows/run_service.cmd
```

Public-contract smoke commands after the service is running:

```bash
tts health
tts list-voices
tts model-install vits-piper-en_US-lessac-medium --activate
tts save "Hello world" --out out.wav --token "$TTS_PLATFORM_TOKEN"
tts stream "Hello world" --out stream.wav --token "$TTS_PLATFORM_TOKEN"
tts catalog-list --catalog ./models/catalog.json
tts model-install <model-id> --catalog ./models/catalog.json
tts model-activate <model-id>
tts model-check <model-id>
tts model-remove <model-id>
tts extension-allow-origin <chrome-extension-origin>
python3 scripts/check_model_management_flow.py
python3 scripts/check_extension_onboarding.py
python3 scripts/check_extension_reader_flow.py
python3 scripts/check_chrome_extension_smoke.py
python3 scripts/check_chrome_extension_smoke.py --require-browser --headed
python3 scripts/smoke_service.py --token "$TTS_PLATFORM_TOKEN"
python3 scripts/smoke_service.py --token-file config/token.txt
python3 scripts/smoke_service.py --token-file config/token.txt --stream-text-repeat 200 --min-stream-text-chunks 2
python3 scripts/benchmark.py --mode http --token "$TTS_PLATFORM_TOKEN"
python3 scripts/benchmark.py --mode stream --token "$TTS_PLATFORM_TOKEN"
python3 scripts/benchmark.py --mode job --token "$TTS_PLATFORM_TOKEN"
```

Extension structural smoke:

```bash
python3 scripts/check_extension.py
python3 scripts/check_chrome_extension_smoke.py
python3 scripts/package_extension.py
python3 scripts/package_windows_bundle.py
```

## Known Issues And Follow-Ups

- `README.md` previously presented a Phase 6 status snapshot, while `TASKS.md` and the Phase 7 notes showed additional completed work. The new Codex docs treat the later Phase 7 sources as stronger.
- `ARCHITECTURE.md` still describes a much earlier architecture snapshot centered on Phase 2. Use it as background only.
- The original design doc uses `kokoro-en-heart` in examples, but the current manifest and config example use `sherpa-en-debug`.
- Older loops ran in WSL, but future code and docs should not assume WSL or
  Windows PowerShell exclusively.
- Some sessions run in Windows PowerShell instead of WSL; use `py -3` when
  `python3` resolves to the Windows Store alias.
- Real-runtime streaming now uses `sherpa_onnx` generation callbacks when the
  installed package supports them. Stub mode and older real runtimes still use
  full-buffer generation followed by local chunk emission.
- Running-work cancellation can now stop supported real runtimes at generation
  callback boundaries. Hard interruption inside one callback interval remains a
  backend/runtime limitation.
- The default example config still points at the development stub voice. A real
  local voice must be installed and activated before real acoustic output is the
  normal local run path.
- The default catalog can now install `vits-piper-en_US-lessac-medium`, but
  `sherpa_onnx` and `numpy` are still optional local runtime dependencies.
  `setup-local`, `model-list`, and `model-check` now report
  `python -m pip install -e ".[real]"` when both are missing, and targeted
  single-package guidance when only one runtime dependency is absent.
- Long page playback now has a larger WebSocket text limit, stream progress
  metadata, a basic popup resume action, and page-capture metadata/truncation
  visibility. It now preserves short headings, reports structure counts, and
  can continue truncated flat pages by text offset manually or automatically
  after a segment finishes. The offscreen player bounds scheduled browser audio
  with `highWatermarkMs`, but the flow still lacks a full named reader-mode
  outline.
- The Windows bundle still requires the operator to run the bundled install
  script, load the Chrome extension, and configure the service allow-list after
  extraction. The virtualenv install/start path is now covered by an automated
  temp-venv smoke, and launcher setup-only plus foreground service smoke
  execution is covered for PowerShell/CMD.
- V1 Windows autostart now uses a per-user Task Scheduler task. A machine-wide
  Windows Service, NSSM, pywin32, or Startup-folder mechanism remains out of
  scope without a new explicit product decision.
- The default Chrome/MV3 smoke is opportunistic so offline release gates remain
  usable across machines. Use
  `python3 scripts/check_chrome_extension_smoke.py --require-browser --headed`
  or `python3 scripts/release_check.py --require-browser --headed` when strict
  local browser evidence is required. Branded Chrome 137+ may ignore
  command-line unpacked extension loading; for strict automated evidence, pass
  Chrome for Testing or Chromium with `--browser-executable`.
- In this Windows session, Chrome discovery succeeded, but the installed branded
  Chrome did not register the unpacked extension from `--load-extension`; the
  smoke therefore returns a skipped JSON result in default mode with extension
  registration diagnostics.
- `python3 scripts/check_extension.py` still skips JavaScript syntax checks by
  default in this environment because `node` is not installed on `PATH`, but it
  now supports `--require-js-syntax`, `--node-executable`, and
  `TTS_PLATFORM_NODE` for strict validation when Node.js is available elsewhere.
- The SAPI bridge has a working X86 native registration and verified localhost
  synthesis path, but it remains an optional compatibility client. X64
  registration and product hardening are not active Reader Workstation gates.

## Resume Instructions For The Next Codex Loop

1. Open `docs/codex/Prompt.md`, `docs/codex/Plan.md`, and `docs/codex/Implement.md`.
2. Read `design_doc/reader_workstation_design_v1.md`, then check this file for
   current status and any newly recorded blockers.
3. Treat v1 as complete unless a new blocker is discovered from fresh evidence.
4. Resume at Reader Workstation Milestone 6 only after the user explicitly asks
   to continue. Add structured offline import, preview/cancellation/warnings,
   and book-scale virtualized reading; preserve the completed clipboard and
   playback behavior.
5. If a future milestone changes deployment exposure, model catalog trust, or
   extension distribution, update the threat model and rerun a scoped security
   pass before relying on the old v1 security evidence.
6. Run the relevant validation commands before handing off and update this file
   again with the new status.
