# Documentation

This file is the live status log and shared memory for future Codex loops.

## Current Status

- Date: 2026-08-15
- Workflow status: `docs/codex/` is the Codex source of truth for project spec, execution order, operating rules, and resume context. After a successful run, Codex should commit and push the completed slice by default.
- Project status: Phases 1 through 7 and the v1 local reader are complete at the
  repository behavior and test-contract level. The active post-v1 product track
  is now the Reader Workstation defined in
  `design_doc/reader_workstation_design_v1.md`.
- Completed the progress-template crash hotfix. Field use populated the new
  progress template and exposed WPF's default TwoWay binding for
  `ProgressBar.Value`; WPF attempted to write into the read-only display
  percentage and terminated the Reader. The binding is now explicitly OneWay,
  and the desktop source gate requires that safety property.
- Crash-hotfix validation passed on 2026-08-15: Ruff and the complete Windows
  desktop integration check passed. A field-equivalent manual automation then
  opened the rebuilt Reader, opened Library, selected Audio exports while the
  real export row existed, rendered one progress bar, and verified that the
  Reader remained alive. The service-owned MP3 job continued from 37 to 57
  percent while the desktop was repaired, proving that the desktop crash did not
  terminate export work.
- The same field export later exposed a separate terminal-bookkeeping anomaly:
  the database row reported `failed` with `PermissionError`, while service
  metrics recorded one completed export and FFprobe verified a complete MP3 in
  the private export directory. The generated audio is usable, but the failed
  row cannot use **Save selected as...**. Root-cause investigation and a safe
  reconciliation path remain a follow-up; no database row was edited manually.
- Completed the desktop export-request hotfix after field use exposed that
  nullable unused collection fields were serialized as JSON `null` and rejected
  by the service's list contract. Current-article exports now omit unused queue
  and section collections; queue exports omit unused document and section
  collections. API validation errors also surface their first rejected field
  and explanation instead of only the generic validation message.
- Export-request hotfix validation passed on 2026-08-15: 91 .NET Release tests,
  .NET formatting, and the complete Windows desktop integration check passed,
  including schema-6 preview storage, live Reader flows, WASAPI,
  clipboard/hotkey/tray integration, self-contained packaging, and packaged WPF
  rendering. The actual schema-6 service remained healthy during the Reader
  rebuild. No Python/service behavior, persistence, architecture, security,
  licensing, model, or deployment direction changed.
- Runtime context: the intended end platform is Windows. Codex sessions may run from Windows PowerShell or WSL, so commands and docs should avoid assuming only one shell.
- Completed the field-reported export-progress and polling correction. Export
  jobs now persist a phase and integer percentage in Reader schema 6. Synthesis
  advances by completed speech fragments, MP3 encoding and final publication
  have explicit phases, and 100% is reserved for a completed, available file.
  The Audio exports grid renders a real progress bar with phase, percentage, and
  document count instead of only `0/1` to `1/1` text.
- Export refresh is now rate-safe and non-overlapping: active jobs poll every
  four seconds, terminal/empty lists every 15 seconds, and a service 429 applies
  a 61-second automatic backoff. Together with the main window's ten-second
  desktop-open poll, steady active use remains below the shared default limit of
  30 localhost requests per minute.
- Export-progress validation passed on 2026-08-15: all 414 Python tests and all
  89 .NET Release tests passed, as did Ruff, .NET formatting, Reader contract
  fixtures, `git diff --check`, and the complete Windows desktop integration
  check. That check covered live Reader paging/edit/streaming, WASAPI,
  clipboard/hotkey/tray integration, schema-6 preview storage, self-contained
  packaging, and packaged WPF rendering. Focused tests cover monotonic durable
  progress, progress observed during a blocked second synthesis fragment, and
  active/idle polling intervals. No architecture, security, licensing, model,
  or deployment direction changed.
- The actual Reader-owned service was restarted after validation and migrated
  the user's existing database to schema 6. Its configured port 7777 reported
  status `ok`, the `sherpa_onnx` backend with Kokoro `af_heart` as the default
  voice, and ready `wav,mp3` export formats; the rebuilt Reader was left open and
  connected with its ownership lease intact.
- Extended the existing service-owned WAV job pipeline with a durable
  `audio_format` contract and schema migration 005. WAV and MP3 now share
  bounded synthesis, speech rules, voice selection, progress, cancellation,
  safe filenames, no-overwrite checks, temporary files, and atomic publication.
- MP3 uses a validated local FFmpeg executable and `libmp3lame` through a fixed
  argument array with no shell. The default is 96 kbps mono with article-title
  metadata. FFmpeg is not bundled; a failed identity/encoder probe removes MP3
  from service capabilities while WAV remains usable.
- The desktop's **Audio exports** workflow obtains ready formats from the
  service, prefers MP3 when available, shows the job format, and can stream a
  completed single-article result through **Save selected as...** to a
  user-chosen location using another temporary-file/atomic-move boundary.
- MP3 implementation validation passed earlier on 2026-08-15: all 413 Python tests, all
  85 .NET Release tests, Ruff, .NET formatting, Reader contract fixtures,
  `git diff --check`, application build, and the complete Windows desktop
  integration check passed. The encoder tests include a real installed-FFmpeg
  round trip that produced a decodable MP3 with title metadata. The actual
  Reader service had migrated to schema 5 and reported ready export formats
  `wav,mp3` with the Kokoro backend healthy.
