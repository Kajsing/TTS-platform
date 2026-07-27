# Speech Rules

This package is reserved for deterministic, backend-agnostic pronunciation and
speech transformation rules for the Reader Workstation.

It will own rule models, compilation, evaluation, preview traces, and source-map
preservation. Its output feeds the existing `tts_core` synthesis pipeline after
Reader structure and stable source spans have been established.

It must not own WPF presentation, FastAPI routes, SQLite repositories, document
parsing, or backend inference.

Milestone 0 contains no speech-rule feature code or runtime dependencies.
