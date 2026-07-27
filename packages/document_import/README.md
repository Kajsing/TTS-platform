# Document Import

This package owns offline, structure-preserving Reader Workstation document
import for TXT, Markdown, HTML/HTM, DOCX, and EPUB.

Importers parse supported source formats into ordered sections and blocks,
preserve source metadata and warnings, apply explicit file, expansion, member,
character, block, and time quotas, and never fetch remote resources or execute
active content. DOCX and EPUB are parsed directly with Python's standard ZIP and
XML libraries. Archive traversal, links, encryption, duplicate member names,
DTD/entity declarations, and excessive expansion are rejected.

The API is intentionally small: construct an `ImportSource`, optional
`ImportOptions` and `ImportLimits`, then call `import_document`. A threading
event can cancel parsing. Results contain immutable sections, blocks, warnings,
source hashes, and non-sensitive import metadata.

The package does not own the Reader database, HTTP routes, desktop UI, speech
rules, or synthesis backends.

The parsers use only the Python standard library. Multipart HTTP ingestion is
provided by `python-multipart` in the service layer; its Apache-2.0 license and
pinned version range are recorded in the repository notices.
