# Decisions

## 2026-03-28: Start with a contract-first skeleton

Phase 1 implements the repository skeleton, configuration loading, voice registry, backend protocol, and a `sherpa-onnx` stub before any synthesis logic.

Reasoning:

- It keeps later phases from leaking backend details into the API layer.
- It gives tests a stable place to anchor early.
- It matches the design document's "platform before model" principle.

## 2026-03-28: Use standard-library dataclasses for the core models

The initial core models are implemented with dataclasses instead of a runtime validation framework.

Reasoning:

- The domain layer stays lightweight.
- Validation can remain explicit and readable.
- It avoids coupling the core contracts to the API framework.

## 2026-03-28: Treat the voice manifest as the primary registry source

The service bootstrap now loads voice metadata from `models/MANIFEST.json` and only falls back to backend-provided voices when no manifest voices are present.

Reasoning:

- The voice catalog becomes explicit, inspectable, and versionable.
- The registry no longer depends on backend-specific metadata shape.
- It prepares later phases for multiple backends without changing the API contract.

## 2026-03-28: Use a deterministic development synthesizer for phase 2

The `sherpa-onnx` backend currently generates deterministic WAV audio with a lightweight local synthesizer instead of real model inference.

Reasoning:

- Phase 2 needs a working `/v1/tts` contract and valid audio output.
- The service can now be integration-tested end-to-end without downloading models.
- Later backend work can replace the synthesis internals without changing the API contract.

## 2026-03-28: Use in-memory security and job primitives for phase 3

Phase 3 introduces token auth, origin filtering, rate limiting, and job management using in-memory service components.

Reasoning:

- It keeps the implementation small and locally testable.
- It is enough to validate the service contract and localhost threat model for the MVP stages.
- It avoids overcommitting to persistence and distributed coordination before the platform needs them.

Later phase 3 tightening added token rotation, direct async-result retrieval, and TTL-based cleanup while keeping those same primitives in-memory.

## 2026-03-29: Add streaming as a WebSocket protocol with binary PCM frames

Phase 4 uses a WebSocket endpoint that exchanges JSON control events and binary PCM16 frames.

Reasoning:

- It keeps control metadata separate from audio payloads.
- It matches the design goal of low-latency playback without wrapping each chunk as a mini file.
- It gives later browser playback work a stable protocol to integrate against.

## 2026-03-29: Keep phase 5 tooling on the public service contract

The CLI and benchmark tooling call the public HTTP and WebSocket interfaces rather than importing private service internals.

Reasoning:

- It validates the real client-facing contract.
- It avoids creating a second unofficial integration path.
- It makes the tools useful for both local development and later browser-adjacent testing.

## 2026-03-29: Accept browser streaming auth in the first WebSocket start event

The WebSocket streaming endpoint still supports bearer headers, but it also accepts the token in the initial `start` message for browser-based clients.

Reasoning:

- Standard browser WebSocket clients cannot attach arbitrary `Authorization` headers in the same way as non-browser clients.
- The Chrome extension prototype should reuse the existing streaming endpoint instead of introducing a separate browser-only transport.
- Keeping this compromise scoped to localhost preserves the public contract while acknowledging a browser platform constraint.

## 2026-06-13: Keep Codex workflow guidance in AGENTS.md for now

The repository now treats `AGENTS.md` as the durable source for coding-agent
workflow rules, with `README.md`, `TESTING.md`, and design docs carrying the
human-facing setup and milestone details. The project is not adding a local
`.codex/` config, hooks, rules, or MCP setup yet.

Reasoning:

- The current workflow needs shared guidance more than mechanical enforcement.
- Project-local hooks and rules require trust review and should be introduced
  only when a specific check needs enforcement.
- Different Codex surfaces can work on this repository, so the repo should not
  assume a single CLI/app/GitHub execution path.
- Windows developer machines may need `py -3` or a bundled runtime even though
  the canonical commands remain `python3`-based.
