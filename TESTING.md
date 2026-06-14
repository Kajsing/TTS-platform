# Testing

Current automated coverage focuses on the service, core foundation, Phase 7
backend-realism work, and early v1 model-management helpers:

- configuration loading and environment overrides
- voice manifest parsing
- voice registry behavior
- text normalization and segmentation
- `/v1/health`, `/v1/voices`, and `/v1/tts`
- `sherpa-onnx` development synthesis behavior
- API error payload shape
- application bootstrap smoke test
- bearer-token enforcement
- invalid bearer-format rejection
- token rotation
- origin filtering
- security allowed-origin config validation for explicit origins and rejection
  of wildcard, null, path-bearing, and unsupported-scheme entries
- config example security-default verification for loopback binding, token auth,
  empty origin allow-list, rate limits, metrics, long stream limits, local CPU
  backend defaults, and ignored token/model artifacts
- CLI `extension-allow-origin` helper coverage for first-run Chrome onboarding
- rate limiting
- job creation, status polling, and queued-job cancellation
- running-job cancellation that remains terminal even when backend interruption is best-effort
- job result retrieval and retention cleanup
- WebSocket auth handling
- WebSocket auth via either bearer headers or the browser-friendly `start` event token field
- PCM streaming and `done` events
- WebSocket long-text streaming above the shorter HTTP/job request limit
- WebSocket reader progress metadata and `start_text_chunk_index` resume anchor
- extension resume wiring for page playback
- extension page-capture metadata wiring for long-page character counts,
  readable block counts, extraction source, and truncation status
- extension page-structure metadata wiring for heading/body/list counts and
  short heading preservation in captured page text
- extension next-section wiring that re-extracts the active tab from the next
  heading-backed section or the first known uncaptured section after truncation
  without storing heading text
- extension continue-page wiring that re-extracts the active tab from the next
  text character offset after a truncated capture without storing raw page text
- extension automatic continuation wiring that starts the next truncated page
  segment from that text character offset after normal stream completion
- extension previous-section wiring that re-extracts the active tab from the
  previous heading-backed section without storing heading text
- extension stop/restart recovery wiring, including persisted interrupted
  state when popup/background state is restored without an offscreen document
- extension manifest policy checks that keep service host permissions limited
  to localhost while leaving page access in the content-script declaration
- extension privacy-boundary checks that block content-script service calls,
  popup/offscreen storage use, broad browser persistence APIs, and non-offscreen
  WebSocket creation
- stream cancellation and streaming metrics updates
- cancellation observability for jobs, streams, and synthesis attempts
- observability snapshots and request ids
- low-sensitivity HTTP request logging that omits query strings, auth tokens,
  and raw request text while replacing unsafe client-provided request ids
- structural audio regression checks
- rate-sensitive audio regression behavior
- backend runtime config for `stub`, `auto`, and `real` modes
- backend readiness and health-status reporting
- fake `sherpa_onnx` runtime coverage for sync, async job, and streaming paths
- callback-driven fake `sherpa_onnx` runtime coverage for incremental streaming
  and real-runtime cancellation callback behavior
- chunk-plan generation and synthesis routing
- model catalog listing summaries and warnings, local artifact install, manifest
  update, remote catalog relative-artifact download, temporary-file artifact
  staging before checksum/extraction, safe zip and tar extraction, install progress
  metadata, overwrite refusal, checksum-required-by-default install behavior
  with an explicit trusted-local override, default `models/catalog.json`
  discovery with friendly missing-file guidance,
  install-and-activate first-run shortcut, offline manifest model listing,
  default-voice activation, read-only real-backend readiness diagnostics with
  catalog-aware concrete install next steps, and model removal
- local first-run setup helper behavior for config creation, token
  initialization, manifest/default-voice readiness reporting, default catalog
  detection, concrete model-install guidance, and `sherpa_onnx` runtime install
  guidance
- local service run command wiring for configured host/port/log level, explicit
  overrides, missing-config guidance, and loopback-only default binding
- Windows launcher structure, including repo-local `PYTHONPATH`, module CLI
  invocation, setup fallback, and PowerShell delegation from the CMD launcher
- Chrome extension popup setup-checklist, manifest-policy, and privacy-boundary
  wiring through the lightweight extension validator
- Chrome extension zip packaging with manifest at the archive root and
  POSIX-style relative asset paths, including `INSTALL.md` and manifest icon
  assets
- Windows local reader bundle packaging that includes the service source,
  Windows launchers, docs, config example, model manifest, extension source,
  model-readiness handoff guidance, and a validated extension zip while
  excluding local token/model artifacts
- Windows local install bootstrap script packaging that creates `.venv`,
  installs the local package, and runs `setup-local` without choosing a
  persistent service manager
- Windows local reader bundle bootstrap checks that safely extract the bundle,
  verify local token/model artifacts are absent, inspect model-readiness guide
  markers, inspect the embedded extension zip, and run catalog-aware
  `setup-local` from the extracted source paths
