# Prompt

This file is the frozen project spec for ongoing Codex work in this repository.

## Source Precedence For This Freeze

Use these sources in this order when documents disagree:

1. Current repository behavior, tests, config, and code.
2. `AGENTS.md` hard rules.
3. `TASKS.md`, `design_doc/phase_7_plan.md`, `design_doc/thoughts_log.md`, `design_doc/backend_status_note.md`, and `design_doc/implementation_phase_additions.md`.
4. Background design intent in `design_doc/tts_platform_design_v_2.md`.

When older summaries disagree with later phase notes, preserve the later phase notes and record the conflict in `Documentation.md`.

## Project Goal

Build and finish an offline-first local text-to-speech platform for long-form
web reading on Windows. The v1 product goal is:

- a local server that runs a TTS pipeline over stable localhost HTTP and
  WebSocket contracts
- a Chrome extension that can capture and read long web pages containing
  thousands of words
- robust first-run, install, service/autostart, and model-management flows
- offline-first operation once models are installed
- security defaults suitable for a localhost reader that talks to a browser

The current long-horizon objective is to finish v1, not to keep expanding the
platform. Prefer closeout work: release validation, Windows install polish,
operator documentation, model-flow safety, extension installability, and a
final security-focused pass before calling v1 done.

V1 is now complete at the repo/test-contract level. New work should be treated
as post-v1 unless it fixes a regression or release blocker in the completed
local reader. The first recorded post-v1 exploration is an optional Windows
SAPI 5/TextAloud bridge; its durable plan is `docs/sapi_bridge.md`.

## Non-Goals

The current initiative does not include:

- adding new backend families beyond `sherpa-onnx`
- redesigning the public HTTP or WebSocket contract without a clear contract bug
- moving browser-specific logic into the localhost service
- distributed job execution or persistent job storage
- cloud-first deployment work
- a major Chrome extension UX redesign
- full reader-mode extraction, advanced SSML parity, or speculative prosody features that the current backend cannot support
- a machine-wide Windows Service, NSSM, pywin32 service, or Startup-folder
  autostart mechanism unless the user makes a new explicit product decision
- uploading local model artifacts or generated model files to GitHub
- treating the Windows SAPI/TextAloud bridge as part of v1 completion; it is a
  post-v1 optional integration track

## Hard Constraints

- Keep code and code comments in English.
- Keep architecture layers separate: API, application, domain, infrastructure.
- Prefer small, reviewable changes over broad rewrites.
- Add or update tests when behavior changes.
- Do not introduce backend-specific logic into API contracts.
- Treat localhost security as part of the product, not an optional extra.
- Treat Windows as the final target runtime platform even when development work happens inside WSL.
- Avoid Linux-only assumptions in paths, process management, shell usage, file permissions, and local setup guidance unless they are explicitly marked as WSL-only development details.
- Keep the platform offline-first once local models are installed.
- Keep the CLI and benchmark tooling on the public service contract instead of private internals.
- Preserve stable response and error shapes for `/v1/health`, `/v1/voices`, `/v1/tts`, `/v1/tts/jobs`, `/v1/tts/jobs/{job_id}`, `/v1/tts/jobs/{job_id}/result`, and `WS /v1/tts/stream` unless a clear contract bug requires change.
- Keep default service binding on `127.0.0.1` and preserve token auth, origin allow-listing, rate limiting, and low-sensitivity logging defaults.

## Required Deliverables

The project must preserve the already-built platform surface and complete the
v1 local-reader flow:

- keep sync, job, and streaming synthesis available through the existing localhost service contracts
- keep the manifest as the primary voice registry source
- keep backend readiness and startup errors truthful in health and startup behavior
- keep chunk planning, long-text streaming, resume/continue behavior, and
  cancellation semantics explicit, tested, and documented
- make Windows first-run and per-user service/autostart setup reviewable,
  removable, and validated without requiring machine-wide privileges
- make model download/install/activate/remove flows safe, documented, and
  checksum-aware
- keep the Chrome extension installable, localhost-bound, and able to read long
  pages through chunked streaming
- document model asset layout, manifest conventions, backend modes, setup
  expectations, and release validation clearly enough for humans and Codex
