# Reader Core

This package contains the backend-agnostic Reader Workstation domain and
service-owned persistence foundation.

It owns document, section, block, cursor, bookmark, queue, and related
domain models; repository protocols; explicit SQLite migrations; and SQLite
repository implementations. Domain models use standard-library dataclasses.

It must not depend on FastAPI, WPF, browser behavior, document parser details,
or TTS backend implementations.

It uses only the Python standard library. SQLite storage lives behind repository
protocols so future API-based multi-computer sharing does not leak database
details into domain or client contracts.

Metadata fields accept JSON objects up to 64 KiB and should contain only small,
documented format or workflow attributes. Raw source content and binary data
belong in blocks or managed files, not metadata.