- Reader Workstation resume point: Milestone 10, PDF text extraction, only after
  the user explicitly continues the track.
- Completed the Reader application-icon follow-up. The transparent source PNG
  and multi-resolution Windows ICO now live under the WPF application's
  `Assets` directory. The ICO contains 16, 20, 24, 32, 40, 48, 64, 128, and
  256-pixel frames, is embedded as the executable application icon, and is used
  explicitly by the main window and taskbar-visible clipboard prompt. Existing
  project-root shortcuts inherit the icon from their Reader executable target,
  and self-contained publishing carries the embedded resource into the portable
  package.
- The icon was generated with the built-in ImageGen workflow as a simple
  navy/teal/white open-book and sound-wave mark, with no text or third-party
  branding. The result arrived with a clean alpha channel, so the planned local
  chroma-key removal was unnecessary. Pillow was used only as a local build-time
  asset tool to create and inspect the multi-resolution ICO; it is not a Reader
  runtime or distribution dependency. The embedded icon was extracted back from
  the built executable and visually verified at Windows' 32-pixel size.
- Application-icon validation passed on 2026-08-14: all 403 Python tests, all 85
  .NET Release tests, Ruff, .NET formatting, `git diff --check`, and the complete
  Windows desktop integration check passed. The integration check verified live
  Reader flows, WASAPI, Windows clipboard/hotkey/tray integration,
  self-contained packaging, the new source-shape icon contract, and WPF
  rendering. No API, service, persistence, security, licensing, or model
  configuration changed.
- Completed the section-navigation field-use correction. The desktop now hides
  previous/next-section controls for articles whose document summary reports
  only one section. For structured articles with multiple sections, navigation
  walks the entire document in bounded 256-block search pages instead of
  stopping at the current 64-block display window. Editable documents reuse the
  already loaded full-document cache without additional service requests.
  Previous-section navigation resolves the first block of the preceding section,
  and API/service failures remain visible in the footer instead of escaping an
  asynchronous WPF event handler.
- Section-navigation validation passed on 2026-08-14: all 403 Python tests, all
  85 .NET Release tests, Ruff, .NET formatting, `git diff --check`, the desktop
  source/package/render check, and the complete Windows integration check
  passed. Three focused application tests cover forward and backward navigation
  across multiple API pages plus zero-request navigation from the editable
  document cache. The first integration attempt reached packaging but correctly
  failed because the prior Reader instance held the self-contained output DLLs;
  after closing that verified Reader process, the same check passed including
  live Reader flows, WASAPI, Windows integration, packaging, and WPF rendering.
  No API, persistence, security, licensing, or model configuration changed.
- Completed the first field-use UI follow-up after several days of normal Reader
  use. Clipboard prompts now activate topmost at screen center and appear in the
  taskbar; their owner is attached only when the Reader is already active. This
  prevents a browser or another foreground application from hiding the modal
  Add/Create/Ignore decision behind the main Reader window.
- Removed implicit caret intent from normal Play. Keyboard focus, mouse clicks,
  selection changes, and a clipboard dialog closing can no longer silently alter
  the next playback start. Normal Play now only resumes Pause or uses the durable
  Stop/beginning position. A separate, explicit `Start at cursor` action maps the
  current full-document caret to its Reader UTF-16 cursor and starts there.
- Long-document follow mode now asks `ReadingWindowPager` for the next 64-block
  viewport eight blocks before the current viewport ends, retaining sixteen
  blocks of preceding context. The visible article therefore continues before
  playback reaches an apparent page ending instead of replacing the entire view
  only after the active source span disappears. Follow-off still leaves manual
  paging under user control.
- Refreshed the WPF presentation without changing the application/service
  boundary: a navy status header, quieter connection card, card-based library and
  reading surfaces, a dedicated bottom playback bar, compact article tools,
  improved typography/spacing, a truthful service-status dot, and deterministic
  WPF vector icons replace the dense rows of equal-weight buttons. ImageGen was
  used for the design reference at
  `design_doc/assets/reader-ui-refresh-reference.png`; the generated bitmap is
  not a runtime dependency or a shipped icon asset.
- Field-use UI validation passed on 2026-08-14: all 403 Python tests, all 82
  .NET Release tests, Ruff, .NET formatting, `git diff --check`, and the complete
  Windows desktop integration check passed. The check covered live paging,
  UTF-16 editing, cursor persistence, stream synthesis, clipboard append/Undo,
  safe structured import, speech rules, WASAPI, Windows clipboard/hotkey/tray
  integration, self-contained packaging, and the refreshed WPF render. A focused
  application test proves context-preserving prefetch for a 150-block article.
- Completed Play/Pause/Stop semantics follow-up: `Pause` preserves the last
  fully heard cursor and the next Play resumes there. `Stop` now durably resets
  the next normal Play to the beginning of the article. Since the 2026-08-14
  field-use follow-up, caret starts require the explicit `Start at cursor`
  action rather than changing ordinary Play. Coordinator
  disposal and section seeking use a position-preserving internal interruption,
  so closing the app does not accidentally apply the user-facing Stop reset.
  Button tooltips now describe the distinction.
