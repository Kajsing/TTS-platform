# Backend And Model Setup

This document explains the current model layout, manifest conventions, backend
modes, readiness behavior, and model-management commands for the local TTS
service.

The current v1 direction is a Windows-friendly localhost reader: the service
runs locally, the Chrome extension sends page or selection text to the service,
and installed local voice models provide synthesis.

## Runtime Files

Expected repository-local files:

```text
config/
  config.toml
  config.example.toml
  token.txt
models/
  MANIFEST.json
  voices/
    <voice-id>/
      model files copied from the installed artifact
```

The service reads `config/config.toml` when started through
`python3 scripts/dev_run.py`. If the file is absent, built-in defaults are used.
The token file path defaults to `./config/token.txt`.

The voice registry is loaded from `models/MANIFEST.json`. If the manifest has no
voices or is absent, the backend can expose the development stub voice
`sherpa-en-debug`.

## Backend Modes

`config/config.example.toml` defines:

```toml
[backend]
mode = "auto"
provider = "cpu"
num_threads = 1
debug = false
max_num_sentences = 1
```

Supported `backend.mode` values:

- `stub`: always use the deterministic development synthesizer.
- `auto`: use real `sherpa_onnx` runtime for voices that have manifest backend
  config; fall back to the stub path for voices without backend config.
- `real`: require a valid manifest backend config and installed `sherpa_onnx`
  runtime for the selected voice.

Supported `backend.provider` values are `cpu`, `cuda`, and `coreml`. The current
Windows-safe default is `cpu`.

## Readiness

`GET /v1/health` reports service readiness:

- `status`: `ok` only when all checks pass; otherwise `degraded`.
- `checks.backend_ready`: false when warmup failed.
- `checks.default_voice_loaded`: false when the configured default voice is not
  in the registry.
- `startup_error`: the warmup error message, if any.
- `backend.runtime_mode`: active backend mode.
- `backend.configured_real_voices`: number of manifest voices with backend
  config.
- `backend.loaded_real_voices`: real runtime voices initialized so far.
- `backend.module_loaded`: whether `sherpa_onnx` has been imported.

With `backend.mode = "real"` and `tts.warmup_on_start = true`, missing
`sherpa_onnx`, missing backend config, or missing model assets will make health
degraded. In `auto` mode, a voice without backend config can still use the stub
path.

## Voice Manifest

`models/MANIFEST.json` must be a JSON object with `version: 1` and a `voices`
array.

Minimal shape:

```json
{
  "version": 1,
  "voices": [
    {
      "id": "sherpa-en-debug",
      "name": "Sherpa English Debug",
      "engine": "sherpa_onnx",
      "language": "en",
      "sample_rate_hz": 24000,
      "license": "development-only",
      "source": "models/voices/sherpa-en-debug",
      "quality_tier": "development",
      "latency_tier": "unknown",
      "tags": ["stub", "debug"],
      "capabilities": {
        "supports_pitch": false,
        "supports_streaming": false,
        "supports_multi_speaker": false
      }
    }
  ]
}
```

Required voice fields:

- `id`
- `name`
- `engine`
- `language`
- `sample_rate_hz`
- `license`
- `source`

Optional descriptor fields:

- `gender_style_hint`
- `quality_tier`
- `latency_tier`
- `tags`
- `capabilities.supports_pitch`
- `capabilities.supports_streaming`
- `capabilities.supports_multi_speaker`
- `quality_score`
- `speed_score`
- `stability_score`

## Real sherpa-onnx Backend Config

A manifest voice can include a `backend` object. Supported `model_type` values:

- `vits`
- `matcha`
- `kokoro`
- `kitten`

Backend path fields:

- `model`
- `tokens`
- `data_dir`
- `lexicon`
- `voices`
- `acoustic_model`
- `vocoder`
- `rule_fsts`

Other backend fields:

- `speaker_id`

Required asset rules:

- `vits` requires `model`, plus either `tokens` or `data_dir`.
- `matcha` requires `acoustic_model` and `vocoder`, plus either `tokens` or
  `data_dir`.
- `kokoro` requires `model`, `voices`, `tokens`, and `data_dir`.
- `kitten` requires `model`, `voices`, `tokens`, and `data_dir`.
- `lexicon` and every `rule_fsts` entry must exist if provided.

Relative paths are resolved from the repository root. The model-management CLI
stores installed assets under `models/voices/<voice-id>` and rewrites common
backend path fields to that location when the catalog uses relative asset names.

Example real VITS voice entry:

```json
{
  "id": "sherpa-en-v1",
  "name": "Sherpa English V1",
  "engine": "sherpa_onnx",
  "language": "en",
  "sample_rate_hz": 24000,
  "license": "check-catalog-license",
  "source": "models/voices/sherpa-en-v1",
  "quality_tier": "standard",
  "latency_tier": "local",
  "tags": ["english", "local"],
  "capabilities": {
    "supports_pitch": false,
    "supports_streaming": true,
    "supports_multi_speaker": false
  },
  "backend": {
    "model_type": "vits",
    "model": "models/voices/sherpa-en-v1/model.onnx",
    "tokens": "models/voices/sherpa-en-v1/tokens.txt",
    "speaker_id": 0
  }
}
```

