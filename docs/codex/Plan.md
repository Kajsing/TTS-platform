# Plan

This file is the source of truth for execution order.

## Global Rules

- Follow milestones in order unless `Documentation.md` records a deliberate reason to reorder them.
- Keep each loop scoped to one milestone or one clearly bounded slice of a milestone.
- Run the listed validation after every milestone.
- Stop-and-fix rule: if validation fails, fix it before moving on.
- Do not treat partial progress inside a milestone as completion.

## Architecture Notes That Prevent Oscillation

- Keep API schemas stable and backend-agnostic.
- Keep chunk planning in the domain layer, orchestration in the application layer, and backend/model/runtime work in infrastructure.
- Keep browser-specific behavior inside `apps/chrome_extension/` except for the existing localhost auth/origin accommodations already documented in the repo.
- Prefer truthful readiness, startup, and cancellation semantics over optimistic but misleading behavior.

## Milestone 1: Improve Chunk-Plan Heuristics

Acceptance criteria:

- `ChunkPlanner` improves beyond simple sentence grouping and simple pause hints.
- Heuristics stay deterministic and live in the domain layer.
- Sync, job, and streaming flows continue to share the same chunk-planning entry point.
- Tests cover the new chunk boundaries and expected metadata.

Validation commands:

```bash
python3 -m pytest -q packages/tts_core/tests/test_text.py apps/tts_service/tests/test_api.py apps/tts_service/tests/test_streaming.py
python3 -m pytest -q
python3 -m ruff check .
```

## Milestone 2: Tighten Streaming Toward Incremental Backend Generation

Acceptance criteria:

- Streaming no longer depends only on "synthesize an entire planned chunk, then slice PCM frames" unless that limitation is explicitly preserved and logged as unfinished work.
- The WebSocket event contract remains stable unless a contract bug requires a documented change.
- Streaming tests cover startup, chunk delivery, completion, and the real-backend path.
- Benchmarking and smoke testing still work on the public contract.

Validation commands:

```bash
python3 -m pytest -q packages/tts_core/tests/test_sherpa_onnx_backend.py apps/tts_service/tests/test_streaming.py apps/tts_service/tests/test_api.py
python3 -m pytest -q
python3 -m ruff check .
```

With the service running and a valid token available:

```bash
python3 scripts/benchmark.py --mode stream --token "$TTS_PLATFORM_TOKEN"
tts stream "Hello world" --out stream.wav --token "$TTS_PLATFORM_TOKEN"
```

## Milestone 3: Tighten Cancellation Semantics

Acceptance criteria:

- Queued-job, running-job, and active-stream cancellation behavior is explicit in code and docs.
- Terminal states stay consistent even when hard interruption is only best-effort.
- Tests cover the supported cancellation guarantees and limitations.
- Health, logging, or observability stay truthful about cancellation outcomes.

Validation commands:

```bash
python3 -m pytest -q apps/tts_service/tests/test_api.py apps/tts_service/tests/test_streaming.py apps/tts_service/tests/test_observability.py
python3 -m pytest -q
python3 -m ruff check .
```

With the service running and a valid token available:

```bash
python3 scripts/benchmark.py --mode job --token "$TTS_PLATFORM_TOKEN"
```

## Milestone 4: Document Backend Setup And Manifest Conventions

Acceptance criteria:

- Human-readable docs explain model asset layout, manifest conventions, backend modes, readiness behavior, and current limitations.
- Documentation matches actual repo behavior and config names.
- Public contracts and security assumptions remain explicit.
- Documentation changes do not silently redefine behavior that code and tests do not support.

Validation commands:

```bash
python3 -m pytest -q
python3 -m ruff check .
```

Optional smoke commands after starting the service:

```bash
python3 scripts/dev_run.py
tts health
tts list-voices
```

## Milestone 5: Phase 7 Closeout

Acceptance criteria:

- All remaining open Phase 7 items are complete or explicitly listed as unfinished in `Documentation.md`.
- `Prompt.md` done-when criteria are checked against the current repo state.
- `Documentation.md` is updated with final status, remaining follow-ups, and a clean resume point.
- Status and workflow docs no longer point Codex at stale execution-order information.