- Play/Pause/Stop validation passed on 2026-08-06: all 403 Python tests, all
  81 .NET Release tests, Ruff, .NET formatting, `git diff --check`, and the
  complete Windows desktop integration check passed. New coordinator tests
  cover Pause resume, Stop restart, a caret override after Stop, idempotent Stop,
  and position preservation during disposal. The integration check passed live
  edit/stream/resume, Kokoro synthesis, WASAPI, Windows integration, packaging,
  and WPF rendering.
- Completed user-requested Kokoro follow-up: the optional committed catalog at
  `models/catalog.kokoro.json` installs the official sherpa-onnx
  `kokoro-multi-lang-v1_0` package as `kokoro-en-v1_0-af-heart`, pins its
  artifact size and SHA-256, and selects English speaker 3 (`af_heart`). The
  smaller default `models/catalog.json` remains Piper-only, preserving the
  existing first-run and release-demo behavior. Kokoro model assets and local
  activation state remain ignored local data; the user's `models/MANIFEST.json`
  changes are deliberately excluded from repository commits. Piper remains an
  installed, one-command fallback.
- Kokoro exposed a backend configuration defect hidden by the VITS-first setup:
  resolved paths were copied into every sherpa-onnx model subconfiguration.
  Runtime construction now populates only the selected model type, and optional
  Kokoro `dict_dir` paths are supported through catalog installation, validation,
  and runtime loading. Regression tests cover model-type isolation and missing
  dictionary assets.
- Kokoro validation passed on 2026-08-04 with sherpa-onnx 1.13.4: all 397 Python
  tests, Ruff, catalog/model readiness, and live loopback HTTP, job, and
  WebSocket synthesis all completed with the default
  `kokoro-en-v1_0-af-heart` voice; synthesized audio was 24 kHz. No
  architecture, localhost security, exposure, or licensing direction changed;
  the selected model is Apache-2.0. Reader Workstation still resumes at
  Milestone 10 only when explicitly requested.
- Completed Markdown text-fence speech correction: Reader displayed imported
  fenced blocks but the speech compiler skipped every `code` block, so novel
  system messages such as `[ROUTE CONTINUITY DEGRADED]` silently jumped to the
  following paragraph. Importer version 2 now records the Markdown fence
  language. Fences labeled `text`, `txt`, `plain`, `plaintext`, or `prose` are
  spoken literally, while programming-language fences retain the planned
  article-profile skip behavior. A conservative compatibility check also speaks
  legacy imports whose metadata is absent when they contain a bracketed,
  uppercase notification header followed by punctuated text.
- Text-fence validation passed on 2026-08-04: all 400 Python tests, Ruff, and
  `git diff --check` passed. A live Reader WebSocket started directly at the
  existing chapter-02 block 51 and produced 350,828 PCM bytes while source marks
  covered all 120 characters. The separate imported
  `[IDENTITY RESOLUTION FAILED]` heading and following paragraph also produced
  audio across both source blocks. The service was restarted with Kokoro and
  left healthy; no stored document text, playback position, security setting,
  or model selection was changed.
- Completed continuous playback-buffer follow-up: the desktop coordinator no
  longer drains WASAPI after every cursor-advancing speech fragment. Audio can
  now remain buffered across paragraph and block boundaries and drains once at
  the end of a bounded Reader stream window. Submitted and conservatively
  estimated played-byte checkpoints keep Pause/Stop resume positions behind
  audio that may still be queued or within the 100 ms WASAPI target latency.
  The existing two-second backpressure target and hard ten-second memory limit
  are unchanged.
- Playback-buffer validation passed on 2026-08-04: all 74 .NET Release tests,
  including a regression requiring two fragments and only one terminal drain,
  all 400 Python tests, Ruff, .NET formatting, `git diff --check`, and the full
  Windows desktop integration check passed after the user disabled Windows
  Smart App Control. The latter covered live paging/stream/resume, shared-mode
  audio, clipboard/hotkey/tray integration, self-contained packaging, and WPF
  rendering. The repository architecture, localhost security model, and
  dependency set were not changed; a user-local official .NET 10 SDK was used
  because the machine-wide SDK remains .NET 8.
- Completed user-requested article deletion: the WPF document header now has a
  `Delete article...` action with a default-No warning. It calls the existing
  protected, row-versioned soft-delete contract, removes the article from
  normal library results and the reading queue, refreshes selection safely,
  and never deletes an external imported source file. This deliberately follows
  the design's recoverable-delete boundary; permanent erasure remains deferred
  until backup/restore exists.
- Added privacy-safe playback performance diagnostics before making another
  buffer-policy change. The desktop writes bounded JSONL events to
  `%LOCALAPPDATA%\TTSPlatform\Reader\logs\playback-performance.jsonl` with
  stream/window/chunk IDs, arrival gaps, PCM duration, submission time, WASAPI
  buffer duration, and suspected underrun counts. The service now emits one
  `reader_stream_performance` summary per stream window with first-audio and
  generation latency, generated-audio duration, real-time factor, maximum
  backend chunk gap, and slow-chunk count. Neither side logs document titles,
  source text, tokens, clipboard contents, or imported-file paths. No buffering
  thresholds were changed in this diagnostic slice; the next tuning decision
  should use a reproduced Kokoro trace.
- Article-delete and diagnostics validation passed on 2026-08-05: all 77 .NET
  Release tests, all 400 Python tests, Ruff, .NET formatting,
  `git diff --check`, and the complete Windows desktop integration check passed.
  The integration check covered live Reader stream/resume, WASAPI output,
  clipboard/hotkey/tray behavior, self-contained packaging, and WPF rendering.
