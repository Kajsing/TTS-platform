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
