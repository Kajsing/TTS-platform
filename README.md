# TTS Platform

Offline-first local text-to-speech platform designed around a stable core domain, a localhost API, and browser playback integration.

## Current Status

Phase 6 is implemented:

- repository skeleton
- engineering guidance documents
- central configuration model
- voice registry
- backend interface
- voice manifest loading
- text normalization and segmentation
- `/v1/health`
- `/v1/voices`
- `/v1/tts`
- WAV output via a deterministic development backend
- `/v1/tts/jobs`
- `/v1/tts/jobs/{job_id}/result`
- token auth for protected endpoints
- token rotation for local clients
- origin filtering and rate limiting
- `WS /v1/tts/stream`
- PCM16 streaming frames
- basic streaming metrics and stream cancellation
- structured request and synthesis observability
- `tts` CLI
- benchmark script
- audio regression tests
- Chrome MV3 prototype
- offscreen streamed playback
- extension popup, background worker, and content-script text capture
- browser-friendly WebSocket start-event auth for the localhost extension flow
- popup-side service status and voice discovery
- more deliberate extension-side rebuffering and playback state recovery
- heuristic page-text extraction and a lightweight extension validation script

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

## CLI Usage

Examples:

```bash
tts health
tts list-voices
tts save "Hello world" --out out.wav --token "$TTS_PLATFORM_TOKEN"
tts stream "Hello world" --out stream.wav --token "$TTS_PLATFORM_TOKEN"
tts job-status <job-id> --token "$TTS_PLATFORM_TOKEN"
```

Protected commands require `--token` or `TTS_PLATFORM_TOKEN`.

## Benchmarking

Examples:

```bash
python3 scripts/benchmark.py --token "$TTS_PLATFORM_TOKEN"
python3 scripts/benchmark.py --mode stream --token "$TTS_PLATFORM_TOKEN"
```

The benchmark script reports average latency, output duration, output size, and an approximate real-time factor.

## Chrome Extension Prototype

See [apps/chrome_extension/README.md](/home/kajsing/projects/TTS-platform/apps/chrome_extension/README.md) for setup and loading instructions.

The extension currently supports:

- speaking the current text selection
- speaking a trimmed snapshot of the current page
- offscreen playback of streamed PCM audio
- local storage of base URL, token, voice, and buffering settings
- voice discovery and health checks from the local service
- displaying the extension origin so it can be allow-listed in the local service config

The browser client is still a prototype. It deliberately keeps all browser-specific behavior inside `apps/chrome_extension/` and reuses the existing localhost HTTP and WebSocket contracts.

For extension-specific setup and troubleshooting, see [README.md](/home/kajsing/projects/TTS-platform/apps/chrome_extension/README.md) and [TROUBLESHOOTING.md](/home/kajsing/projects/TTS-platform/apps/chrome_extension/TROUBLESHOOTING.md).
