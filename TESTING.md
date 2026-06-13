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
- stream cancellation and streaming metrics updates
- cancellation observability for jobs, streams, and synthesis attempts
- observability snapshots and request ids
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
- Chrome extension popup setup-checklist wiring through the lightweight
  extension validator
- Chrome extension zip packaging with manifest at the archive root and
  POSIX-style relative asset paths
- repo-native release check orchestration for ruff, pytest, extension
  validation, and extension package build

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
If the service is already running, include the public-contract smoke path:

```bash
python3 scripts/release_check.py --live-smoke --token-file config/token.txt
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
```

For a lightweight extension syntax check when `node` is available:

```bash
python3 scripts/check_extension.py
python3 scripts/package_extension.py
node --check apps/chrome_extension/src/background.js
node --check apps/chrome_extension/src/popup.js
node --check apps/chrome_extension/offscreen/offscreen.js
```

On Windows, run the Python check as `py -3 scripts/check_extension.py` when
`python3` is unavailable.