Validation commands:

```bash
python3 -m pytest -q
python3 -m ruff check .
python3 scripts/check_extension.py
```

With the service running and a valid token available:

```bash
tts health
tts list-voices
python3 scripts/benchmark.py --mode http --token "$TTS_PLATFORM_TOKEN"
python3 scripts/benchmark.py --mode stream --token "$TTS_PLATFORM_TOKEN"
python3 scripts/benchmark.py --mode job --token "$TTS_PLATFORM_TOKEN"
```

## Post-Phase 7: V1 Reader Track

After Phase 7 closeout, continue toward the active v1 product goal in this
order unless `Documentation.md` records a deliberate reorder:

1. Long-document reading orchestration for thousands-of-words inputs.
2. Model-management UX and hardening: catalog clarity, progress output,
   checksum defaults, install/activate/remove safety, and first-run guidance.
3. Service packaging/install and Windows-friendly first-run flow.
4. Chrome extension onboarding and installability.
5. Release hardening: docs, security defaults, smoke tests, and remaining test
   coverage gaps.

Keep browser-specific behavior inside `apps/chrome_extension/`, and keep the
service contract stable while adding any long-document orchestration.

The first long-document slices are now:

- separate `tts.max_chars_per_stream` limit for WebSocket playback;
- stream progress metadata plus `start_text_chunk_index` as a resume anchor.
- popup-side `Resume Page` action that re-extracts active-tab text and resumes
  from the latest reader progress.
- extension-side page-capture metadata so long page reads report captured
  characters, extraction source, readable block count, and truncation at the
  configured page limit.
- extension-side page-structure metadata so captured long pages preserve short
  headings and report heading/body/list/quote counts without storing heading
  text.
- popup-side `Next Section` action that uses heading offsets and section
  indexes to re-extract active-tab text from a later captured section without
  storing heading text.
- popup-side `Previous Section` action that uses the same heading offsets and
  re-extracts active-tab text from an earlier captured section without storing
  heading text.
- truncated-page continuation metadata so `Next Section` can jump to the first
  known uncaptured section after the current capture limit without storing
  heading text or raw page text.

