# Document Import

This package is reserved for offline, structure-preserving Reader Workstation
document import.

Importers will parse supported source formats into ordered sections and blocks,
preserve source metadata and warnings, apply explicit quotas, and avoid fetching
remote resources or executing active content.

The package must not own the Reader database, HTTP routes, desktop UI, speech
rules, or synthesis backends.

Milestone 0 contains no importer feature code or runtime dependencies.
