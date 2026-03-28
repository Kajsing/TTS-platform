# Architecture

The repository is organized as a small monorepo:

- `packages/tts_core`: shared domain contracts and backend interfaces
- `apps/tts_service`: service application code and configuration loading
- `apps/chrome_extension`: future browser client placeholder

Phase 2 adds the first usable request flow:

- text normalization and sentence segmentation in `tts_core`
- manifest-backed voice discovery during service bootstrap
- a deterministic development synthesis path for WAV output
- FastAPI endpoints for health, voice listing, and basic synthesis

Voice metadata is now expected to come from `models/MANIFEST.json`, with backend-provided voices used as a fallback during bootstrap. This keeps the registry contract explicit and decouples installed voice metadata from backend implementation details.
