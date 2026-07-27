# Reader Core

This package is reserved for the backend-agnostic Reader Workstation domain and
service-owned persistence foundation.

It will own document, section, block, cursor, bookmark, queue, and related
domain models; repository protocols; explicit SQLite migrations; and SQLite
repository implementations. Domain models use standard-library dataclasses.

It must not depend on FastAPI, WPF, browser behavior, document parser details,
or TTS backend implementations.

Milestone 0 contains no domain feature code or runtime dependencies. Reader
domain and SQLite implementation begins in Reader Milestone 1.