- Completed played-audio highlight synchronization after the first reproduced
  Kokoro performance trace. The latest affected run contained 89 PCM packets,
  maintained an average 1.42-second WASAPI buffer and a 2.0-second maximum,
  had a maximum packet gap of 78 ms, and recorded one startup underrun. This
  showed that the visible sentence was moving when audio entered the buffer,
  up to roughly two seconds before that audio was heard, rather than exposing a
  sustained Kokoro generation shortfall.
- The desktop coordinator now schedules each source-span highlight at the first
  PCM byte submitted for that span and advances it from the conservatively
  estimated WASAPI played-byte checkpoint on a 20 ms monitor. Repeated backend
  PCM packets for the same source span are coalesced, so one sentence does not
  cause redundant visual updates. Durable resume cursors retain their existing
  fully-played checkpoint semantics. A regression test holds two submitted
  spans in a simulated output buffer and proves the second highlight stays
  hidden until its first byte is reported played.
- Played-audio highlight validation passed on 2026-08-05: all 78 .NET Release
  tests, all 400 Python tests, Ruff, .NET formatting, `git diff --check`, and
  the complete Windows desktop integration check passed. The integration check
  again covered live Reader streaming/resume, WASAPI output, Windows clipboard,
  hotkey and tray behavior, self-contained packaging, and WPF rendering. The
  existing two-second backpressure target remains unchanged based on the
  reproduced trace; this slice changes visual timing only.
- Completed the first measured Kokoro latency and rhythm tuning pass. A fresh
  affected Reader trace took 6.38 seconds to produce its first audio, later had
  a 9.47-second packet gap, and accumulated four WASAPI underruns. A controlled
  one-thread baseline needed an average 13.03 seconds to generate 6.55 seconds
  of the same speech (`RTF 1.99`). Four CPU inference threads reduced that to
  2.57 seconds (`RTF 0.39`). On the user's 16-core/24-thread i9-12900KF, eight
  threads were another 25 percent faster than four while twelve regressed, so
  the user-local config now uses eight and the portable default is four.
- Sherpa-onnx generation silence is now configurable as
  `backend.silence_scale`, bounded from `0` through `2` and reported in the
  backend health snapshot. The new default `0.06` retains a short sentence
  boundary while replacing the upstream `0.2` value that added roughly 223 ms
  per generated sentence in the measured Kokoro passage. With eight threads
  and the shorter boundary, the final controlled benchmark averaged 1.22
  seconds for 6.24 seconds of audio (`RTF 0.196`), about 10.7 times faster than
  the reproduced baseline. Speech rate itself remains `1.0`.
- The performance restart also exposed a Windows process-start race in the
  Reader fallback service controller: immediately after starting PowerShell,
  `Process.MainModule` can temporarily be unavailable. The ownership lease now
  falls back to the exact executable path from the `ProcessStartInfo` created
  by Reader. The service was then restarted through Reader with both its
  launcher PID and service PID recorded; unrelated processes remain outside the
  stop boundary.
- Kokoro latency/rhythm validation passed on 2026-08-05: all 403 Python tests,
  all 78 .NET Release tests, Ruff, .NET formatting, `git diff --check`, and the
  complete Windows desktop integration check passed. The latter again covered
  live Reader stream/resume, WASAPI output, clipboard/hotkey/tray behavior,
  self-contained packaging, and WPF rendering. The optimized real Kokoro
  service remains local on port 7777; Reader Milestone 10 remains deferred.
- Completed service-control ownership follow-up: the fallback service launcher
  was previously owned only through an in-memory `Process` handle. If Reader was
  restarted while that service remained alive, the new Reader correctly refused
  to kill an unverifiable Python process and `Stop service` reported that neither
  it nor a per-user scheduled task could be stopped. Reader now persists a small
  local ownership record at `%LOCALAPPDATA%\TTSPlatform\Reader\service-process.json`
  when it starts the fallback launcher. The record contains no token or document
  data. A later Reader verifies the launcher PID, exact start time, PowerShell
  executable, and bundled launcher path before it may stop the complete owned
  process tree. Missing, stale, malformed, or installation-mismatched records are
  rejected and never cause an arbitrary Python process to be selected.
- Service-control follow-up validation passed on 2026-07-29: 73 .NET Release
  tests, all 394 Python tests, Ruff, .NET formatting, `git diff --check`, and the
  complete Windows desktop integration check passed. A live transition also
  passed `Start service -> terminate Reader only -> open a new Reader -> Stop
  service`; the second Reader removed both the verified process tree and ownership
  record. Service was then started again with a new record and left running.
- Completed smart-Play follow-up: the separate `Play from cursor` button was
  removed. The single `Play` control now consumes a user-selected text cursor for
  the next start, then returns to normal durable resume behavior. Clicking in the
  text or moving the caret, including `Ctrl+Home`, selects that one-time start.
  (Since the 2026-08-06 follow-up, `Stop` instead resets normal Play to the
  beginning.) If either the live
  coordinator or the saved position says the document was completed, the next
  normal Play starts at the document's first cursor instead of reopening at the
  end. Clipboard replay, Pause, compact-controller, and global-hotkey behavior
  retain their existing semantics.