- keep benchmark coverage for HTTP, streaming, and async job flows
- run a final security-focused pass before declaring v1 complete; use Codex
  Security workflows and subagents when they improve repository-wide or
  cross-cutting coverage

## Done When

The current initiative is done only when all of the following are true:

1. The local server can run the intended TTS pipeline through the stable
   localhost HTTP and WebSocket contracts.
2. Long page reading through the Chrome extension is covered by structural and
   service-level smoke checks.
3. Model management covers catalog listing, download/install, activation,
   checks, removal, checksum behavior, and safe archive handling.
4. Windows first-run, bundle install, launchers, and per-user Task Scheduler
   service/autostart contracts are documented and tested.
5. Security defaults for localhost binding, token auth, origin validation,
   model archive extraction, extension base URL handling, and release packaging
   are verified.
6. A final security-focused review has been run and any accepted findings are
   fixed or explicitly recorded as follow-up work.
7. Documentation is updated to match the actual repo behavior.
8. Relevant automated validation passes:
   - `python3 -m pytest -q`
   - `python3 -m ruff check .`
   - `python3 scripts/release_check.py`
   - `python3 scripts/check_v1_readiness.py`
9. Repo-level definition of done from `AGENTS.md` is satisfied:
   - code is implemented and understandable
   - relevant tests exist and pass
   - public contracts are explicit
   - documentation is updated when architecture or workflow changes
   - logging and failure modes are reasonable for the current phase

## Demo And Run Expectations

Expected local workflow:

1. Create a virtual environment and install `.[dev]`.
2. Copy `config/config.example.toml` to `config/config.toml`.
3. Ensure the token file and manifest-backed voice setup exist locally.
4. Start the service with `python3 scripts/dev_run.py`, `tts serve`, or the
   Windows launcher scripts.
5. Smoke-test the public contract with commands such as:
   - `tts health`
   - `tts list-voices`
   - `tts catalog-list`
   - `tts model-install vits-piper-en_US-lessac-medium --activate`
   - `tts save "Hello world" --out out.wav --token "$TTS_PLATFORM_TOKEN"`
   - `tts stream "Hello world" --out stream.wav --token "$TTS_PLATFORM_TOKEN"`
   - `python3 scripts/benchmark.py --mode http --token "$TTS_PLATFORM_TOKEN"`
   - `python3 scripts/benchmark.py --mode stream --token "$TTS_PLATFORM_TOKEN"`
   - `python3 scripts/benchmark.py --mode job --token "$TTS_PLATFORM_TOKEN"`
6. On Windows, optionally install the user-scoped autostart task with
   `tts service-install --user`, inspect it with `tts service-status --user`,
   and remove it with `tts service-remove --user`.

Optional browser prototype validation keeps the service running on a localhost URL Chrome can reach, allow-lists the extension origin, and uses `python3 scripts/check_extension.py` plus manual popup/playback checks.

## Important Repo-Specific Assumptions

- This is a small monorepo with service code in `apps/tts_service`, shared core code in `packages/tts_core`, browser code in `apps/chrome_extension`, config in `config/`, and voice metadata in `models/`.
- The final intended platform for the project is Windows. The current Codex session may run inside WSL, which is a development environment detail rather than the deployment target.
- `models/MANIFEST.json` is the primary voice registry source.
- The current example config uses `sherpa-en-debug` as the default voice, not the older `kokoro-en-heart` examples from the original design document.
- Backend runtime modes are `stub`, `auto`, and `real`.
- Tests can exercise the real-backend path through a fake in-test `sherpa_onnx` runtime instead of requiring heavyweight model downloads in the normal suite.
- Browser WebSocket clients may send the bearer token in the first `start` event because standard browser clients cannot attach arbitrary `Authorization` headers. This is a deliberate localhost-only compromise, not a general API expansion.
- Chrome/MV3 smoke coverage is skip-aware by default because branded Chrome may
  reject command-line unpacked extension loading; strict evidence can be
  required with the browser flags documented in `Documentation.md`.
- `docs/codex/Prompt.md`, `docs/codex/Plan.md`, `docs/codex/Implement.md`, and `docs/codex/Documentation.md` are now the Codex-oriented workflow source of truth.
- `docs/sapi_bridge.md` records the post-v1 Windows SAPI/TextAloud bridge plan.
