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
- rate limiting
- job creation, status polling, and queued-job cancellation
- job result retrieval and retention cleanup
- WebSocket auth handling
- WebSocket auth via either bearer headers or the browser-friendly `start` event token field
- PCM streaming and `done` events
- stream cancellation and streaming metrics updates
- observability snapshots and request ids
- structural audio regression checks
- rate-sensitive audio regression behavior
- backend runtime config for `stub`, `auto`, and `real` modes
- backend readiness and health-status reporting
- fake `sherpa_onnx` runtime coverage for sync, async job, and streaming paths
- chunk-plan generation and synthesis routing
- model catalog listing, local artifact install, manifest update, safe zip
  extraction, overwrite refusal, and model removal

The Chrome extension prototype currently relies on manual verification in Chrome because there is not yet an automated MV3 test harness in the repository.

Recommended extension checks:

- confirm the popup can load service health and voice discovery from the configured base URL
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
node --check apps/chrome_extension/src/background.js
node --check apps/chrome_extension/src/popup.js
node --check apps/chrome_extension/offscreen/offscreen.js
```

On Windows, run the Python check as `py -3 scripts/check_extension.py` when
`python3` is unavailable.
