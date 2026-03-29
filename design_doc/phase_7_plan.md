# Phase 7 Plan: Real Backend Integration

## Purpose

Phase 7 replaces the deterministic development synthesizer with real `sherpa-onnx` inference while preserving the current public service contract.

The goal is not to redesign the platform. The goal is to make the existing platform real:

- keep the localhost HTTP and WebSocket API stable
- keep the current CLI and Chrome extension integration path working
- keep backend-specific concerns inside the backend and infrastructure layers
- make readiness, latency, streaming, and cancellation semantics more truthful

## Why Phase 7 Comes Next

Phases 1 through 6 established the platform shape:

- repository structure and architecture boundaries
- manifest-backed voice discovery
- localhost security controls
- synchronous synthesis, async jobs, and streaming contracts
- observability baselines
- a browser prototype that already consumes the current service contract

The main remaining gap is that the default backend is still a deterministic development implementation rather than real model inference.

Phase 7 should therefore focus on backend realism, not on adding another client surface.

## Phase Goal

Deliver real `sherpa-onnx`-backed synthesis for sync, async, and streaming flows without breaking the existing API contracts.

## Success Criteria

Phase 7 is successful when:

- the default synthesis path uses real `sherpa-onnx` inference instead of the stub renderer
- `/v1/tts`, `/v1/tts/jobs`, and `WS /v1/tts/stream` continue to work with the same request and response shapes
- backend readiness and startup failures are reported clearly in health output
- the voice manifest can resolve to real local model assets
- running-job and active-stream cancellation semantics are explicit and tested
- benchmarks and observability reflect real backend latency characteristics

## Non-Goals

Phase 7 should not include:

- introducing multiple new backend families
- major Chrome extension UX redesign
- distributed job execution or persistent job storage
- cloud deployment work
- installer or packaging automation for end users
- full reader-mode text extraction improvements

These may become later phases, but they should not compete with the backend integration milestone.

## Core Principles

Phase 7 should preserve the repository's existing design principles:

1. Offline-first remains the default operating mode.
2. Public contracts stay stable even if backend internals change.
3. Backend-specific details do not leak into API schemas.
4. Localhost security remains part of the product baseline.
5. Incremental, reviewable changes are preferred over a broad rewrite.

## Scope

### In Scope

- real `sherpa-onnx` runtime integration
- local model and voice asset resolution
- meaningful backend warmup and readiness checks
- real synchronous synthesis
- real async job execution on the true backend path
- real streaming behavior from the true backend path
- clearer cancellation semantics for running work
- improved backend-facing observability and benchmark coverage
- documentation updates for model setup and backend operation

### Explicitly Out of Scope

- cross-machine orchestration
- browser-side model management
- browser-only service endpoints
- advanced SSML expansion
- broad prosody-feature expansion beyond what the backend can actually support

## Proposed Deliverables

### 1. Real Backend Runtime Integration

Add a real `sherpa-onnx` backend implementation behind the existing backend contract.

Expected outcomes:

- the backend loads required model assets from local disk
- voice descriptors resolve to concrete backend resources
- warmup validates that the configured default voice is actually usable
- backend failures surface as structured service errors rather than low-level trace noise

### 2. Manifest-to-Model Binding

Extend the manifest-driven voice flow so a voice entry can be mapped to the assets needed by the real backend.

Expected outcomes:

- `models/MANIFEST.json` remains the primary registry source
- manifest fields stay backend-agnostic at the API level
- backend-specific asset resolution stays in the backend or infrastructure layer
- missing or invalid model assets fail early and clearly

### 3. Truthful Readiness and Startup Behavior

Make startup and health reporting reflect actual backend state instead of only contract-level availability.

Expected outcomes:

- health can distinguish process status from backend readiness
- startup errors identify model-loading or warmup failures clearly
- default voice readiness is based on real backend validation
- the service remains debuggable when a model path or voice asset is wrong

### 4. Real Sync and Async Synthesis

Preserve the current HTTP and job lifecycle contracts while routing real synthesis through them.

Expected outcomes:

- `/v1/tts` returns real backend audio
- `/v1/tts/jobs` and result retrieval keep the same API shape
- job failures reflect real backend failure cases
- timeout and cancellation semantics are revisited based on true runtime behavior

### 5. Chunk-Planned Streaming

Introduce a first-class chunk-planning domain component so streaming is driven by planned text chunks rather than only a single flattened request and PCM slicing.

Expected outcomes:

