# Architecture

The repository is organized as a small monorepo:

- `packages/tts_core`: shared domain contracts and backend interfaces
- `apps/tts_service`: service application code and configuration loading
- `apps/chrome_extension`: future browser client placeholder

Phase 1 intentionally stops before real synthesis or API endpoints. The goal is to establish stable contracts before adding behavior in later phases.

Voice metadata is now expected to come from `models/MANIFEST.json`, with backend-provided voices used as a fallback during bootstrap. This keeps the registry contract explicit and decouples installed voice metadata from backend implementation details.
