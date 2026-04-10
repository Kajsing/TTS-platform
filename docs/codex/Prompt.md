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

Build and finish an offline-first local text-to-speech platform with:

- a stable localhost HTTP API
- protected async job flows
- protected WebSocket streaming
- a public-contract CLI
- a browser prototype that stays isolated in `apps/chrome_extension/`
- a backend architecture that can use real `sherpa-onnx` inference without changing public API contracts

The current long-horizon objective is to finish Phase 7 by making the real backend path, chunk-planned execution, streaming behavior, cancellation semantics, and operator documentation complete and truthful.

## Non-Goals

The current initiative does not include:

- adding new backend families beyond `sherpa-onnx`
- redesigning the public HTTP or WebSocket contract without a clear contract bug
- moving browser-specific logic into the localhost service
- distributed job execution or persistent job storage
- cloud-first deployment work
- installer or packaging automation for end users
- a major Chrome extension UX redesign
- full reader-mode extraction, advanced SSML parity, or speculative prosody features that the current backend cannot support

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

The project must preserve the already-built platform surface and complete the remaining Phase 7 work:

- keep sync, job, and streaming synthesis available through the existing localhost service contracts
- keep the manifest as the primary voice registry source
- keep backend readiness and startup errors truthful in health and startup behavior
- improve chunk-plan heuristics beyond simple sentence grouping and pause hints
- move streaming closer to true incremental backend generation instead of only planned-chunk synthesis plus PCM frame slicing
- tighten and document cancellation semantics for queued jobs, running jobs, active streams, and in-flight backend work
- document model asset layout, manifest conventions, backend modes, and setup expectations clearly enough for humans and Codex
- keep benchmark coverage for HTTP, streaming, and async job flows

## Done When

The current initiative is done only when all of the following are true:

1. The remaining open Phase 7 items from `TASKS.md` are complete.
2. Real `sherpa-onnx` inference powers the intended sync, async, and streaming paths without breaking public contracts.
3. Chunk planning remains a first-class domain concept and its heuristics are no longer limited to the initial simple pass.
4. Streaming is no longer only "synthesize a full planned chunk and slice PCM frames" unless that limitation is explicitly retained, tested, and recorded as unfinished work in `Documentation.md`.
5. Cancellation behavior is explicit, tested, and documented for queued jobs, running jobs, and active streams.
6. Model/setup/backend documentation is updated to match the actual repo behavior.
7. Relevant automated validation passes:
   - `python3 -m pytest -q`
   - `python3 -m ruff check .`
8. Repo-level definition of done from `AGENTS.md` is satisfied:
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
4. Start the service with `python3 scripts/dev_run.py`.
5. Smoke-test the public contract with commands such as:
   - `tts health`
   - `tts list-voices`
   - `tts save "Hello world" --out out.wav --token "$TTS_PLATFORM_TOKEN"`
   - `tts stream "Hello world" --out stream.wav --token "$TTS_PLATFORM_TOKEN"`
   - `python3 scripts/benchmark.py --mode http --token "$TTS_PLATFORM_TOKEN"`
   - `python3 scripts/benchmark.py --mode stream --token "$TTS_PLATFORM_TOKEN"`
   - `python3 scripts/benchmark.py --mode job --token "$TTS_PLATFORM_TOKEN"`

Optional browser prototype validation keeps the service running on a localhost URL Chrome can reach, allow-lists the extension origin, and uses `python3 scripts/check_extension.py` plus manual popup/playback checks.

## Important Repo-Specific Assumptions

- This is a small monorepo with service code in `apps/tts_service`, shared core code in `packages/tts_core`, browser code in `apps/chrome_extension`, config in `config/`, and voice metadata in `models/`.
- The final intended platform for the project is Windows. The current Codex session may run inside WSL, which is a development environment detail rather than the deployment target.
- `models/MANIFEST.json` is the primary voice registry source.
- The current example config uses `sherpa-en-debug` as the default voice, not the older `kokoro-en-heart` examples from the original design document.
- Backend runtime modes are `stub`, `auto`, and `real`.
- Tests can exercise the real-backend path through a fake in-test `sherpa_onnx` runtime instead of requiring heavyweight model downloads in the normal suite.
- Browser WebSocket clients may send the bearer token in the first `start` event because standard browser clients cannot attach arbitrary `Authorization` headers. This is a deliberate localhost-only compromise, not a general API expansion.
- There is still no full automated MV3 test harness in the repo. The extension currently relies on manual verification plus `python3 scripts/check_extension.py`.
- `docs/codex/Prompt.md`, `docs/codex/Plan.md`, `docs/codex/Implement.md`, and `docs/codex/Documentation.md` are now the Codex-oriented workflow source of truth.
