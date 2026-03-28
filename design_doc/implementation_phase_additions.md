# Implementation Phase Additions

This document records implementation details that were added during development and are not spelled out as explicit checklist items in the main design document. It should be read as a companion to `tts_platform_design_v_2.md`, not a replacement for it.

## Phase 1

### Added implementation details

- A Python workspace layout was created with installable packages for `tts_core` and `tts_service`.
- Central project metadata and tooling were added in `pyproject.toml`.
- Repository guidance files were added: `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `SECURITY.md`, `TASKS.md`, and `TESTING.md`.
- A manifest-based voice metadata flow was added through `models/MANIFEST.json`.
- A first API error contract object was added in the service layer to keep error payloads consistent.
- Application bootstrap was separated from the FastAPI entrypoint to keep startup logic testable.

### Why these additions matter

- They make the repo easier to navigate and safer to extend iteratively.
- They anchor the public contracts before more behavior is added.
- They keep future backend work from leaking into the API layer.

## Phase 2

### Added implementation details

- A lightweight text pipeline was added with normalization and sentence segmentation.
- The `sherpa-onnx` backend stub was upgraded into a deterministic development synthesizer that returns valid WAV audio without requiring downloaded models.
- FastAPI routes were added for `/v1/health`, `/v1/voices`, and `/v1/tts`.
- The health response was extended with readiness-style checks for process status, backend readiness, and default-voice availability.
- FastAPI request validation errors are now translated into the shared JSON error contract instead of returning the default framework-specific error shape.
- Integration tests were added for happy-path synthesis and common invalid-request cases.

### Why these additions matter

- They make the service testable end-to-end before real model inference is integrated.
- They reduce the risk of contract churn when the real backend implementation arrives.
- They provide a better baseline for phase 3 security and job-management work.

## Phase 3

### Added implementation details

- Token bootstrap and token-file loading were added for protected endpoints.
- Write endpoints now enforce bearer-token auth.
- Token rotation was added through a protected local endpoint.
- Origin filtering was added for requests that carry an `Origin` header.
- An in-memory rate limiter was added for protected endpoints.
- An in-memory job manager was added for `/v1/tts/jobs`.
- Job status and cancellation endpoints were added.
- A direct job-result endpoint was added for completed async jobs.
- Completed jobs now use in-memory retention limits and TTL-based cleanup.
- A backend status note was added to document the temporary development backend and its current limits.

### Why these additions matter

- They make the localhost API safer by default.
- They allow asynchronous job orchestration before streaming is introduced.
- They keep token lifecycle and async result retrieval explicit instead of hidden in local files or internal state.
- They prevent the in-memory job table from growing without bounds during development use.
- They make the current backend limitations explicit instead of leaving them implicit in the code.

## Phase 4

### Added implementation details

- A WebSocket endpoint was added at `/v1/tts/stream`.
- The streaming protocol now uses JSON control events and binary PCM16 frames.
- The development backend can now emit PCM chunks incrementally instead of only returning complete WAV files.
- Stream cancellation is supported through a WebSocket `cancel` control event.
- Basic in-memory streaming metrics were added and exposed through health data.
- WebSocket auth, origin checks, and rate limiting reuse the same baseline security policy as protected HTTP endpoints.

### Why these additions matter

- They create a concrete streaming contract before browser playback work starts.
- They exercise cancellation and low-latency delivery without waiting for the final backend implementation.
- They provide a measurable first baseline for later streaming performance work.

## Future phases

As later phases are implemented, this file should be extended with:

- implementation-specific behavior that was necessary in practice
- deviations from the original phase checklist
- temporary development substitutions that still preserve the public contract
