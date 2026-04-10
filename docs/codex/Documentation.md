# Documentation

This file is the live status log and shared memory for future Codex loops.

## Current Status

- Date: 2026-04-10
- Workflow status: `docs/codex/` has been created as the Codex source of truth for project spec, execution order, operating rules, and resume context.
- Project status: Phases 1 through 6 are complete. Phase 7 is partially complete and is the active long-horizon implementation target.
- Runtime context: the intended end platform is Windows, while the current Codex environment is WSL.
- Current loop result: Milestone 2 is complete at the service orchestration layer, while the stricter Phase 7 streaming follow-up in `TASKS.md` remains open.
- Validation status for the current loop:
  - `python3 -m pytest -q packages/tts_core/tests/test_sherpa_onnx_backend.py apps/tts_service/tests/test_streaming.py apps/tts_service/tests/test_api.py` passed.
  - `python3 -m pytest -q` passed with 65 tests.
  - `python3 -m ruff check .` passed.
  - `python3 scripts/check_extension.py` passed, with JavaScript syntax checks skipped because `node` is not installed.

## What Is Done

- Repo guidance, config loading, voice registry, backend abstraction, and service bootstrap exist.
- Stable localhost HTTP endpoints exist for health, voices, sync TTS, async jobs, job status, job cancellation, and job result retrieval.
- Token auth, token rotation, origin filtering, rate limiting, and localhost security baselines exist.
- WebSocket streaming exists with JSON control events and binary PCM16 frames.
- Observability, CLI tooling, benchmark modes, and audio regression tests exist.
- Chrome MV3 prototype work exists in `apps/chrome_extension/`.
- Phase 7 work already completed includes backend runtime config (`stub` / `auto` / `real`), manifest-side backend asset binding, more truthful backend readiness, health backend snapshots, fake-runtime coverage for sync/jobs/streaming, async job benchmarking, and a first chunk-planning component shared across sync/jobs/streaming.
- Milestone 1 is now complete:
  - `ChunkPlanner` can split long sentence-level segments at clause boundaries before the hard max when that produces a better early chunk.
  - oversized segments without clause punctuation now fall back to whitespace-aware hard-limit splitting.
  - split subchunks are kept explicit instead of being immediately merged back into a larger chunk.
  - tests now cover core chunk-boundary behavior plus service-level use of the shared chunk-planning entry point.
- Milestone 2 is now complete at the service layer:
  - `SynthesisService` streams through `backend.synthesize_stream()` instead of synthesizing WAV per planned chunk and slicing decoded PCM locally.
  - service streaming now remaps backend-local chunk indices into one global stream index sequence across the whole chunk plan.
  - service streaming validates sample-rate/channel consistency across streamed backend chunks.
  - regression coverage now fails if stream execution falls back to `backend.synthesize()` instead of the backend streaming contract.
- This Codex memory structure is now in place:
  - `docs/codex/Prompt.md`
  - `docs/codex/Plan.md`
  - `docs/codex/Implement.md`
  - `docs/codex/Documentation.md`

## What Is Next

- Milestone 3 from `Plan.md`: tighten cancellation semantics for running work.
- After that, finish backend/model/setup documentation closeout.
- The open Phase 7 streaming item in `TASKS.md` still needs backend-level work if the project wants true runtime-incremental generation instead of backend-side full-PCM generation followed by chunk emission.
- Milestone 5 closeout remains blocked on Milestones 3 and 4, plus the remaining open Phase 7 streaming task in `TASKS.md`.

## Decisions Made And Why

- `docs/codex/` is now the Codex-oriented source of truth so future loops do not have to rediscover scattered instructions.
- `AGENTS.md` remains the entry point for repo rules, but it now points directly to the four Codex workflow files.
- Later phase trackers were treated as stronger than older summary docs when they conflicted.
- Existing legacy docs were mostly left in place as reference material to avoid disruptive rewrites.
- Windows is now recorded explicitly as the final target platform so future loops do not overfit to the current WSL development environment.
- The chunk-plan improvement was implemented inside `ChunkPlanner` only, without changing public API schemas or service orchestration, so sync/jobs/streaming continue to share the same `prepare_request` entry point.
- This loop stayed focused on the Milestone 2 streaming architecture slice and did not start Milestone 3, even though the user allowed "more if you think you can handle it", because the repo runbook prefers validated milestone-sized slices over bundling unrelated behavioral changes.
- The service now uses the backend streaming contract as its primary streaming path. The remaining limitation is explicitly preserved: the current `SherpaOnnxBackend.synthesize_stream()` implementation still generates full PCM before chunk emission for the stub path and current fake-runtime path.

## Commands To Run And Smoke Test

Baseline validation:

```bash
python3 -m pytest -q
python3 -m ruff check .
```

Service start:

```bash
python3 scripts/dev_run.py
```

Public-contract smoke commands after the service is running:

```bash
tts health
tts list-voices
tts save "Hello world" --out out.wav --token "$TTS_PLATFORM_TOKEN"
tts stream "Hello world" --out stream.wav --token "$TTS_PLATFORM_TOKEN"
python3 scripts/benchmark.py --mode http --token "$TTS_PLATFORM_TOKEN"
python3 scripts/benchmark.py --mode stream --token "$TTS_PLATFORM_TOKEN"
python3 scripts/benchmark.py --mode job --token "$TTS_PLATFORM_TOKEN"
```

Extension structural smoke:

```bash
python3 scripts/check_extension.py
```

## Known Issues And Follow-Ups

- `README.md` previously presented a Phase 6 status snapshot, while `TASKS.md` and the Phase 7 notes showed additional completed work. The new Codex docs treat the later Phase 7 sources as stronger.
- `ARCHITECTURE.md` still describes a much earlier architecture snapshot centered on Phase 2. Use it as background only.
- The original design doc uses `kokoro-en-heart` in examples, but the current manifest and config example use `sherpa-en-debug`.
- WSL is the current working environment, but it must not silently become the assumed target platform in code or documentation.
- The service-layer streaming path no longer decodes WAV and slices PCM locally, but the backend still needs follow-up for true runtime-incremental generation.
- Running-work cancellation on the real backend path still needs clearer semantics and stronger coverage.
- The browser prototype still depends on manual Chrome loading and manual allow-list setup.
- There is still no full automated MV3 test harness in the repository.
- `python3 scripts/check_extension.py` still cannot perform JavaScript syntax checks in this environment because `node` is not installed.

## Resume Instructions For The Next Codex Loop

1. Open `docs/codex/Prompt.md`, `docs/codex/Plan.md`, and `docs/codex/Implement.md`.
2. Check this file for current status and any newly recorded blockers.
3. Start with Milestone 3 unless this file records a deliberate reorder.
4. Keep the next diff narrowly scoped to that milestone.
5. Run the milestone validation commands before claiming completion.
6. Update this file again before handing off.