- Windows launcher setup-only checks that run the bundled PowerShell/CMD
  launchers far enough to create local config/token files without starting a
  long-lived service process
- Windows launcher foreground service smoke checks that start the bundled
  PowerShell/CMD launchers on reserved loopback ports, run public-contract
  smoke, and stop the process tree
- Windows bundle install checks that use the bundled install script when
  available before starting the installed `tts serve` entrypoint
- repo-native release check orchestration for ruff, pytest, security-default
  verification, v1-readiness verification, extension validation, extension
  package build, Windows bundle build, launcher setup/service-smoke checks, and
  Windows bundle bootstrap/install checks
- v1-readiness documentation checks that keep automated gates, manual gates,
  product choices, and known not-yet-automated items explicit
- release-check redaction for inline live-smoke bearer tokens in JSON summaries
- live smoke support for separate long WebSocket stream text, minimum stream
  text-chunk assertions, and release-check redaction of inline smoke text
- optional Chrome/MV3 browser smoke harness coverage that loads the extension
  in Chrome or Edge through DevTools Protocol when a browser is available,
  starts an isolated local service, opens a generated long article, verifies
  extension page capture, and starts page playback
- extension popup copy-command coverage for the `tts extension-allow-origin`
  first-run helper

Recommended extension checks:

- confirm the popup can load service health and voice discovery from the configured base URL
- confirm the setup checklist reflects service reachability, token state,
  allow-list command/snippet readiness, voice discovery, backend readiness,
  default voice loading, and health
- confirm the allow-list snippet matches the current extension origin
- verify the popup can copy the exact `tts extension-allow-origin ...` command
- verify selection playback on a normal web page
- verify stop and restart behavior after an active stream
- verify the popup still shows a sensible playback state after reopening it mid-stream
- verify the popup can copy the extension origin and allow-list snippet
- verify page playback prefers readable content over navigation-heavy boilerplate on a normal article page
- verify long page playback reports page-capture metadata and shows truncation
  when readable text reaches the configured character limit
- verify short headings are included in page playback and that `Page Capture`
  reports heading/body/list structure counts
- verify `Next Section` restarts page playback from a later heading-backed
  section, or from the first known uncaptured section after truncation, when
  one is available
- verify `Continue Page` restarts page playback after the previous truncated
  capture when no later heading-backed section is available
- verify normal page playback automatically starts the next segment after a
  truncated captured segment finishes
- verify `Previous Section` restarts page playback from an earlier
  heading-backed section when one is available

Run tests with:

```bash
python3 -m pytest -q
```

On Windows, use `py -3 -m pytest -q` when `python3` is unavailable.

Lint with:

```bash
python3 -m ruff check .
```

On Windows, use `py -3 -m ruff check .` when `python3` is unavailable.

Run the local release gate with:

```bash
python3 scripts/release_check.py
python3 scripts/release_check.py --node-executable <path-to-node> --require-js-syntax
```

On Windows, use `py -3 scripts/release_check.py` when `python3` is unavailable.
The release gate also verifies `docs/v1_readiness.md`, which separates
automated gates from manual live checks and unresolved product choices.
It starts a temporary first-run service on a loopback port and runs the local
public-contract smoke against that isolated config/token root.
It also creates a temporary local model artifact/catalog, verifies
catalog-list, relative-artifact download over a loopback HTTP catalog, install,
activate, read-only model readiness output, service smoke with the installed
voice, and remove.
It runs the bundled Windows launchers in setup-only mode when Windows launcher
executables are available, verifying direct first-run setup without choosing a
permanent service manager. On Windows, the same check also starts the bundled
PowerShell/CMD launchers as foreground services on reserved loopback ports,
runs public-contract smoke, and stops the launcher process trees.
It verifies the bundled Windows install script path when present by using it to
create `.venv`, install the local package, and run catalog-aware `setup-local`
before the installed foreground service smoke.
It verifies the Chrome extension onboarding contract by checking popup setup
controls, service health/voice discovery against a temporary service, and the
extension-origin allow-list snippet plus CLI helper behavior.
It verifies Chrome extension installability assets by checking local
`INSTALL.md` guidance and the manifest/action icon set.
It also verifies the long-page reader-flow contract and streams a generated
thousand-word article through the WebSocket service path. That reader-flow
contract includes previous/next section navigation, truncated-section
continuation, manual and automatic truncated text-offset continuation,
stop/restart recovery wiring, and the popup state fields used after reopening
the popup.
It runs a skip-aware Chrome/MV3 browser smoke that uses Chrome or Edge when a
compatible browser build can load unpacked extensions from automation. When the
local browser/MV3 environment cannot run the smoke, the gate reports a skipped
smoke rather than failing the offline release gate; use `--require-browser` on
the smoke script when strict browser evidence is needed. Branded Chrome 137+ may
ignore `--load-extension`; for strict automated evidence, pass Chrome for
Testing or Chromium with `--browser-executable`.
If the service is already running, include the public-contract smoke path:

