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
`models/MANIFEST.json`, inspects the default `models/catalog.json`, and returns
next steps as JSON. It also reports whether `sherpa_onnx` is importable in the
active environment. The next steps include `tts model-check` so operators can
verify configured/default voice readiness before expecting real acoustic output.
When the configured default voice is only a development stub and the default
catalog has one installable real voice, setup guidance starts with the concrete
`tts model-install vits-piper-en_US-lessac-medium --activate` command and adds
`python -m pip install -e ".[real]"` when both real-runtime packages are
missing. If only one runtime package is absent, the next steps use the targeted
`python -m pip install sherpa-onnx` or `python -m pip install numpy` command
instead. It does not print the bearer token; read `config/token.txt` locally
when a protected client needs it.

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

Use `.\scripts\windows\install_local.ps1 -InstallRealRuntime` when this machine
should install the optional `.[real]` runtime dependencies into `.venv` during
the same bootstrap. Use `-NoDependencies` only for an already provisioned
environment.

```cmd
scripts\windows\run_service.cmd
```

The launchers set `PYTHONPATH` for the repo-local service/core packages, honor
`TTS_PLATFORM_PYTHON` when set, prefer `.venv\Scripts\python.exe` when present,
fall back to `py -3`, run `setup-local` when needed, and then run `tts serve`.
The CMD launchers delegate to the trusted
`%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe` path instead of
performing bare `powershell.exe` lookup in the current directory or `PATH`.
Use `.\scripts\windows\run_service.ps1 -SetupOnly` to create
`config\config.toml` and `config\token.txt` without starting the service. They
are convenience launchers; the v1 persistent autostart path is the per-user
Task Scheduler command below, not a machine-wide Windows Service.
Use `.\scripts\windows\install_local.ps1` first when the extracted bundle needs
a local `.venv`; it creates the virtual environment, installs the local package,
runs `setup-local`, and emits a JSON summary for automation. By default it
installs the package's base dependencies in `.venv`; add `-InstallRealRuntime`
when the bootstrap should also install the optional `.[real]` runtime
dependencies before `setup-local`, or `-NoDependencies` only for an already
provisioned environment.

After the local package is installed, optional per-user autostart is available
through Windows Task Scheduler:

```powershell
.\.venv\Scripts\tts.exe service-install --user
.\.venv\Scripts\tts.exe service-status --user
.\.venv\Scripts\tts.exe service-start --user
```

The scheduled task starts `scripts\windows\run_scheduled_service.ps1`, which
wraps `run_service.ps1` and appends startup output to
`logs\tts-service.log`. Remove it with:

```powershell
.\.venv\Scripts\tts.exe service-stop --user
.\.venv\Scripts\tts.exe service-remove --user
```

Build a Windows-friendly local reader bundle with:

```powershell
py -3 scripts\package_windows_bundle.py
```

