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

For first-run setup, run:

```powershell
tts setup-local
```

The helper copies `config/config.example.toml` to `config/config.toml` when the
local config is missing, initializes `config/token.txt` through the same auth
path the service uses, checks whether the configured default voice appears in
`models/MANIFEST.json`, and returns next steps as JSON. It does not print the
bearer token; read `config/token.txt` locally when a protected client needs it.

Add a copied Chrome extension origin to the service allow-list with:

```powershell
tts extension-allow-origin chrome-extension://abcdefghijklmnopabcdefghijklmnop
```

The helper updates `security.allowed_origins` in `config/config.toml`, preserves
existing origins, rejects non-extension origins for this onboarding path, and
prints restart/popup next steps.

Start the service with:

```powershell
tts serve
```

`tts serve` loads `config/config.toml`, creates the app with the current repo as
the model/config root, and starts Uvicorn with the configured host, port, and
log level. It only allows loopback hosts (`127.0.0.1`, `localhost`, or `::1`) by
default; `--allow-non-local-host` must be explicit for any trusted-network bind.

Windows launcher scripts are also available:

```powershell
.\scripts\windows\install_local.ps1
.\scripts\windows\run_service.ps1
```

```cmd
scripts\windows\run_service.cmd
```

The launchers set `PYTHONPATH` for the repo-local service/core packages, honor
`TTS_PLATFORM_PYTHON` when set, prefer `.venv\Scripts\python.exe` when present,
fall back to `py -3`, run `setup-local` when needed, and then run `tts serve`.
Use `.\scripts\windows\run_service.ps1 -SetupOnly` to create
`config\config.toml` and `config\token.txt` without starting the service. They
are convenience launchers, not persistent Windows service installers.
Use `.\scripts\windows\install_local.ps1` first when the extracted bundle needs
a local `.venv`; it creates the virtual environment, installs the local package,
runs `setup-local`, and emits a JSON summary for automation.

Build a Windows-friendly local reader bundle with:

```powershell
py -3 scripts\package_windows_bundle.py
```

