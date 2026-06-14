# Documentation

This file is the live status log and shared memory for future Codex loops.

## Current Status

- Date: 2026-06-14
- Workflow status: `docs/codex/` is the Codex source of truth for project spec, execution order, operating rules, and resume context. After a successful run, Codex should commit and push the completed slice by default.
- Project status: Phases 1 through 7 are complete at the repository behavior and
  test-contract level. The active long-horizon implementation target is now the
  v1 local reader flow: robust long-document orchestration, model-management
  UX, Windows-friendly service setup, and Chrome extension installability.
- Runtime context: the intended end platform is Windows. Codex sessions may run from Windows PowerShell or WSL, so commands and docs should avoid assuming only one shell.
- Current loop target: make the Chrome reader's source-tab guard visible in the
  popup before the operator clicks a manual page action.
- Current loop result: background `get-state` responses now add non-persisted
  `sourceTabActive` and `sourceTabMessage` fields for page playback state, and
  the popup uses them to show a `Source Tab` playback-state line and disable
  manual page resume/continue/section actions while another tab is active.
- Validation status for the current loop:
  - `py -3 scripts\check_extension.py` passed; JavaScript syntax parsing
    remains skip-aware because Node.js is not on `PATH`.
  - `py -3 scripts\check_extension_reader_flow.py` passed, including
    `source_tab_guard`, `source_tab_status`, and generated long-article
    WebSocket smoke with 145 stream text chunks.
  - `py -3 -m pytest apps\tts_service\tests\test_extension_reader_flow_check.py -q`
    passed with 3 tests.
  - `py -3 scripts\check_v1_readiness.py` passed.
  - `py -3 -m ruff check .` passed.
  - `py -3 -m pytest -q` passed with 229 tests.
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
- This Codex memory structure is now in place:
  - `docs/codex/Prompt.md`
  - `docs/codex/Plan.md`
  - `docs/codex/Implement.md`
  - `docs/codex/Documentation.md`

## What Is Next

- Continue the Post-Phase 7 v1 reader track from `Plan.md`.
- Continue from the v1-readiness audit: either automate another listed manual
  gate or take the next reader-flow/product slice from `Plan.md`.
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
python3 scripts/release_check.py --windows-bundle-local-reader-check
python3 scripts/release_check.py --live-smoke --token-file config/token.txt
python3 scripts/release_check.py --real-voice-demo --install-real-runtime
python3 scripts/release_check.py --require-browser --browser-executable <path-to-browser>
python3 scripts/package_windows_bundle.py
python3 scripts/check_local_reader_bundle.py
python3 scripts/check_v1_readiness.py
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
  after a segment finishes, but still lacks a full named reader-mode outline.
- The Windows bundle still requires the operator to run the bundled install
  script, load the Chrome extension, and configure the service allow-list after
  extraction. The virtualenv install/start path is now covered by an automated
  temp-venv smoke, and launcher setup-only plus foreground service smoke
  execution is covered for PowerShell/CMD.
- Persistent Windows auto-start/service-manager installation remains an explicit
  later product choice.
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

## Resume Instructions For The Next Codex Loop

1. Open `docs/codex/Prompt.md`, `docs/codex/Plan.md`, and `docs/codex/Implement.md`.
2. Check this file for current status and any newly recorded blockers.
3. Start with the Post-Phase 7 v1 reader track unless this file records a
   deliberate reorder.
4. Keep the next diff narrowly scoped to that milestone.
5. Run the milestone validation commands before claiming completion.
6. Update this file again before handing off.
