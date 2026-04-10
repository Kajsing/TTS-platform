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