- The 2026-08-14 field-use follow-up deliberately supersedes the implicit-caret
  portion of that smart-Play experiment. Real clipboard use showed that focus
  restoration and click position made implicit intent indistinguishable from an
  accidental start. Explicit `Start at cursor` is now the supported behavior.
- Smart-Play validation passed on 2026-07-29: 71 .NET Release tests (including
  live-completion and persisted-completion restart regressions), all 394 Python
  tests, Ruff, .NET formatting, and `git diff --check` passed. The complete
  desktop check also passed live Reader streaming/resume, Windows integration,
  audio, self-contained packaging, WPF rendering, and a source assertion that
  the obsolete second playback button is absent.
- Completed continuous-editor rate-limit follow-up: the first full-document UI
  version fetched the same blocks separately for `DocumentEditor`, the reading
  page, and the continuous editor. Combined with normal browser-handoff polling
  and the live smoke session, selecting a document could receive HTTP 429 and
  leave the old view visible with `Document: Rate limit exceeded.` The optimized
  load fetches editable blocks once, loads the editor's active block from that
  result, and gives the complete block collection to `ReadingWindowPager` as a
  local cache. Page navigation and playback highlighting reuse that cache without
  more block requests. Library rows are updated in memory after Save/Undo/Redo,
  so normal selection no longer needs an extra document GET merely to obtain the
  current row version. If another local client still exhausts the shared limit,
  the footer now states that the document is not locked and Reader retries once
  automatically after the 60-second limiter window. A newer document selection
  supersedes that delayed retry.
- Rate-limit follow-up validation passed on 2026-07-29:
  - `.NET Release` solution tests increased to 69 and passed; focused tests prove
    three forward/back pages from a loaded editable document make zero additional
    block calls and that a mutated library row is replaced without an API refresh;
  - `py -3 -m pytest -q` passed all 394 tests, Ruff and .NET formatting passed,
    and `py -3 scripts\check_desktop_reader.py --require-windows-integration`
    passed the live Reader, Windows integration, audio, packaging, and WPF checks;
  - a fresh live service opened five documents consecutively, including both
    816-block articles, then reopened the 98-block/17,359-character article with
    its continuous editor every time and no rate-limit response;
  - no rate-limit threshold or security behavior was weakened. This is client-side
    request reuse and recovery only; `models/MANIFEST.json` remains excluded.
- Completed post-Milestone 9 continuous-editor correction: comparison with the
  TextAloud UI showed that separate inline `TextBox` controls still exposed the
  internal Reader blocks and prevented one selection from spanning an article.
  Stopped editable articles now assemble all source blocks into one conventional
  WPF text surface. Ctrl+A, selection, copy, and caret placement span the complete
  article, while a tested mapping converts the global caret back to the stable
  block ID and UTF-16 offset used by playback. The reading view remains paged and
  virtualized, but its ListBox containers have no focus, border, or selection
  chrome; source-span highlighting continues to mark the active sentence. To
  preserve the existing atomic block-edit and Undo contract, one saved edit may
  change one paragraph. A cross-paragraph mutation is restored locally with a
  clear message, although selection and copying may cross every paragraph.
  Continuous editing is bounded at 1,000,000 characters and 20,000 blocks so an
  extreme book cannot freeze WPF; larger documents retain the virtualized reader.
- Continuous-editor validation passed on 2026-07-29:
  - `.NET Release` solution build completed with zero warnings/errors and all 67
    tests passed. New tests cover document assembly, global caret mapping,
    single-paragraph edits, and rejection of separator-crossing edits;
  - `py -3 -m pytest -q`: 394 passed; one first-run WebSocket metric snapshot
    raced its existing cancellation cleanup, then its focused test passed five
    consecutive runs and the full suite passed. Ruff, .NET formatting, and diff
    checks passed;
  - `py -3 scripts\check_desktop_reader.py --require-windows-integration`
    passed live editing/resume, Windows audio, clipboard/hotkey/tray integration,
    portable packaging, WPF rendering, and the updated source contract;
  - live UI Automation opened the real 98-block article and found one document
    editor containing 17,359 displayed characters. A whole-document selection
    selected all 17,359 characters; the block list, page controls, and legacy
    block-edit controls were absent while stopped. A middle-paragraph edit enabled
    Save/Revert and Revert restored the full article without persistence. A
    separator-crossing edit was rejected/restored, and Play from a middle caret
    switched to the boundary-free reading view, entered Playing, then restored the
    continuous editor after Stop;
  - the user-owned `models/MANIFEST.json` remains excluded. No dependency,
    security, licensing, deployment, or backend contract changed. The design now
    records the bounded continuous-editor exception to the long-book rule.
- Completed post-Milestone 9 Reader workflow follow-up: the WPF header now
  reports whether the localhost TTS service is running and offers explicit
  Start/Stop controls. Start prefers the installed per-user Task Scheduler task
  and falls back to the bundled PowerShell launcher in a source checkout. Stop
  may end that task or the exact process tree started by the current Reader; it
  never searches for and terminates an unrelated Python process. Editable
  documents now use a virtualized, page-bounded series of visually continuous
  inline text editors, keeping blocks as an internal persistence/playback detail.
  The active paragraph can be edited whenever playback is stopped, with the
  existing revision-aware Save, Revert, Undo, and Redo behavior. Playback swaps
  the page to its read/highlight template, locking text for the duration. A new
  Play from cursor action sends the active WPF caret as the explicit UTF-16
  Reader cursor; normal Play continues to use the durable saved position.