The first model-management UX slices now cover `model-install --activate`,
catalog-list summary/warning output, install progress metadata/status lines,
and checksum-required-by-default model installs with an explicit trusted-local
override.
The first Windows-friendly setup slice now adds `tts setup-local` for local
config/token bootstrap and manifest readiness reporting. The first service-run
slice now adds `tts serve` as the normal installed-CLI localhost run command.
The first packaging slice now adds PowerShell/CMD Windows launchers that run
setup fallback plus `tts serve` without choosing a permanent service manager.
The second packaging slice now adds `scripts/package_windows_bundle.py` for a
Windows-friendly local reader source bundle that includes launchers, docs,
config example, service/core source, extension source, and a validated extension
zip while excluding local token/model artifacts.
The first extension onboarding slice now adds a popup setup checklist and
validator coverage for its wiring. The first extension packaging slice now adds
`scripts/package_extension.py` for validated local zip builds. The first
release-hardening slice now rejects unsafe `security.allowed_origins` entries
at config load. The second release-hardening slice now adds
`scripts/release_check.py` as a repo-native local release gate. The third
release-hardening slice adds optional `--live-smoke` coverage for a running
local service. The fourth release-hardening slice redacts inline live-smoke
tokens in release-check summaries. The fifth release-hardening slice now keeps
HTTP request logs low-sensitivity by replacing unsafe client-provided request
ids and adding regression coverage for query string, token, and raw text
omission. The sixth release-hardening slice now adds
`scripts/check_security_defaults.py` and wires it into the release gate so the
example config and ignore policy keep localhost, auth, empty allow-list,
long-stream, local CPU backend, and local artifact defaults explicit. The
seventh release-hardening slice now lets live smoke checks use separate
page-scale WebSocket stream text, repeat it for long-reader coverage, assert a
minimum stream text-chunk count, and redact inline smoke text from release-check
summaries. The eighth release-hardening slice now removes `<all_urls>` from
extension `host_permissions` and expands `scripts/check_extension.py` with
manifest-policy and privacy/layering checks so service permissions stay
localhost-only while page access remains content-script based. The ninth
release-hardening slice now adds `docs/v1_readiness.md` and
`scripts/check_v1_readiness.py`, wiring readiness verification into the release
gate and Windows bundle so automated gates, manual gates, product choices, and
known not-yet-automated items stay explicit. The tenth release-hardening slice
now adds `scripts/check_windows_bundle_bootstrap.py`, wiring safe bundle
extraction and extracted-source `setup-local` into the release gate. The
eleventh release-hardening slice now adds
`scripts/check_local_service_bootstrap.py`, wiring isolated first-run service
startup plus public-contract smoke into the release gate. The twelfth
release-hardening slice now adds `scripts/check_model_management_flow.py`,
covering a generated local catalog/artifact install, activate, service smoke,
and remove flow. The thirteenth release-hardening slice now adds
`scripts/check_extension_onboarding.py`, covering popup setup controls,
extension-origin allow-list snippet compatibility, and service health/voice
discovery without requiring a full Chrome MV3 harness. The fourteenth
release-hardening slice now adds `scripts/check_windows_bundle_install.py`,
covering extracted-bundle temporary venv creation, package install, installed
`tts setup-local`, installed `tts serve`, and public-contract smoke. The
fifteenth release-hardening slice now adds
`scripts/check_extension_reader_flow.py`, covering long-page reader wiring plus
generated thousand-word WebSocket stream smoke. The sixteenth
release-hardening slice tightens extension stop/restart and popup reopen-state
recovery by persisting interrupted playback state when the offscreen document is
gone and extending the reader-flow gate to cover those signals. The seventeenth
release-hardening slice adds a setup-only Windows launcher path plus
`scripts/check_windows_launchers.py`, covering bundled PowerShell/CMD
first-run setup without choosing a permanent service manager. The eighteenth
model-management slice adds `tts model-check`, a read-only readiness diagnostic
for default or selected voices that reports manifest/backend asset readiness,
backend mode, `sherpa_onnx` availability, and concrete next steps before
operators expect real acoustic output. The nineteenth reader-flow slice adds
popup-side `Previous Section` navigation, reusing heading offsets and active-tab
re-extraction so long article navigation can move backward without storing raw
page text. The twentieth release-hardening slice extends
`scripts/check_windows_launchers.py` to start bundled PowerShell/CMD launchers
as foreground services on reserved loopback ports, run public-contract smoke,
and stop the process trees without choosing a permanent service manager.
The twenty-first packaging slice adds `scripts/windows/install_local.ps1` and
`.cmd` wrapper support for extracted bundles, bootstrapping `.venv`, local
package install, and `setup-local` without choosing a permanent service
manager or auto-start mechanism.
The twenty-second model-management hardening slice makes `artifact_sha256`
required by default for `model-install`, with `--allow-missing-checksum` as an
explicit trusted-local override.
The twenty-third reader-flow slice extends page-capture structure metadata with
a `nextSectionIndex` continuation marker for truncated captures, allowing
`Next Section` to re-extract from the first known uncaptured heading-backed
section without storing raw page text or heading text.
The twenty-fourth model-management slice resolves relative `artifact_url`
entries from remote HTTP catalogs against the catalog URL before download, so
the download/install path works consistently for local catalog files and remote
catalogs.
The twenty-fifth model-management slice stages downloaded or copied artifacts
in a temporary file and verifies/extracts from that file, avoiding a full
artifact-sized byte string in memory during install.
The twenty-sixth release-hardening slice extends
`scripts/check_model_management_flow.py` to serve the generated catalog and
relative artifact over loopback HTTP, proving the remote-catalog download path
inside the offline release gate.
The twenty-seventh reader-flow slice adds popup-side `Continue Page` for
truncated captures that do not expose a later heading-backed section. It uses a
non-textual `nextTextCharStart` offset and re-extracts active-tab text without
storing raw page text.
The twenty-eighth reader-flow slice adds automatic continuation after a
truncated page segment finishes normally, using the same `nextTextCharStart`
metadata and source tab without storing raw page text.
The twenty-ninth extension-installability slice adds a local `INSTALL.md`
handoff guide and manifest/action PNG icon assets to the Chrome extension
package, with validator, package, and Windows bundle bootstrap coverage.
The thirtieth release-hardening slice adds
`scripts/check_chrome_extension_smoke.py`, a skip-aware Chrome/Edge MV3 browser
smoke that loads the unpacked extension, starts an isolated local service,
opens a generated long article, verifies page capture, starts page playback,
observes playback state, and can be made strict with `--require-browser`.
The thirty-first extension-onboarding slice adds
`tts extension-allow-origin <chrome-extension-origin>`, making first-run
allow-list setup idempotent and config-validated instead of requiring manual
TOML edits.
The thirty-second extension-onboarding slice adds a popup-side copyable
allow-list command, so the extension can hand the operator the exact
`tts extension-allow-origin ...` command during first-run setup.
The thirty-third model-management UX slice makes `--catalog` optional for
`tts catalog-list` and `tts model-install`, defaulting both commands to
`models/catalog.json`, adds friendly missing-default-catalog guidance, and
extends the model-management smoke with default-catalog next-step evidence.
The thirty-fourth model-management UX slice makes `tts model-check`
default-catalog aware, reporting whether `models/catalog.json` exists and
omitting redundant `--catalog` guidance when the default catalog is available.
The thirty-fifth model-management slice adds a committed default English model
catalog entry for `vits-piper-en_US-lessac-medium`, supports official
sherpa-onnx tar archives in `model-install` with safe extraction checks, and
includes the default catalog in the Windows local reader bundle.
The thirty-sixth model-management UX slice makes `tts model-check` inspect the
default catalog contents and suggest a concrete installable catalog model when
the configured development stub is not real-backend ready, avoiding misleading
stub reinstall guidance.
The thirty-seventh first-run UX slice makes `tts setup-local` inspect the
default catalog too, returning catalog status in JSON and putting the concrete
default English `tts model-install vits-piper-en_US-lessac-medium --activate`
step first when the configured default voice is still a non-real development
stub.
The thirty-eighth release-hardening slice extends
`scripts/check_local_service_bootstrap.py` to seed the default catalog and fail
if first-run `setup-local` output does not put that concrete default model
install command first.
The thirty-ninth packaging UX slice updates the generated
`WINDOWS_BUNDLE_README.md` so the first-run model section installs
`vits-piper-en_US-lessac-medium` before re-checking readiness, matching the
catalog-aware `setup-local` next steps.
The fortieth release-hardening slice makes the Windows bundle bootstrap and
install checks fail if extracted/installed `setup-local` output does not expose
the default catalog and put the concrete default model install command first.
The forty-first release-hardening slice exposes the same
`catalog_single_installable_model` signal from Windows launcher setup-only
summaries, keeping all Windows first-run checks aligned.
The forty-second model-management UX slice adds `tts model-list`, a read-only
offline manifest/default-voice listing command, and wires it into the
model-management flow smoke.
The forty-third first-run UX slice exposes `sherpa_onnx` runtime status from
`tts setup-local` and `tts model-list`, adding `python -m pip install
sherpa-onnx` next-step guidance before real local playback.
The forty-fourth extension-onboarding slice surfaces backend readiness and
default-voice loading directly in the popup service snapshot and setup
checklist, with validator coverage for those first-run signals.
The forty-fifth release-hardening slice makes the extension onboarding smoke
explicitly assert and report `backend_ready` and `default_voice_loaded` from
the service snapshot.
The forty-sixth real-audio UX slice adds `scripts/demo_real_voice.py`, an
optional reproducible Lessac demo that seeds ignored `dist/real-demo`, installs
the default catalog model there, runs public-contract smoke, writes a WAV, and
stops its temporary service.
The forty-seventh runtime-readiness hardening slice makes `model-check`,
`model-list`, and `setup-local` report `numpy` availability too, because the
real async/stream callback path needs it even when short sync synthesis works.
The forty-eighth install-flow slice adds a `real` optional dependency extra for
`sherpa-onnx` and `numpy`, so real voice demos can use
`python -m pip install -e ".[real]"` instead of loose runtime package commands.
The forty-ninth reader-flow reliability slice makes page capture skip
`aria-hidden`, `hidden`, and `inert` DOM subtrees so long-page playback avoids
hidden UI noise without adding a full reader-mode extractor.
The fiftieth reader-flow reliability slice routes fallback plain-text capture
through the same skip/hidden subtree filters, so flat pages without enough
reader blocks still avoid hidden UI and chrome noise.
The fifty-first reader-flow reliability slice changes readable-root selection
from first matching candidate to best scored candidate, improving extraction on
pages with multiple article/main/content containers.
The fifty-second first-run UX slice makes runtime next-step guidance prefer the
committed `.[real]` optional dependency extra when both `sherpa-onnx` and
`numpy` are missing, while preserving targeted single-package guidance.
The fifty-third extension-flow hardening slice adds observed-browser-target
diagnostics when the optional Chrome/MV3 smoke cannot find the extension
service worker, making skipped browser evidence easier to triage.
The fifty-fourth release-hardening slice makes extension JavaScript syntax
validation configurable and strict-capable via `--node-executable`,
`TTS_PLATFORM_NODE`, and `--require-js-syntax`.
The fifty-fifth release-hardening slice propagates `--node-executable` and
`--require-js-syntax` through `scripts/release_check.py`, so full release gates
can require extension JavaScript syntax parsing without manual environment
setup.
The fifty-sixth extension-flow hardening slice makes the Chrome/MV3 smoke
discover the unpacked extension id from the temporary Chrome profile and execute
from the extension popup CDP context, avoiding a false dependency on eager MV3
service-worker startup before page playback is exercised.
The fifty-seventh Windows first-run UX slice adds
`scripts/windows/install_local.ps1 -InstallRealRuntime` plus
`scripts/check_windows_bundle_install.py --install-real-runtime`, keeping real
runtime dependency installation opt-in while making the extracted-bundle
bootstrap capable of installing `.[real]` in the same `.venv`.
The fifty-eighth Windows first-run hardening slice makes the extracted-bundle
installer install the package's base dependencies by default, adds
`-NoDependencies`/`--no-dependencies` only for already provisioned environments,
and reports `dependencies_installed` in the installer/check summaries.
The fifty-ninth model-management UX slice expands `tts catalog-list`
`model_summaries` with operator-facing install metadata: artifact URL and
download size, license/source/upstream links, tags, and capability flags, with
model-management smoke coverage proving those fields survive the catalog flow.
The sixtieth model-management hardening slice adds artifact metadata to
`tts model-install` JSON output, including actual loaded bytes, MiB size,
catalog-declared size, and a size-match signal, with model-management smoke
coverage proving those fields survive install.
The sixty-first model-management hardening slice moves existing model directory
refusal ahead of artifact load when `--overwrite` is not set, so rerunning
`tts model-install` does not download or copy a large artifact before failing.
The sixty-second extension-installability slice makes `TROUBLESHOOTING.md` an
explicit Chrome extension handoff asset: `check_extension.py` validates key
troubleshooting sections, `package_extension.py` reports it in the package
summary, and the Windows bundle propagates that metadata.
The sixty-third release-hardening slice propagates `--node-executable` and
`--require-js-syntax` into standalone extension and Windows bundle packaging,
so local package builds can require extension JavaScript syntax validation
without relying on a separate release-check invocation.
The sixty-fourth real-audio UX slice adds
`scripts/demo_real_voice.py --install-real-runtime`, an explicit opt-in path
that installs `.[real]` into the active Python environment before demo
setup/model checks, keeping the default offline gates download-free while
making real English voice reproduction closer to one command.
Continue from the readiness audit: either automate another listed manual gate
or take the next reader-flow/product slice.