The bundle is written to `dist\windows\tts-platform-local-reader.zip` by
default. It includes the service source, core source, Windows launchers, config
example, model manifest, setup docs, Chrome extension source, Chrome extension
install/troubleshooting guidance, icons, and a validated Chrome extension zip under
`dist\chrome_extension\`. It deliberately excludes local secrets such as
`config\token.txt` and installed model files under
`models\voices\`. The generated `WINDOWS_BUNDLE_README.md` explains the
extract, virtualenv, launcher, and extension-loading flow.
`scripts/check_windows_launchers.py` verifies the bundled PowerShell/CMD
launchers in setup-only mode and, on Windows, starts them as foreground
services on reserved loopback ports before running public-contract smoke and
stopping the process trees.
`scripts/check_windows_service_task.py` verifies the Task Scheduler command
shape, status parsing, scheduled wrapper, and log wiring without creating a
real scheduled task.
`scripts/check_windows_bundle_install.py` verifies the extracted bundle in a
temporary virtual environment by installing the package, running the installed
`tts setup-local` and `tts serve` entrypoint, and executing public-contract
smoke against the started service. When the bundled install script is present,
the check uses it for the venv/package/setup stage. Add
`--run-local-reader-check` when the same extracted-bundle install should also
run the bundled service bootstrap, model-management, extension onboarding,
reader-flow, and skip-aware Chrome/MV3 validation with the installed `.venv`
Python. The install check can pass strict nested validation flags through as
`--local-reader-node-executable`, `--local-reader-require-js-syntax`,
`--local-reader-browser-executable`, `--local-reader-require-browser`, and
`--local-reader-headed`. When the install check builds its own temporary bundle
instead of receiving `--bundle`, `--node-executable` and `--require-js-syntax`
make that package step strict and are inherited by the nested local-reader
check unless the local-reader-specific Node flags are set.

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
- `tts.max_chars_per_request`: current `/v1/tts` and job text limit.
- `tts.max_chars_per_stream`: current WebSocket stream text limit.
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

Backend asset paths must be relative and must resolve under the voice
`source`, normally `models/voices/<voice-id>`. Paths may be model-relative, such
as `model.onnx`, or already source-prefixed, such as
`models/voices/<voice-id>/model.onnx`. Absolute paths, traversal entries, and
paths under a different model directory are rejected by install, readiness
checks, and runtime loading. The model-management CLI stores installed assets
under `models/voices/<voice-id>` and rewrites common backend path fields to
that location when the catalog uses relative asset names.

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

`tts catalog-list` and `tts model-install` read a catalog JSON file or URL.
When `--catalog` is omitted, both commands use `models/catalog.json` from the
current working directory. Pass `--catalog <path-or-url>` for a different local
catalog file or remote catalog URL. The catalog root must be an object with a
`models` list. Each model entry must include at least:

- `id`
- `artifact_url`

Recommended model fields:

- `name`
- `language`
- `sample_rate_hz`
- `license`
- `license_url`
- `source_url`
- `upstream_url`
- `quality_tier`
- `latency_tier`
- `tags`
- `capabilities`
- `artifact_sha256`
- `artifact_size_bytes`
- `backend`

`artifact_url` may be `http`, `https`, an absolute local path, or a path
relative to the catalog source. Relative artifacts under a local catalog are
resolved against the catalog file directory; relative artifacts under an HTTP
catalog are resolved against the catalog URL before download.
Artifacts may be zip or tar archives, including `tar.gz`, `tgz`, `tar.bz2`, and
`tbz2`.
`artifact_sha256` is required by default for `model-install` so artifacts are
integrity-checked before extraction.
Remote artifact downloads are bounded before checksum verification: responses
must stay under the built-in maximum model artifact size of 2 GiB, and when
`artifact_size_bytes` is present the streamed bytes must also stay at or below
that catalog declaration. Redirects are followed manually and each target must
remain an allowed `http` or `https` artifact URL without embedded credentials.
Local/private network destinations are rejected by literal host and DNS
resolution unless they are the same origin as the remote catalog URL the
operator explicitly selected.

The committed default catalog at `models/catalog.json` starts with the English
`vits-piper-en_US-lessac-medium` sherpa-onnx voice. It points at the official
k2-fsa `vits-piper-en_US-lessac-medium.tar.bz2` release artifact, pins its
SHA-256 checksum, and maps the installed VITS backend to:

- `vits-piper-en_US-lessac-medium/en_US-lessac-medium.onnx`
- `vits-piper-en_US-lessac-medium/tokens.txt`
- `vits-piper-en_US-lessac-medium/espeak-ng-data`

`tts catalog-list` keeps the raw `models` entries in stdout JSON and adds:

- `catalog` counts for total, installable, and checksum-covered entries
- `model_summaries` for quick operator scanning, including language, engine,
  quality/latency tiers, license/source links, tags, capability flags,
  artifact URL, download size, and checksum state
- `warnings` for duplicate model ids, missing artifacts, and missing checksums
- `next_steps` with the suggested install command shape

Install behavior:

- resolves relative artifacts against either the local catalog file path or the
  remote catalog URL
- downloads or copies the artifact into a temporary file before checksum and
  extraction so large artifacts do not need to stay resident as one in-memory
  byte string
- caps remote artifact downloads before and during streaming, validates
  `Content-Length` when present, rejects unsafe redirect targets, and rejects
  remote artifact hostnames that resolve to local/private network addresses
  unless they match the explicitly selected remote catalog origin
- refuses an already-installed model before artifact download/copy unless
  `--overwrite` is set
- verifies `artifact_sha256` before extraction
- rejects missing `artifact_sha256` unless `--allow-missing-checksum` is used
  for a trusted local artifact
- rejects unsafe zip or tar entries before extraction
- rejects archives that exceed the built-in extracted-size or member-count
  quotas before extraction
- extracts to a temporary directory first
- replaces an existing model directory only after extraction succeeds
- writes or updates the manifest entry
- reports installed file count, checksum verification status, and suggested
  next steps
- reports the artifact URL, actual artifact byte count, MiB size, catalog
  artifact size declaration, and whether the declaration matched the loaded
  artifact
- prints progress status lines to stderr while preserving structured JSON on
  stdout

Unsafe archive entries include absolute paths, Windows drive-qualified paths,
and path traversal using either `/` or `\`. Tar symlinks, hard links, devices,
and other non-file/non-directory entries are rejected. Archive extraction is
also preflighted for total uncompressed bytes and file count before
`extractall` runs.

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
tts catalog-list
tts catalog-list --catalog ./models/catalog.json
```