- Reader workflow validation passed on 2026-07-29:
  - `py -3 -m pytest -q`: 394 passed; `py -3 -m ruff check .`, `git diff
    --check`, and .NET format verification passed;
  - `.NET Release` solution tests: 63 passed, including explicit-cursor precedence
    and safe bundled-launcher discovery; the solution build completed with zero
    warnings and zero errors;
  - `py -3 scripts\check_desktop_reader.py --require-windows-integration`
    passed live paging/editing/resume, shared Windows audio, clipboard/hotkey/tray
    integration, portable packaging, WPF rendering, and the new source contract;
  - live Windows UI Automation confirmed stopped/running service state, owned
    process-tree start, port release on Stop, and a successful restart. It placed
    a zero-length selection at character offset 5, observed Play from cursor enter
    Playing, confirmed the editor was absent while playing, and returned to
    Stopped. A temporary local edit enabled Save/Revert and Revert restored the
    original text without persisting a mutation. The 98-block article exposed
    only five currently materialized inline editors plus the next-page control;
    the old block-edit and return controls were absent. The healthy service and
    responsive Reader remain running;
  - no product direction, architecture, security model, licensing model, cloud
    dependency, or data contract changed. The user-owned `models/MANIFEST.json`
    remains excluded.
- Completed post-Milestone 9 playback-resume reliability follow-up: a live
  98-block article exposed that a durable cursor saved exactly at the end of a
  non-final block was not normalized to the first block actually included in
  the next stream window. Building the `started` event then referenced a block
  outside that window, raised an uncaught `ReaderValidationError`, leaked the
  active-stream metric, and caused the desktop to report an incomplete
  WebSocket close handshake. Stream windows now expose the first included
  slice as their start cursor, and an exhausted start block no longer consumes
  the bounded block quota. The complete stream startup path is inside the
  existing failure/cancellation cleanup boundary, and backend/internal stream
  failures write a structured exception before returning a typed Reader error.
  A desktop Stop may close its receive side before the server can return the
  terminal `cancelled` event; that terminal send is now best effort,
  cancellation is checked again after background synthesis returns, and metrics
  no longer count the same stream as both cancelled and failed. The real voice
  playback smoke now adds all local package roots itself instead of requiring a
  manually supplied `PYTHONPATH`.
- Playback-resume validation passed on 2026-07-29:
  - `py -3 -m pytest -q`: 394 passed; `py -3 -m ruff check .` and `git diff
    --check` passed;
  - focused window and WebSocket regression tests prove that a cursor at the
    exact end of one block resumes at offset zero of the next block;
  - the isolated Windows real-voice Reader smoke completed through NAudio with
    `vits-piper-en_US-lessac-high`;
  - the original article, original schema-4 database, stored block-26 boundary
    cursor, and real Lessac voice produced a `started` event at block 27 plus
    PCM frames, then cancelled cleanly with zero active or failed streams. The
    WPF Reader subsequently resumed that same document through its Play action
    and returned to Stopped through its Stop action without faulting. The
    healthy local service and responsive WPF Reader remain running;
  - no product, architecture, security, dependency, or licensing direction
    changed. The user-owned `models/MANIFEST.json` remains excluded.
- Completed post-Milestone 9 reliability follow-up: a real desktop run exposed
  that the two-second browser-handoff poll alone exhausted the default
  30-request-per-minute localhost limit. The bounded fix reduces normal polling
  to ten seconds, backs off for one minute after a typed rate-limit response,
  and contains expected clipboard/network failures so WPF event handlers do
  not terminate the process. Clipboard document creation now rejects identical
  content first and offers explicit Open existing, Create anyway, and Cancel
  choices instead of silently allowing duplicates. The newer accidental local
  duplicate was archived through the reversible Reader state API after all
  validation passed; the older Inbox copy remains canonical. The rebuilt Reader
  is running against the healthy schema-4 local service with a responsive WPF
  window.
- Post-Milestone 9 reliability validation passed on 2026-07-27:
  - `py -3 -m pytest -q`: 392 passed; `py -3 -m ruff check .`, `git diff
    --check`, and .NET format verification passed;
  - `.NET Release` solution tests: 59 passed; the full WPF solution build
    completed with zero warnings and zero errors;
  - `py -3 scripts\check_desktop_reader.py --require-windows-integration`
    passed live Reader behavior, privacy-safe clipboard/Windows integration,
    audio, self-contained packaging, WPF rendering, and source checks for the
    duplicate-choice and rate-limit protections.
- Completed post-Milestone 9 desktop usability follow-up: a real 98-block,
  16,971-character clipboard article exposed that the stopped editable view
  showed only the first block even though playback correctly switched to the
  paged reading view. The bounded fix makes the existing virtualized 64-block
  reading page the default before playback, adds explicit selected-block edit
  and return-to-document actions, and keeps revision-aware block edits plus
  durable Undo/Redo intact. Document titles gain a revision-aware Rename flow,
  and visible mojibake in the Import UI is corrected without changing import
  contracts or dependencies.
