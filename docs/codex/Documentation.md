# Documentation

This file is the live status log and shared memory for future Codex loops.

## Current Status

- Date: 2026-06-13
- Workflow status: `docs/codex/` is the Codex source of truth for project spec, execution order, operating rules, and resume context. After a successful run, Codex should commit and push the completed slice by default.
- Project status: Phases 1 through 7 are complete at the repository behavior and
  test-contract level. The active long-horizon implementation target is now the
  v1 local reader flow: robust long-document orchestration, model-management
  UX, Windows-friendly service setup, and Chrome extension installability.
- Runtime context: the intended end platform is Windows. Codex sessions may run from Windows PowerShell or WSL, so commands and docs should avoid assuming only one shell.
- Current loop result: The extension-onboarding readiness slice adds a
  deterministic popup/service contract check. It verifies popup setup controls,
  Chrome-extension origin allow-list snippet compatibility, and health/voice
  discovery against a temporary local service without requiring a full Chrome
  MV3 browser harness.
- Validation status for the current loop:
  - `py -3 scripts/check_extension_onboarding.py` passed.
  - `py -3 -m pytest apps\tts_service\tests\test_extension_onboarding_check.py apps\tts_service\tests\test_release_check.py apps\tts_service\tests\test_package_windows_bundle.py apps\tts_service\tests\test_check_extension.py -q` passed with 9 tests.
  - Targeted `py -3 -m ruff check ...` passed.
  - `py -3 scripts/check_v1_readiness.py` passed.
  - `py -3 -m ruff check .` passed.
  - `py -3 -m pytest -q` passed with 134 tests.
  - `py -3 scripts/release_check.py` passed, including
    `extension_onboarding`.
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
  artifact install with optional checksum verification, safe zip extraction
  against absolute paths, drive-qualified paths, and traversal entries, manifest
  update, default voice activation in `config/config.toml`, and model removal.
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
  - `scripts/check_extension.py` now validates the structural resume wiring even
    when `node` is not installed.
- V1 model-management UX has started:
  - `tts model-install --activate` updates the manifest and `config/config.toml`
    default voice in one command.
  - model install JSON output now reports installed file count, checksum
    verification status, warnings for missing checksums, and next steps.
  - `tts catalog-list` now reports catalog counts, model summaries, duplicate
    or incomplete-entry warnings, and install next-step guidance.
  - `tts model-install` now emits progress status lines to stderr and includes
    structured `install_steps` in its JSON stdout result.
  - `tts model-remove` now reports whether the removed model id is still
    configured as `[tts].default_voice`, with next-step guidance to activate
    another voice before service restart.
  - `scripts/check_model_management_flow.py` now verifies local catalog-list,
    install, activate, service smoke with the installed voice, and remove using
    a generated local artifact and temp repo root.
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
  - `scripts/package_windows_bundle.py` builds a Windows-friendly local reader
    bundle with service/core source, Windows launchers, config example, docs,
    Chrome extension source, and a validated extension zip.
  - The Windows bundle intentionally excludes `config/token.txt` and installed
    model files under `models/voices/`.
- Chrome extension onboarding has started:
  - the popup now includes a setup checklist for service reachability, saved
    token state, origin snippet readiness, voice discovery, and health status.
  - `scripts/check_extension.py` now validates setup-checklist wiring along
    with manifest, asset, and resume wiring.
  - `scripts/check_extension_onboarding.py` now validates the popup onboarding
    surface, config-loadable Chrome extension origin snippet, and service
    health/voice snapshot used by the popup.
  - `scripts/package_extension.py` now builds a validated local extension zip
    at `dist/chrome_extension/tts-platform-prototype.zip` by default.
  - the extension manifest no longer requests `<all_urls>` in
    `host_permissions`; service host permissions are limited to localhost, while
    page access remains in the declared content script.
  - `scripts/check_extension.py` now validates extension manifest policy and
    privacy/layering boundaries, including blocking content-script service
    calls, popup/offscreen storage use, broad browser persistence APIs, and
    non-offscreen WebSocket creation.
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
    checks the embedded extension zip, and runs `setup-local` from the extracted
    source paths.
  - `scripts/release_check.py` now runs the Windows bundle bootstrap check after
    building the bundle.
  - `scripts/check_local_service_bootstrap.py` now starts a temp first-run
    loopback service and runs public-contract smoke without repo-local config
    or token side effects.
  - `scripts/release_check.py` now runs local service bootstrap and
    model-management flow smoke checks as deterministic offline readiness gates.
  - `scripts/release_check.py` now runs extension onboarding contract smoke as
    a deterministic local gate before extension packaging.
  - HTTP request logs now keep only low-sensitivity metadata: method, path
    without query string, status, duration, outcome, and request id.
  - Client-provided `X-Request-ID` values are reused only when they are short,
    simple identifiers and are not bearer-shaped or equal to the current auth
    token; unsafe values are replaced with server-generated ids.
