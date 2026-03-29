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
- `mark` control events are emitted before audio frames so clients can track stream progress without parsing binary payloads.
- The development backend can now emit PCM chunks incrementally instead of only returning complete WAV files.
- Stream cancellation is supported through a WebSocket `cancel` control event.
- Basic in-memory streaming metrics were added and exposed through health data.
- WebSocket auth, origin checks, and rate limiting reuse the same baseline security policy as protected HTTP endpoints.
- Edge-case tests were added for invalid first events, invalid payloads, and forbidden origins on WebSocket connections.

### Why these additions matter

- They create a concrete streaming contract before browser playback work starts.
- They exercise cancellation and low-latency delivery without waiting for the final backend implementation.
- They provide a measurable first baseline for later streaming performance work.

## Phase 5

### Added implementation details

- Shared audio helpers were added for WAV encoding and structural inspection.
- Structured request and synthesis observability were added, including request ids and aggregated health snapshots.
- A public-contract CLI was added with `health`, `list-voices`, `save`, `say`, and `stream` commands.
- A benchmark script was added to measure HTTP synthesis latency, output duration, and approximate RTF.
- Audio regression tests were added around waveform structure and rate-sensitive duration changes.
- Phase 5.1 extended the CLI with job lifecycle commands and clearer token-related failure handling.
- Phase 5.1 also extended observability with job-level counters and expanded the benchmark script to support streaming mode.

### Why these additions matter

- They improve day-to-day operability without changing the public service contract.
- They make it easier to spot regressions in audio output and request handling.
- They give later browser and performance work a concrete baseline for comparison.

## Phase 6

### Added implementation details

- A first Chrome MV3 prototype was added under `apps/chrome_extension`.
- The prototype uses a popup, background service worker, content script, and offscreen document instead of embedding browser behavior in the localhost service.
- Offscreen playback now consumes the existing WebSocket streaming contract and schedules PCM chunks with a small local prebuffer.
- The browser prototype stores localhost client settings such as base URL, token, preferred voice, buffer thresholds, and page-text limits.
- The WebSocket streaming contract was extended in practice to accept the bearer token in the initial `start` event for browser clients that cannot attach `Authorization` headers directly.
- Manual setup guidance was added for allow-listing the extension origin in the service configuration.
- Phase 6.1 added popup-side service health checks and voice discovery so the browser client can inspect the local service instead of relying on manual voice-id entry.
- Phase 6.1 also tightened the client playback loop with session-backed state persistence and simple rebuffering behavior after underruns.
- Phase 6.2 improved page text capture heuristics, added retry-oriented offscreen lifecycle recovery, and introduced a lightweight extension validation script plus troubleshooting note.

### Why these additions matter

- They validate that the current localhost contracts are usable from a real browser environment.
- They keep browser-specific playback and UX concerns isolated from the service core.
- They make the first client integration explicit before later UX or packaging work begins.
- They reduce a few of the sharpest prototype edges without changing the service-domain boundaries.
- They create a more practical maintenance loop for the extension even before a full MV3 automation harness exists.

## Future phases

As later phases are implemented, this file should be extended with:

- implementation-specific behavior that was necessary in practice
- deviations from the original phase checklist
- temporary development substitutions that still preserve the public contract
