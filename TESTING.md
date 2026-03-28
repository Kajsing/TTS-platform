# Testing

Current automated coverage focuses on the phase 1 foundation:

- configuration loading and environment overrides
- voice manifest parsing
- voice registry behavior
- `sherpa-onnx` stub contract behavior
- API error payload shape
- application bootstrap smoke test

Run tests with:

```bash
python3 -m pytest -q
```

Lint with:

```bash
python3 -m ruff check .
```