- Post-Milestone 9 desktop usability validation passed on 2026-07-27:
  - `py -3 -m pytest -q`: 392 passed; `py -3 -m ruff check .`, `git diff
    --check`, and .NET format verification passed;
  - `.NET Release` solution tests: 61 passed; focused application tests cover
    later-block editing and row-versioned title updates; the WPF application
    build completed with zero warnings and zero errors;
  - `py -3 scripts\check_desktop_reader.py --require-windows-integration`
    passed live Reader behavior, clipboard privacy, audio, packaging, WPF
    rendering, and the full-document/title source contract;
  - live Windows UI Automation selected the reported 98-block article and
    confirmed enabled Rename, Edit selected block, and Next page controls. The
    edit action entered and returned from the first block without mutation, the
    virtualized list materialized only the currently visible rows, and the
    rebuilt Reader remained responsive against the healthy schema-4 service.
- Reader Milestone 9 implementation details:
  - the protected browser-capture API accepts bounded structured blocks and
    HTTP(S)-only source metadata, writes through the Reader application layer,
    detects/reuses existing captures, and can idempotently add an active queue
    item plus a persistent desktop-open request;
  - SQLite migration `004_browser_handoffs.sql` adds durable, one-per-document
    pending handoffs. The desktop polls them only while connected, defers while
    playback or unsaved edits make opening unsafe, and acknowledges only after
    the document is loaded;
  - the canonical extension exposes Save Selection, Save Page, Add Page to
    Queue, and Open Page in Desktop. It preserves heading/paragraph/list/quote/
    code structure and page source metadata while keeping raw capture text
    transient and retaining the existing direct WebSocket playback path;
  - the popup now reports protected Reader browser-capture and desktop-handoff
    readiness alongside the existing service onboarding state;
  - Reader contracts, source validators, the isolated live browser-library
    flow, local-reader bundle validation, release checks, and the Windows bundle
    include the new integration;
  - the MIT-licensed `Kajsing/Chrome-TTS-plugin` prototype was evaluated at
    `6e56ceb95d6e675e0d9d6139c97578f9be47372c`. Its brittle node-index ranges,
    whole-ancestor highlighting, missing DOM-mutation recovery, and broad
    manifest were not superior to the current implementation, so no code was
    transplanted. README commit `2c547fe` and the repository description now
    mark it superseded and point to `apps/chrome_extension/` here.
- Reader Milestone 9 validation passed on 2026-07-27:
  - `py -3 -m pytest -q`: 391 passed; `py -3 -m ruff check .`, `git diff
    --check`, and .NET format verification passed;
  - `.NET Release` solution tests: 57 passed; the full WPF solution build
    completed with zero warnings and zero errors;
  - `py -3 scripts\check_reader_contracts.py` validated 13 fixtures;
    `py -3 scripts\check_security_defaults.py` passed;
  - strict extension JavaScript syntax, onboarding, the existing 2,963-word
    direct reader flow, and the new isolated library flow passed. The latter
    proves token/origin enforcement, structured persistence, desktop library
    visibility, durable queue/open handoff, repeat-action idempotence, and
    filesystem-source rejection;
  - `py -3 scripts\check_desktop_reader.py --require-windows-integration`
    passed live Reader regressions, Windows audio/integration, portable
    packaging, WPF rendering, and source-level browser-handoff wiring;
  - the complete `scripts\release_check.py` passed with strict JavaScript
    syntax, extension and Windows bundle packaging/bootstrap/install, both
    Windows launcher smokes, and the new library-flow gate. Its optional
    branded-Chrome MV3 check remained skip-aware because that browser ignored
    command-line unpacked-extension registration; no required check failed.
- Reader Milestone 9 assumptions and deviations:
  - browser saves reuse a content-identical existing Reader document from the
    same source URL by default, so repeated Save, Queue, and Open actions remain
    useful without discarding distinct source metadata; callers can explicitly
    disable reuse or request an allowed duplicate;
  - the old repository is marked superseded rather than archived, preserving a
    reversible historical reference while making the supported product clear;
  - no new dependency, filesystem-write authority, deployment exposure, or
    security-model change was introduced. The user-owned
    `models/MANIFEST.json` installation-state change remains excluded.
  - the first real post-milestone launch exposed one pre-release Milestone 7
    migration checksum whose SQL predates three database-level rule bounds.
    Migration loading now accepts only that exact known predecessor checksum;
    service/API validation already enforces the canonical bounds, arbitrary
    checksum drift remains fail-closed, and a regression test upgrades the
    legacy schema through the current browser-handoff migration.
- Reader Milestone 8 implementation details:
  - migration `003_search_and_exports.sql` adds persistent export jobs. The
    SQLite repository maintains an optional FTS5 title/source/content index and
    automatically falls back to escaped `LIKE` search when FTS5 is unavailable;
  - library state filters and reversible Inbox/Reading/Finished/Archive actions,
    bookmark management, queue reorder, transactional activation/advance, and
    optional desktop auto-advance complete the daily library loop. Backend
    transactions enforce at most one playing queue item;
  - the saved reading queue is the design-approved playlist form for beta; it
    persists order across restarts and feeds both auto-advance and batch export;
  - service-owned WAV export jobs persist independently of the desktop, recover
    queued/interrupted work on service restart, apply current speech rules,
    synthesize bounded blocks, verify PCM format consistency, insert configured
    pauses, report progress, and support cancellation;
  - temporary files are removed after cancellation or failure. Finalization is
    atomic and refuses overwrite unless the request explicitly allows it;
    sanitized Windows-safe basenames remain inside the configured export root;
  - the WPF workflow dialog manages queue items, bookmarks, current-document and
    queue exports, live progress, and cancellation. Reader diagnostics expose
    integrity, schema/search readiness, aggregate document/queue/lease/export
    states, and low-sensitivity metrics without titles, text, or private paths.
