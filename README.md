# TTS Platform

Offline-first local text-to-speech platform designed around a stable core domain, a localhost API, and browser playback integration.

For ongoing Codex implementation work, use `docs/codex/Prompt.md`, `docs/codex/Plan.md`, `docs/codex/Implement.md`, and `docs/codex/Documentation.md` as the workflow source of truth. This README remains the product and setup overview.

## Current Status

Repository feature summary through the Phase 6 checkpoint plus current Phase 7
and v1-readiness work:

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
- backend runtime modes for `stub`, `auto`, and `real`
- manifest-side backend asset binding for real `sherpa-onnx` voices
- backend status reporting in `/v1/health`
- shared chunk planning for sync, job, and streaming synthesis
- local model catalog/install/activate/remove CLI helpers
- callback-driven real-runtime streaming and cancellation when the installed
  `sherpa_onnx` package exposes generation callbacks, with fallback for older
  runtimes
- separate long-text character limit for WebSocket streaming so page-scale
  extension playback can exceed the shorter HTTP/job request limit
- WebSocket reader progress metadata and `start_text_chunk_index` resume anchor
  for long streamed playback
- popup-side resume action for page playback based on the latest reader progress

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
2. Install dependencies from [`pyproject.toml`](pyproject.toml).
3. Copy [`config/config.example.toml`](config/config.example.toml) to `config/config.toml`.
4. Run the tests.

Example:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
```

On Windows, use `py -3` if `python3` resolves to the Microsoft Store alias:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
```

## CLI Usage

Examples:

```bash
tts health
tts list-voices
tts save "Hello world" --out out.wav --token "$TTS_PLATFORM_TOKEN"
tts stream "Hello world" --out stream.wav --token "$TTS_PLATFORM_TOKEN"
tts job-status <job-id> --token "$TTS_PLATFORM_TOKEN"
tts catalog-list --catalog ./models/catalog.json
tts model-install sherpa-en-v1 --catalog ./models/catalog.json --overwrite
tts model-install sherpa-en-v1 --catalog ./models/catalog.json --activate
tts model-activate sherpa-en-v1
tts model-remove sherpa-en-v1
```

Protected commands require `--token` or `TTS_PLATFORM_TOKEN`.

The `catalog-list`, `model-install`, `model-activate`, and `model-remove`
commands are local model-management helpers and do not require service auth
tokens. `model-install` downloads or reads a catalog artifact, verifies
`artifact_sha256` when present, extracts the zip safely under
`models/voices/<model-id>`, and updates `models/MANIFEST.json`.
`model-activate` validates that the model exists in the manifest and updates
`config/config.toml` so new synthesis requests use that voice by default.
Use `model-install --activate` for the first-run path when the installed model
should immediately become the default voice.

For backend modes, model asset layout, manifest conventions, catalog format,
and current long-text limits, see
[`docs/backend_model_setup.md`](docs/backend_model_setup.md).

## Benchmarking

Examples:

```bash
python3 scripts/benchmark.py --token "$TTS_PLATFORM_TOKEN"
python3 scripts/benchmark.py --mode stream --token "$TTS_PLATFORM_TOKEN"
```

The benchmark script reports average latency, output duration, output size, and an approximate real-time factor.

## Chrome Extension Prototype

See [apps/chrome_extension/README.md](apps/chrome_extension/README.md) for setup and loading instructions.

The extension currently supports:

- speaking the current text selection
- speaking a bounded readable snapshot of the current page
- offscreen playback of streamed PCM audio
- popup-side reader progress for streamed page playback
- resuming page playback from the latest reader progress on the active tab
- local storage of base URL, token, voice, and buffering settings
- voice discovery and health checks from the local service
- displaying the extension origin so it can be allow-listed in the local service config

The browser client is still a prototype. It deliberately keeps all browser-specific behavior inside `apps/chrome_extension/` and reuses the existing localhost HTTP and WebSocket contracts. Page playback uses the WebSocket stream path, which supports a larger `tts.max_chars_per_stream` limit than the shorter HTTP/job request path and exposes reader progress in stream events.

For extension-specific setup and troubleshooting, see
[README.md](apps/chrome_extension/README.md) and
[TROUBLESHOOTING.md](apps/chrome_extension/TROUBLESHOOTING.md).
