# Testing

Current automated coverage focuses on the phase 5 foundation:

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
- PCM streaming and `done` events
- stream cancellation and streaming metrics updates
- observability snapshots and request ids
- structural audio regression checks
- rate-sensitive audio regression behavior

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
```
