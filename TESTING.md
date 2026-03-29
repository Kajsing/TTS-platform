# Testing

Current automated coverage focuses on the service and core foundation through phase 6:

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

The Chrome extension prototype currently relies on manual verification in Chrome because there is not yet an automated MV3 test harness in the repository.

Run tests with:

```bash
python3 -m pytest -q
```

Lint with:

```bash
python3 -m ruff check .
```

CLI example:

```bash
tts health
tts list-voices
tts save "Hello world" --out out.wav
tts job-status <job-id> --token "$TTS_PLATFORM_TOKEN"
python3 scripts/benchmark.py --mode stream --token "$TTS_PLATFORM_TOKEN"
```
