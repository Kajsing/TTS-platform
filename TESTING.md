# Testing

Current automated coverage focuses on the phase 3 foundation:

- configuration loading and environment overrides
- voice manifest parsing
- voice registry behavior
- text normalization and segmentation
- `/v1/health`, `/v1/voices`, and `/v1/tts`
- `sherpa-onnx` development synthesis behavior
- API error payload shape
- application bootstrap smoke test
- bearer-token enforcement
- origin filtering
- rate limiting
- job creation, status polling, and queued-job cancellation

Run tests with:

```bash
python3 -m pytest -q
```

Lint with:

```bash
python3 -m ruff check .
```