- chunk planning becomes an explicit domain object
- stream-first behavior can be tuned separately from sync synthesis behavior
- chunk metadata can support pause hints and future playback improvements
- browser buffering behavior can later rely on more meaningful stream structure

This does not require a full prosody engine. It does require making chunk planning real and explicit.

### 6. Cancellation Semantics Rework

Clarify what cancellation means for:

- queued jobs
- running jobs
- active streams
- backend work already in progress

Expected outcomes:

- best-effort cancellation is documented where hard interruption is not possible
- terminal job states remain consistent
- stream cancellation behavior is testable and observable
- the backend contract makes cancellation expectations explicit

### 7. Observability and Benchmark Expansion

Extend current health-snapshot and logging baselines so the real backend can be measured usefully.

Expected outcomes:

- meaningful first-audio and end-to-end latency measurement
- backend readiness and warmup signals
- job outcome visibility under real inference
- benchmark coverage for async job flow in addition to sync HTTP and streaming

## Architecture Impact

Phase 7 should keep the current high-level layering:

- API layer: unchanged request and response contracts
- application layer: orchestration, job flow, streaming coordination
- domain layer: chunk planning, synthesis request preparation, voice selection
- infrastructure layer: model loading, backend runtime, filesystem access, backend-specific errors

The main architectural addition should be a dedicated chunk-planning component in the domain layer.

## Proposed Implementation Sequence

### Phase 7.1: Backend Bootstrap and Asset Resolution

- add backend-facing model asset resolution
- validate manifest-to-model mapping
- make warmup and readiness meaningful
- add startup and health tests for missing or broken assets

### Phase 7.2: Real Sync Synthesis

- replace stub audio generation on the sync path
- preserve the existing `/v1/tts` contract
- add tests for real backend success and failure paths

### Phase 7.3: Real Async Jobs

- route async jobs through the real backend
- revisit time limits and running-job cancellation expectations
- extend job-focused tests and benchmark support

### Phase 7.4: Chunk-Planned Streaming

- add a domain-level chunk-planning component
- connect streaming execution to the chunk plan
- preserve existing WebSocket event shapes where possible
- verify first-audio behavior and stream cancellation under real runtime conditions

### Phase 7.5: Observability, Benchmarks, and Docs

- add real backend metrics and structured logging improvements
- expand benchmark coverage
- document model setup, known limits, and operational workflow
- update status documents that still describe older project phases

## Testing Strategy

Phase 7 should add or update tests for:

- manifest entries that resolve to missing model assets
- startup warmup failures
- backend-ready versus backend-not-ready health states
- sync synthesis on the real backend path
- async jobs on the real backend path
- stream startup, first chunk, completion, and cancellation on the real backend path
- timeout or long-running behavior where relevant
- chunk-planning behavior and boundaries

The current public-contract tests should remain valuable and should be preserved wherever possible.

## Documentation Deliverables

Phase 7 should update:

- `README.md`
- `ARCHITECTURE.md`
- `TESTING.md`
- `SECURITY.md` if browser auth or local assumptions change
- config examples if model paths or backend settings are added

Phase 7 should also document:

- required model files
- expected manifest conventions
- warmup and readiness behavior
- current cancellation guarantees and limits

## Risks

### Risk: Backend integration breaks stable contracts

Mitigation:

- keep existing request and response schemas unchanged unless a clear contract bug is discovered
- use current API and CLI tests as contract guards

### Risk: Model-specific details leak into API design

Mitigation:

- keep model resolution and runtime concerns in backend and infrastructure code
- continue using the manifest and backend interface as the abstraction boundary

### Risk: Streaming becomes harder to reason about

Mitigation:

- add chunk planning as an explicit domain concept instead of burying logic in the WebSocket handler
- preserve the current control-event-plus-binary-frame protocol

### Risk: Cancellation promises exceed backend reality

Mitigation:

- document best-effort behavior honestly
- test terminal-state consistency even when hard interruption is limited

## Definition of Done

Phase 7 is done when:

- the stub synthesizer is no longer the default synthesis implementation
- real `sherpa-onnx` inference powers sync, async, and streaming flows
- public contracts remain stable for HTTP, jobs, CLI, and browser streaming
- backend readiness is visible and truthful in health output
- chunk planning exists as a first-class domain component
- cancellation behavior is explicit, tested, and documented
- benchmarks cover the real backend path
- operational and architecture documentation are updated

## Suggested Follow-Up Phase Candidates

If Phase 7 succeeds, the most likely Phase 8 directions are:

- packaging and local model installation workflow
- stronger metrics export and long-running observability
- richer browser automation and extension test coverage
- additional backend implementations behind the same contract