- This Codex memory structure is now in place:
  - `docs/codex/Prompt.md`
  - `docs/codex/Plan.md`
  - `docs/codex/Implement.md`
  - `docs/codex/Documentation.md`

## What Is Next

- Continue the Post-Phase 7 v1 reader track from `Plan.md`.
- Continue from the v1-readiness audit: either automate a listed manual gate or
  take the next reader-flow/product slice from `Plan.md`.
- Leave permanent Windows service manager or auto-start install as an explicit
  later product choice.

## Decisions Made And Why

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
- First-run model setup should prefer one clear local command where possible:
  `tts model-install <id> --catalog <catalog> --activate`.
- Model-management CLI stdout should remain structured JSON for automation; any
  human progress chatter belongs on stderr.
- First-run setup may create local config and token files, but should not choose
  a Windows service manager or persistence mechanism until that product
  direction is explicit.
- Installed CLI service startup should prefer `tts serve`; `scripts/dev_run.py`
  remains a development convenience.
- Windows launcher scripts are acceptable packaging progress without choosing a
  persistent service mechanism. Do not silently choose NSSM, Task Scheduler,
  pywin32, or startup-folder auto-run without an explicit product decision.
- The Windows local reader bundle is a source handoff package, not a persistent
  service-manager installer. It moves installability forward while preserving
  the explicit later choice around NSSM, Task Scheduler, pywin32, or auto-start.
- Extension onboarding should expose readiness state in the popup, while
  browser-specific behavior remains inside `apps/chrome_extension/`.
- Extension zip packaging is local handoff/installability only; Chrome Web Store
  signing or publishing is out of scope until explicitly chosen.
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
- This loop intentionally reordered one v1-enabling model-management slice
  ahead of Phase 7 Milestone 3 because the user restated the product goal as a
  local server plus Chrome reader for long web content; a usable voice install
  path is a prerequisite for that end state.

## Commands To Run And Smoke Test

Baseline validation:

```bash
python3 -m pytest -q
python3 -m ruff check .
python3 scripts/release_check.py
python3 scripts/release_check.py --live-smoke --token-file config/token.txt
python3 scripts/package_windows_bundle.py
python3 scripts/check_v1_readiness.py
python3 scripts/check_windows_bundle_bootstrap.py --bundle dist/windows/tts-platform-local-reader.zip
```

First-run setup:

```bash
tts setup-local
```

Service start:

```bash
tts serve
python3 scripts/dev_run.py
scripts/windows/run_service.cmd
```

Public-contract smoke commands after the service is running:

```bash
tts health
tts list-voices
tts save "Hello world" --out out.wav --token "$TTS_PLATFORM_TOKEN"
tts stream "Hello world" --out stream.wav --token "$TTS_PLATFORM_TOKEN"
tts catalog-list --catalog ./models/catalog.json
tts model-install <model-id> --catalog ./models/catalog.json
tts model-activate <model-id>
tts model-remove <model-id>
python3 scripts/check_model_management_flow.py
python3 scripts/check_extension_onboarding.py
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
- Long page playback now has a larger WebSocket text limit, stream progress
  metadata, a basic popup resume action, and page-capture metadata/truncation
  visibility. It now preserves short headings and reports structure counts, but
  still lacks a full named reader-mode outline.
- The Windows bundle still requires manual virtualenv setup, Chrome extension
  loading, and service allow-list configuration after extraction.
- Persistent Windows auto-start/service-manager installation remains an explicit
  later product choice.
- The browser prototype still depends on manual Chrome loading and manual allow-list setup.
- There is still no full automated MV3 test harness in the repository.
- `python3 scripts/check_extension.py` still cannot perform JavaScript syntax checks in this environment because `node` is not installed.

## Resume Instructions For The Next Codex Loop

1. Open `docs/codex/Prompt.md`, `docs/codex/Plan.md`, and `docs/codex/Implement.md`.
2. Check this file for current status and any newly recorded blockers.
3. Start with the Post-Phase 7 v1 reader track unless this file records a
   deliberate reorder.
4. Keep the next diff narrowly scoped to that milestone.
5. Run the milestone validation commands before claiming completion.
6. Update this file again before handing off.
