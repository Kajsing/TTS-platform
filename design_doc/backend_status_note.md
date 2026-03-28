# Backend Status Note

## Current backend state

The repository currently uses a deterministic development implementation behind the `sherpa-onnx` backend contract.

This means:

- the service exposes the same public synthesis contract as the intended real backend
- `/v1/tts` returns valid WAV audio
- `/v1/tts/jobs` can execute and complete jobs end-to-end
- no external model download is required to develop or test the service

## What it is not

The current backend is not real ONNX model inference.

It does not yet provide:

- actual `sherpa-onnx` runtime integration
- real voice-specific acoustic behavior
- real model-backed streaming audio generation
- backend-level cancellation of in-flight synthesis
- production-grade latency or audio quality characteristics

## Why this temporary backend exists

The development backend was introduced so that phases 2 and 3 could stabilize:

- request and response contracts
- health and readiness reporting
- auth and security rules
- job lifecycle handling
- API and integration tests

This keeps platform work moving while preserving the backend abstraction.

## Implications for phase 3

Phase 3 security and job management are considered valid against the current backend because they exercise the service contract, not the final acoustic implementation.

Phase 4 streaming is also considered valid at the contract level because the development backend now emits PCM chunks and supports cooperative cancellation markers, even though the underlying audio generation is still synthetic.

The main limitation is cancellation:

- queued jobs can be cancelled cleanly
- running jobs depend on backend support
- the current development backend does not stop an already running synthesis operation

This is acceptable for now, but real backend integration should revisit cancellation semantics during later backend and streaming phases.

## Next backend milestone

The next backend-focused milestone should replace the deterministic development synthesis path with actual `sherpa-onnx` inference while preserving:

- the existing request schema
- the existing error contract
- the job lifecycle API
- the localhost security model