## Catalog Format

`tts model-install` reads a catalog JSON file or URL. The catalog root must be an
object with a `models` list. Each model entry must include at least:

- `id`
- `artifact_url`

Recommended model fields:

- `name`
- `language`
- `sample_rate_hz`
- `license`
- `quality_tier`
- `latency_tier`
- `tags`
- `capabilities`
- `artifact_sha256`
- `backend`

`artifact_url` may be `http`, `https`, an absolute local path, or a path relative
to the catalog file. `artifact_sha256` is optional but strongly recommended.

Install behavior:

- verifies `artifact_sha256` when present
- rejects unsafe zip entries before extraction
- extracts to a temporary directory first
- replaces an existing model directory only after extraction succeeds
- writes or updates the manifest entry

Unsafe zip entries include absolute paths, Windows drive-qualified paths, and
path traversal using either `/` or `\`.

## Model CLI Workflow

List catalog entries:

```bash
tts catalog-list --catalog ./models/catalog.json
```

Install a model:

```bash
tts model-install sherpa-en-v1 --catalog ./models/catalog.json
```

Replace an existing installed model:

```bash
tts model-install sherpa-en-v1 --catalog ./models/catalog.json --overwrite
```

Activate an installed model as the default voice:

```bash
tts model-activate sherpa-en-v1
```

Remove an installed model:

```bash
tts model-remove sherpa-en-v1
```

These model-management commands edit local files and do not call protected
service endpoints, so they do not require `--token` or `TTS_PLATFORM_TOKEN`.

## Long-Text Implications

The service keeps separate text limits for short requests and streamed reading:

- `tts.max_chars_per_request` defaults to `4000` and applies to `/v1/tts` and
  `/v1/tts/jobs`.
- `tts.max_chars_per_stream` defaults to `48000` and applies to
  `WS /v1/tts/stream`.

The split keeps synchronous WAV and async job requests bounded while allowing
the browser reader to send page-scale text to the streaming path.

The current long-text path is therefore:

- capture bounded readable page text in the extension,
- send page text through the WebSocket stream path,
- let the service normalize, segment, plan chunks, synthesize, stream, and allow
  cancellation between planned chunks.

When the installed `sherpa_onnx` runtime exposes generation callbacks, the real
backend streaming path emits audio from those callbacks instead of waiting for
the full generated audio buffer. Older runtimes or runtimes without a usable
callback fall back to the full-buffer path.

The server-side chunk planner now improves chunk boundaries, the stream path has
a separate page-scale text limit, and the real runtime path can stream callback
audio. The product still needs a richer long-document reader workflow before
the Chrome reader is fully v1-ready.

## Cancellation Limits

Cancellation is terminal and observable at the service-contract level:

- queued jobs become `cancelled`;
- running jobs stay `cancelled` even if backend generation finishes later;
- chunk-planned synthesis checks cancellation between planned chunks;
- real-runtime generation receives a cancellation callback when the installed
  `sherpa_onnx` package supports generation callbacks;
- WebSocket cancellation returns a `cancelled` event when observed by the stream
  path.

Current limitation: hard interruption inside one real `sherpa_onnx` callback
interval is still best-effort. The job state will be correct, but older runtimes
or in-flight work between callback boundaries may finish before the worker
thread returns.

## Security Notes

- The service is expected to bind to `127.0.0.1`.
- Protected synthesis/job endpoints require bearer-token auth.
- Browser clients must be explicitly allow-listed by origin.
- Raw input text should not be logged.
- Model archives are local code-adjacent inputs. Use checksums and trusted
  catalog sources.
- Installed model files stay under `models/voices/<voice-id>`.

## Troubleshooting

Health is `degraded`:

1. Check `/v1/health` `startup_error`.
2. Confirm `config/config.toml` `tts.default_voice` exists in
   `models/MANIFEST.json`.
3. For `backend.mode = "real"`, confirm `sherpa_onnx` is installed in the active
   Python environment.
4. Confirm manifest backend asset paths exist.
5. Use `backend.mode = "auto"` or `stub` while validating service wiring without
   real model assets.

`model-install` fails:

1. Confirm the model id exists in `tts catalog-list` output.
2. Confirm the artifact URL or path is reachable.
3. Confirm the checksum matches when `artifact_sha256` is present.
4. Confirm the zip does not contain absolute or traversal paths.
5. Use `--overwrite` only when replacing an already-installed model.

Default voice is wrong:

1. Run `tts model-activate <model-id>`.
2. Restart the service so `config/config.toml` is reloaded.
3. Check `tts list-voices` and `/v1/health`.

## Validation

Baseline:

```bash
python3 -m pytest -q
python3 -m ruff check .
```

Windows PowerShell fallback:

```powershell
py -3 -m pytest -q
py -3 -m ruff check .
```

Optional service smoke after starting the service:

```bash
tts health
tts list-voices
python3 scripts/smoke_service.py --token-file config/token.txt
```
