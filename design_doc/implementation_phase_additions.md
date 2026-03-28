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

## Future phases

As later phases are implemented, this file should be extended with:

- implementation-specific behavior that was necessary in practice
- deviations from the original phase checklist
- temporary development substitutions that still preserve the public contract