Install a model:

```bash
tts model-install vits-piper-en_US-lessac-medium
tts model-install <model-id> --catalog <path-or-url>
```

Install and activate a model in one first-run command:

```bash
tts model-install vits-piper-en_US-lessac-medium --activate
tts model-install <model-id> --catalog <path-or-url> --activate
```

Replace an existing installed model:

```bash
tts model-install vits-piper-en_US-lessac-medium --overwrite
```

Install a trusted local artifact that has no checksum only with an explicit
override:

```bash
tts model-install <model-id> --catalog <path-or-url> --allow-missing-checksum
```

Activate an installed model as the default voice:

```bash
tts model-activate vits-piper-en_US-lessac-medium
```

Check whether an installed or default voice is ready for real local output:

```bash
tts model-list
tts model-check vits-piper-en_US-lessac-medium
tts model-check
```

`model-list` is read-only and does not require the service to be running. It
reports installed manifest voices, which one matches `[tts].default_voice`,
whether each voice has backend configuration, default catalog status,
`sherpa_onnx`/`numpy` runtime status, and next-step guidance.

`model-check` is also read-only. It reports config validity, the
selected/default voice, manifest presence, whether the voice has a sherpa-onnx
backend config, which backend asset paths exist, whether `[backend].mode` is
non-stub, whether `sherpa_onnx` and `numpy` can be imported, whether the default
`models/catalog.json` exists, which installable model ids it contains, and
concrete next steps. When the default catalog exists, install guidance omits
`--catalog`; otherwise it tells the operator to pass `--catalog <path-or-url>`.
If the configured default voice is still the development stub and the default
catalog has one installable real voice, `model-check` suggests that catalog
model, such as
`tts model-install vits-piper-en_US-lessac-medium --activate`, instead of
suggesting a stub reinstall. A development stub voice is expected to report
`ready: false` because it has no real backend asset configuration.

Remove an installed model:

```bash
tts model-remove vits-piper-en_US-lessac-medium
```

If the removed model id is still configured as `[tts].default_voice`,
`model-remove` reports `active_default_voice: true` plus next-step guidance.
It does not silently choose a replacement voice; activate another installed
model before restarting the service.

These model-management commands edit local files and do not call protected
service endpoints, so they do not require `--token` or `TTS_PLATFORM_TOKEN`.
`model-install --activate` also updates `config/config.toml`
`[tts].default_voice` and reports the config path in its JSON output.
`model-install` JSON also includes artifact metadata plus `install_steps`, so
scripts can inspect what was loaded and which local steps completed without
parsing stderr progress lines.

For a reproducible local real-voice demo without committing local model files,
run:

```bash
python3 -m pip install -e ".[real]"
python3 scripts/demo_real_voice.py --python-executable .venv/Scripts/python.exe
python3 scripts/demo_real_voice.py --python-executable .venv/Scripts/python.exe --install-real-runtime
python3 scripts/release_check.py --real-voice-demo --install-real-runtime
```