The bundle is written to `dist\windows\tts-platform-local-reader.zip` by
default. It includes the service source, core source, Windows launchers, config
example, model manifest, setup docs, Chrome extension source, Chrome extension
install guidance/icons, and a validated Chrome extension zip under
`dist\chrome_extension\`. It deliberately excludes local secrets such as
`config\token.txt` and installed model files under
`models\voices\`. The generated `WINDOWS_BUNDLE_README.md` explains the
extract, virtualenv, launcher, and extension-loading flow.
`scripts/check_windows_launchers.py` verifies the bundled PowerShell/CMD
launchers in setup-only mode and, on Windows, starts them as foreground
services on reserved loopback ports before running public-contract smoke and
stopping the process trees.
`scripts/check_windows_bundle_install.py` verifies the extracted bundle in a
temporary virtual environment by installing the package, running the installed
`tts setup-local` and `tts serve` entrypoint, and executing public-contract
smoke against the started service. When the bundled install script is present,
the check uses it for the venv/package/setup stage.

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

`tts catalog-list` and `tts model-install` read a catalog JSON file or URL. The
catalog root must be an object with a `models` list. Each model entry must
include at least:

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

`artifact_url` may be `http`, `https`, an absolute local path, or a path
relative to the catalog source. Relative artifacts under a local catalog are
resolved against the catalog file directory; relative artifacts under an HTTP
catalog are resolved against the catalog URL before download.
`artifact_sha256` is required by default for `model-install` so artifacts are
integrity-checked before extraction.

`tts catalog-list` keeps the raw `models` entries in stdout JSON and adds:

- `catalog` counts for total, installable, and checksum-covered entries
- `model_summaries` for quick operator scanning
- `warnings` for duplicate model ids, missing artifacts, and missing checksums
- `next_steps` with the suggested install command shape

Install behavior:

- resolves relative artifacts against either the local catalog file path or the
  remote catalog URL
- downloads or copies the artifact into a temporary file before checksum and
  extraction so large artifacts do not need to stay resident as one in-memory
  byte string
- verifies `artifact_sha256` before extraction
- rejects missing `artifact_sha256` unless `--allow-missing-checksum` is used
  for a trusted local artifact
- rejects unsafe zip entries before extraction
- extracts to a temporary directory first
- replaces an existing model directory only after extraction succeeds
- writes or updates the manifest entry
- reports installed file count, checksum verification status, and suggested
  next steps
- prints progress status lines to stderr while preserving structured JSON on
  stdout

Unsafe zip entries include absolute paths, Windows drive-qualified paths, and
path traversal using either `/` or `\`.

## Model CLI Workflow

Initialize local config and token files:

```bash
tts setup-local
```

Start the local service:

```bash
tts serve
```

Allow-list a locally loaded Chrome extension:

```bash
tts extension-allow-origin chrome-extension://abcdefghijklmnopabcdefghijklmnop
```

Or, on Windows:

```powershell
.\scripts\windows\run_service.ps1
```

List catalog entries:

```bash
tts catalog-list --catalog ./models/catalog.json
```

Install a model:

```bash
tts model-install sherpa-en-v1 --catalog ./models/catalog.json
```

Install and activate a model in one first-run command:

```bash
tts model-install sherpa-en-v1 --catalog ./models/catalog.json --activate
```

Replace an existing installed model:

```bash
tts model-install sherpa-en-v1 --catalog ./models/catalog.json --overwrite
```

Install a trusted local artifact that has no checksum only with an explicit
override:

```bash
tts model-install sherpa-en-v1 --catalog ./models/catalog.json --allow-missing-checksum
```

Activate an installed model as the default voice:

```bash
tts model-activate sherpa-en-v1
```

Check whether an installed or default voice is ready for real local output:

```bash
tts model-check sherpa-en-v1
tts model-check
```

`model-check` is read-only. It reports config validity, the selected/default
voice, manifest presence, whether the voice has a sherpa-onnx backend config,
which backend asset paths exist, whether `[backend].mode` is non-stub, whether
`sherpa_onnx` can be imported, and concrete next steps. A development stub
voice is expected to report `ready: false` because it has no real backend asset
configuration.

Remove an installed model:

```bash
tts model-remove sherpa-en-v1
```

If the removed model id is still configured as `[tts].default_voice`,
`model-remove` reports `active_default_voice: true` plus next-step guidance.
It does not silently choose a replacement voice; activate another installed
model before restarting the service.

These model-management commands edit local files and do not call protected
service endpoints, so they do not require `--token` or `TTS_PLATFORM_TOKEN`.
`model-install --activate` also updates `config/config.toml` `[tts].default_voice`
and reports the config path in its JSON output. `model-install` JSON also
includes `install_steps`, so scripts can inspect which local steps completed
without parsing stderr progress lines.

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

`WS /v1/tts/stream` also reports reader progress:

- `started.progress` includes the planned text chunk count, total planned text
  characters, completed characters, and percent complete.
- each `mark.progress` reports the planned text chunk currently producing audio.
- `done.progress` reports completion.
- a browser client can send `start_text_chunk_index` in the initial `start`
  event to begin from a later planned text chunk.

The Chrome extension uses this to implement `Resume Page`: it keeps the latest
reader progress in session playback state, re-extracts readable text from the
active tab, and asks the service to start from the saved planned text chunk. It
does not persist raw page text for resume.
The extension also uses page-capture heading offsets for `Previous Section` and
`Next Section`, re-extracting the active tab from a section index instead of
storing raw page text. If a capture is truncated before a later heading-backed
section, `Next Section` can use a non-textual continuation section index to
re-extract from the first known uncaptured section.
For long pages without a later heading-backed section, `Continue Page` uses a
non-textual character offset from the latest truncated capture metadata and
re-extracts the active tab from that offset. It still does not persist raw page
text.
When a page playback segment finishes normally and the latest capture still has
a continuation offset, the extension starts that next segment automatically
from the same metadata.

When the installed `sherpa_onnx` runtime exposes generation callbacks, the real
backend streaming path emits audio from those callbacks instead of waiting for
the full generated audio buffer. Older runtimes or runtimes without a usable
callback fall back to the full-buffer path.

The server-side chunk planner now improves chunk boundaries, the stream path has
a separate page-scale text limit, the real runtime path can stream callback
audio, stream events expose reader progress, and the extension has a basic
resume action plus previous/next section navigation with truncated-page
continuation and manual/automatic text-offset continuation for flat long pages.
`scripts/check_chrome_extension_smoke.py` can run an optional real Chrome/Edge
MV3 smoke that loads the extension, starts a temporary loopback service, opens a
generated long article, verifies capture, and starts page playback. Strict
browser evidence still requires Chrome or Edge on the operator machine.

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
- `security.allowed_origins` entries must be explicit `http`, `https`, or
  `chrome-extension` origins. Wildcard `*`, `null`, paths, query strings, and
  fragments are rejected when config loads.
- HTTP request logs include low-sensitivity metadata only: method, path without
  query string, status, duration, outcome, and request id.
- Raw input text, auth tokens, and query strings should not be logged.
- Client-provided `X-Request-ID` values are only reused when they are short,
  simple identifiers. Unsafe values, bearer-shaped values, and values equal to
  the current auth token are replaced with a server-generated id.
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
3. Confirm `artifact_sha256` is present and matches the artifact, or use
   `--allow-missing-checksum` only for a trusted local artifact.
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
python3 scripts/check_model_management_flow.py
python3 scripts/check_chrome_extension_smoke.py
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
