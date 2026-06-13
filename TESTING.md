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
  heading-backed section without storing heading text
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
  update, safe zip extraction, install progress metadata, overwrite refusal,
  install-and-activate first-run shortcut, default-voice activation, and model
  removal
- local first-run setup helper behavior for config creation, token
  initialization, and manifest/default-voice readiness reporting
- local service run command wiring for configured host/port/log level, explicit
  overrides, missing-config guidance, and loopback-only default binding
- Windows launcher structure, including repo-local `PYTHONPATH`, module CLI
  invocation, setup fallback, and PowerShell delegation from the CMD launcher
- Chrome extension popup setup-checklist, manifest-policy, and privacy-boundary
  wiring through the lightweight extension validator
- Chrome extension zip packaging with manifest at the archive root and
  POSIX-style relative asset paths
- Windows local reader bundle packaging that includes the service source,
  Windows launchers, docs, config example, model manifest, extension source,
  and a validated extension zip while excluding local token/model artifacts
- Windows local reader bundle bootstrap checks that safely extract the bundle,
  verify local token/model artifacts are absent, inspect the embedded extension
  zip, and run `setup-local` from the extracted source paths
- repo-native release check orchestration for ruff, pytest, security-default
  verification, v1-readiness verification, extension validation, extension
  package build, Windows bundle build, and Windows bundle bootstrap check
- v1-readiness documentation checks that keep automated gates, manual gates,
  product choices, and known not-yet-automated items explicit
- release-check redaction for inline live-smoke bearer tokens in JSON summaries
- live smoke support for separate long WebSocket stream text, minimum stream
  text-chunk assertions, and release-check redaction of inline smoke text

The Chrome extension prototype currently relies on manual verification in Chrome because there is not yet an automated MV3 test harness in the repository.

Recommended extension checks:

- confirm the popup can load service health and voice discovery from the configured base URL
- confirm the setup checklist reflects service reachability, token state,
  origin snippet readiness, voice discovery, and health
- confirm the allow-list snippet matches the current extension origin
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
  section when one is available

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
```

On Windows, use `py -3 scripts/release_check.py` when `python3` is unavailable.
The release gate also verifies `docs/v1_readiness.md`, which separates
automated gates from manual live checks and unresolved product choices.
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
Check the built bundle's first-run bootstrap path with:

```bash
python3 scripts/check_windows_bundle_bootstrap.py --bundle dist/windows/tts-platform-local-reader.zip
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

For a lightweight extension syntax check when `node` is available:

```bash
python3 scripts/check_extension.py
python3 scripts/package_extension.py
python3 scripts/package_windows_bundle.py
node --check apps/chrome_extension/src/background.js
node --check apps/chrome_extension/src/popup.js
node --check apps/chrome_extension/offscreen/offscreen.js
```

On Windows, run the Python check as `py -3 scripts/check_extension.py` when
`python3` is unavailable.