The demo seeds ignored `dist/real-demo`, installs and activates the default
catalog model there when needed, starts a temporary loopback service, runs
public-contract smoke with `--token-file`, writes
`dist/real-demo/lessac-demo.wav`, and stops the service process.
Use `--install-real-runtime` when the active Python environment should install
the optional `.[real]` runtime dependencies as part of the demo run. Use
`release_check.py --real-voice-demo` to include the same demo as an explicit
opt-in release gate without adding real model downloads to the default release
check.

## Long-Text Implications

The service keeps separate text limits for short requests and streamed reading:

- `tts.max_chars_per_request` defaults to `4000` and applies to `/v1/tts` and
  `/v1/tts/jobs`.
- `tts.max_chars_per_stream` defaults to `48000` and applies to
  `WS /v1/tts/stream`.

The split keeps synchronous WAV and async job requests bounded while allowing
the browser reader to send page-scale text to the streaming path.

`GET /v1/health` exposes both text limits under `tts`. The Chrome extension
uses `tts.max_chars_per_stream` as the service-side cap for page capture, while
still keeping its local per-segment safety cap and continuation flow for very
long articles.

Async jobs are also bounded by the `[limits]` section:

- `limits.max_stored_jobs` is the total in-memory job retention cap. When
  queued/running jobs already fill that cap, new `POST /v1/tts/jobs` requests
  are rejected with `429` instead of growing the executor backlog.
- `limits.max_job_seconds` marks a queued or running job `failed` after the
  configured lifetime and asks the backend to cancel the job. Hard interruption
  inside backend work remains best-effort, but a timed-out worker cannot later
  overwrite the terminal failed job state with `completed`.

The current long-text path is therefore:

- capture bounded readable page text in the extension,
- send page text through the WebSocket stream path,
- let the service normalize, segment, plan chunks, synthesize, stream, and allow
  cancellation between planned chunks.

Sentence segmentation bounds abbreviation lookbehind to the longest known
abbreviation token, so punctuation-heavy page text cannot force repeated
unbounded backward scans before synthesis starts.

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
The offscreen player also uses its configured high watermark to bound how far
ahead browser audio is scheduled, topping up queued PCM chunks as scheduled
sources finish. This keeps long-page playback from creating a large planned
audio window in the browser while retaining the same segmented continuation
model for page-scale text.

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
generated long article, verifies capture, starts page playback from an
extension popup CDP context, and observes playback state. It also lowers the
temporary service stream text limit below the extension's configured page limit
and checks that `Speak Page` stores page-capture metadata capped at the service
limit. Strict browser
evidence still requires a compatible browser on the operator machine. Branded
Chrome 137+ may ignore command-line unpacked extension loading; use Chrome for
Testing or Chromium with `--browser-executable` when strict automated evidence
is required.

## Cancellation Limits

Cancellation is terminal and observable at the service-contract level:

- queued jobs become `cancelled`;
- running jobs stay `cancelled` even if backend generation finishes later;
- timed-out jobs become `failed` and cannot later be overwritten by late backend
  completion;
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
- Async job submissions are bounded by configured in-memory retention and
  timeout limits so authenticated local clients cannot grow queued/running work
  without limit.
- Model archives are local code-adjacent inputs. Use checksums and trusted
  catalog sources.
- Remote model artifact downloads are bounded by checksum-before-fetch
  requirements, maximum byte caps, redirect destination checks, DNS-based
  private-network rejection, connected-peer private-network rejection when
  transport peer details are available, and archive extraction quotas before
  extraction side effects.
- Installed model files stay under `models/voices/<voice-id>`.
- Manifest backend asset paths must stay under the voice `source`; do not use
  absolute paths, `..`, or paths pointing at another model directory.
- The Chrome extension runtime validates its saved service `Base URL` before
  background fetch/WebSocket traffic uses it. It must be an HTTP localhost
  origin using `127.0.0.1` or `localhost`, with no credentials, path, query
  string, or fragment.

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
python3 scripts/check_windows_service_task.py
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
