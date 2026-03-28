# TTS Platform

Offline-first local text-to-speech platform designed around a stable core domain, a localhost API, and future browser playback integration.

## Current Status

Phase 1 is implemented:

- repository skeleton
- engineering guidance documents
- central configuration model
- voice registry
- backend interface
- `sherpa-onnx` backend stub

## Repository Layout

```text
apps/
  chrome_extension/
  tts_service/
config/
design_doc/
models/
packages/
  tts_core/
scripts/
```

## Quick Start

1. Create a virtual environment.
2. Install dependencies from [`pyproject.toml`](/home/kajsing/projects/TTS-platform/pyproject.toml).
3. Copy [`config/config.example.toml`](/home/kajsing/projects/TTS-platform/config/config.example.toml) to `config/config.toml`.
4. Run the tests.

Example:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
```

## Next Step

Phase 2 will add the first text pipeline pieces together with `/v1/health`, `/v1/voices`, and `/v1/tts`.
