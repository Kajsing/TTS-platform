# Tasks

For ongoing Codex execution order, use `docs/codex/Plan.md` as the source of truth. This file remains the historical phase checklist and should stay aligned with the plan.

## Phase 1

- [x] Create repository skeleton
- [x] Add `AGENTS.md`
- [x] Add central config model
- [x] Add voice registry
- [x] Add backend interface
- [x] Add `sherpa-onnx` backend stub

## Phase 2

- [x] Implement text normalization
- [x] Implement segmentation
- [x] Add `/v1/health`
- [x] Add `/v1/voices`
- [x] Add `/v1/tts`
- [x] Add WAV output flow

## Phase 3

- [x] Add job manager
- [x] Add token auth
- [x] Add origin control
- [x] Add rate limiting
- [x] Add cancellation

## Phase 4

- [x] Add WebSocket endpoint
- [x] Add PCM chunk delivery
- [x] Add streaming metrics
- [x] Add cancellation during stream

## Phase 5

- [x] Add benchmark script
- [x] Add broader observability
- [x] Add audio regression tests
- [x] Add CLI

## Phase 6

- [x] Add MV3 prototype
- [x] Add offscreen playback
- [x] Add jitter buffer
- [x] Add extension auth flow

## Phase 7

- [x] Add backend runtime config with `stub` / `auto` / `real` modes
- [x] Add manifest-side backend asset binding for real `sherpa-onnx` voices
- [x] Make backend readiness and startup errors more truthful
- [x] Add backend status snapshot to `/v1/health`
- [x] Prove the real sync path with a fake `sherpa_onnx` runtime in tests
- [x] Prove the real async job path with a fake `sherpa_onnx` runtime in tests
- [x] Prove the real streaming path with a fake `sherpa_onnx` runtime in tests
- [x] Add async job benchmarking mode to `scripts/benchmark.py`
- [x] Add a first-class chunk planning component in `tts_core`
- [x] Route sync, jobs, and streaming through the shared chunk-planning flow
- [x] Improve chunk-plan heuristics beyond sentence grouping and simple pause hints
- [x] Revisit streaming to support true incremental backend generation instead of chunk synthesize plus frame slicing
- [x] Tighten cancellation semantics for running real-backend work
- [x] Add stronger docs for model asset layout, manifest conventions, and backend setup

## V1 Reader Track

- [x] Add a separate long-text WebSocket stream limit for page-scale playback
- [x] Add reader progress/resume semantics for long page playback
- [x] Add richer extension UX for resuming from saved reader progress
- [x] Add `model-install --activate` first-run shortcut and install guidance output
- [x] Improve catalog listing and install progress output
- [x] Add Windows-friendly local first-run setup helper
- [x] Add Windows-friendly service run command
- [x] Add Windows-friendly service launcher scripts
- [ ] Add Windows-friendly service install/packaging flow
- [x] Add Chrome extension popup setup checklist
- [x] Add Chrome extension zip packaging script
- [x] Harden allowed-origin config validation
- [ ] Close release-hardening gaps for docs, security defaults, and tests