- Reader Milestone 8 validation passed on 2026-07-27:
  - `py -3 -m pytest -q`: 388 passed; the focused Reader/config/API suite passed
    98 tests; `py -3 -m ruff check .` passed;
  - `.NET Release` solution tests: 57 passed across Client, Application, and
    Windows projects; app build and `dotnet format --verify-no-changes` passed;
  - `py -3 scripts\check_reader_contracts.py` validated 10 fixtures;
    `py -3 scripts\check_security_defaults.py`, Windows bundle bootstrap, and
    `git diff --check` passed;
  - `py -3 scripts\check_desktop_reader.py --require-windows-integration`
    passed live paging/edit/stream/resume, clipboard, structured import, speech
    rules, Windows audio/integration, portable packaging, WPF rendering, and
    source-level Milestone 8 workflow wiring;
  - API/repository tests cover FTS and fallback search, durable queue ordering,
    atomic advance, export recovery, cancellation cleanup, filename confinement,
    batch export, diagnostics, and WAV decoding through Python's standard
    `wave` reader.
- Reader Milestone 8 assumptions and deviations:
  - the existing saved queue satisfies the normative “playlists or saved
    queues” choice; separate named playlists were not added;
  - beta exports only WAV through the existing synthesis stack. No external
    encoder, cloud service, paid dependency, or security-model change was
    introduced;
  - no product decision was required. The existing uncommitted
    `models/MANIFEST.json` installation-state change remains user-owned and is
    excluded from the milestone commit.
- Reader Milestone 7 implementation details:
  - migration `002_rules_and_profiles.sql` adds durable rule sets, six speech-rule
    types, scope/stage/priority/filter metadata, row and global rule versions,
    idempotent import records, and the future voice-profile storage boundary;
  - `packages/speech_rules` applies literal and regex replacement, skip, spell,
    pause, and preserved phoneme rules in deterministic order without changing
    stored source text. Generated speech retains per-character source mapping;
  - untrusted regex uses `regex` 2026.7.19 with hard per-operation timeouts,
    a 250 ms block budget, bounded patterns, replacements, matches, output, and
    a 4,096-character interactive preview limit. The dependency's
    Apache-2.0/CNRI-Python license expression is recorded in
    `THIRD_PARTY_NOTICES.md`;
  - protected CRUD, preview/trace, JSON import/export, version, and capability
    contracts are implemented. Import is dry-run-first and byte-hash idempotent;
    unknown provider rules and fields survive as bounded disabled metadata;
  - Reader playback composes speech-rule mapping with the existing language
    normalizer, advances across fully skipped blocks without audio, emits typed
    rule warnings, carries the current rules version, and applies pause hints;
  - the WPF app now manages rule sets and rules, previews source-mapped output,
    disables a warned rule directly, imports/exports the open Reader JSON format,
    and creates a prefilled document/language-scoped rule from selected text;
  - Windows source launchers and bundles include `speech_rules`. The unresolved
    repository-license choice still prevents claiming external-distribution
    readiness but does not block Milestones 8 or 9.
- Reader Milestone 7 validation passed on 2026-07-27:
  - the milestone Python suite passed after the final correction as part of the
    378-test full suite; the earlier isolated milestone run covered 334 tests;
  - `py -3 -m pytest -q`: 378 passed; `py -3 -m ruff check .` passed;
  - `.NET Release` solution tests: 56 passed; build and `dotnet format
    --verify-no-changes` passed with zero warnings/errors;
  - `py -3 scripts\check_reader_contracts.py` validated 8 fixtures and
    `git diff --check` passed;
  - `py -3 scripts\check_desktop_reader.py --require-windows-integration
    --skip-build` passed live rule mapping, a catastrophic-regex timeout,
    paging/edit/stream/resume, clipboard, import, WASAPI, Windows integration,
    portable packaging, and packaged WPF rendering;
  - `py -3 scripts\check_windows_bundle_bootstrap.py` and
    `py -3 scripts\check_security_defaults.py` passed;
  - the required regex-focused security review found zero open Milestone 7
    findings. Auth/origin controls remain inherited by all Reader routes,
    preview content is absent from logs, validation errors are sanitized, and
    adversarial timeout/expansion/match/response-amplification cases are tested.
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

- Stop at the completed Reader Workstation Milestone 9 boundary. If the user
  explicitly continues, start Milestone 10 from
  `design_doc/reader_workstation_design_v1.md`: add bounded, layout-aware PDF
  text extraction, page/block coordinates, reading order, repeated
  header/footer handling, page-range preview, and scanned-page warnings.
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
python3 scripts/check_extension_library_flow.py
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
4. Resume at Reader Workstation Milestone 10 only after the user explicitly
   asks to continue. Add PDF text extraction and preview while preserving the
   completed browser/library, import, rule, queue, export, clipboard, and
   playback behavior.
5. If a future milestone changes deployment exposure, model catalog trust, or
   extension distribution, update the threat model and rerun a scoped security
   pass before relying on the old v1 security evidence.
6. Run the relevant validation commands before handing off and update this file
   again with the new status.