```bash
python3 scripts/release_check.py --live-smoke --token-file config/token.txt
```

For a long-page reader smoke, use a separate repeated stream input so HTTP and
async job coverage stay within the shorter request limit while WebSocket
streaming exercises the long-text path:

```bash
python3 scripts/release_check.py --live-smoke --token-file config/token.txt --stream-text-repeat 200 --min-stream-text-chunks 2
```

Build the Windows local reader bundle directly with:

```bash
python3 scripts/package_windows_bundle.py
```

On Windows, use `py -3 scripts/package_windows_bundle.py` when `python3` is
unavailable.
After extracting a bundle, bootstrap the local virtual environment with:

```powershell
.\scripts\windows\install_local.ps1
```

Use `.\scripts\windows\install_local.ps1 -InstallRealRuntime` when the extracted
bundle should install the optional `.[real]` runtime dependencies during the
same bootstrap. Use `-NoDependencies` only for an already provisioned
environment.

Check the built bundle's first-run bootstrap path with:

```bash
python3 scripts/check_windows_bundle_bootstrap.py --bundle dist/windows/tts-platform-local-reader.zip
```

Check the built bundle's temporary virtualenv install/start path with:

```bash
python3 scripts/check_windows_bundle_install.py --bundle dist/windows/tts-platform-local-reader.zip
```

Use `--install-real-runtime` on this check only when the test machine should
exercise the optional `.[real]` install path; the default gate keeps that
download-heavy path opt-in. Use `--no-dependencies` only when checking a
pre-provisioned environment that should skip base dependency installation.

Check the built bundle's PowerShell/CMD launcher setup and foreground service
smoke paths with:

```bash
python3 scripts/check_windows_launchers.py --bundle dist/windows/tts-platform-local-reader.zip
```

Check the source first-run service bootstrap path directly with:

```bash
python3 scripts/check_local_service_bootstrap.py
```

Check the local model-management flow directly with:

```bash
python3 scripts/check_model_management_flow.py
```

Check real-backend readiness for the configured default voice with:

```bash
tts model-check
```

Generate and verify a local real English voice demo WAV with:

```bash
python3 -m pip install -e ".[real]"
python3 scripts/demo_real_voice.py --python-executable .venv/Scripts/python.exe
```

The demo script installs the default catalog model into ignored
`dist/real-demo`, runs `smoke_service.py` with `--token-file`, writes
`dist/real-demo/lessac-demo.wav`, and stops its temporary service process.
The `real` extra installs `sherpa-onnx` plus `numpy` for the real async and
stream callback paths.

Check the Chrome extension onboarding contract directly with:

```bash
python3 scripts/check_extension_onboarding.py
```

Check the Chrome extension long-page reader-flow contract directly with:

```bash
python3 scripts/check_extension_reader_flow.py
```

Check the optional Chrome/MV3 browser smoke directly with:

```bash
python3 scripts/check_chrome_extension_smoke.py
```

For strict browser evidence on a machine with a compatible browser build:

```bash
python3 scripts/check_chrome_extension_smoke.py --require-browser --headed
```

If the installed browser ignores command-line unpacked extension loading, pass a
Chrome for Testing or Chromium executable:

```bash
python3 scripts/check_chrome_extension_smoke.py --require-browser --browser-executable <path-to-browser>
```

CLI example:

```bash
tts health
tts list-voices
tts save "Hello world" --out out.wav
tts job-status <job-id> --token "$TTS_PLATFORM_TOKEN"
python3 scripts/benchmark.py --mode stream --token "$TTS_PLATFORM_TOKEN"
```

Public-contract smoke test after the service is running:

```bash
python3 scripts/smoke_service.py --token "$TTS_PLATFORM_TOKEN"
python3 scripts/smoke_service.py --token-file config/token.txt
python3 scripts/smoke_service.py --token-file config/token.txt --stream-text-repeat 200 --min-stream-text-chunks 2
```

For lightweight extension checks:

```bash
python3 scripts/check_extension.py
python3 scripts/check_extension.py --require-js-syntax
python3 scripts/check_extension.py --node-executable <path-to-node> --require-js-syntax
python3 scripts/check_chrome_extension_smoke.py
python3 scripts/package_extension.py
python3 scripts/package_windows_bundle.py
node --check apps/chrome_extension/src/background.js
node --check apps/chrome_extension/src/popup.js
node --check apps/chrome_extension/offscreen/offscreen.js
```

On Windows, run the Python check as `py -3 scripts/check_extension.py` when
`python3` is unavailable. `scripts/check_extension.py` also honors
`TTS_PLATFORM_NODE=<path-to-node>` when Node.js is installed outside `PATH`.
