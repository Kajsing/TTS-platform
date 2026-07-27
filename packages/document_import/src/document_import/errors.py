from __future__ import annotations


class DocumentImportError(Exception):
    """Base class for safe, user-facing document import failures."""


class ImportUnsupportedError(DocumentImportError):
    pass


class ImportTooLargeError(DocumentImportError):
    pass


class ImportInvalidError(DocumentImportError):
    pass


class ImportArchiveUnsafeError(DocumentImportError):
    pass


class ImportCancelledError(DocumentImportError):
    pass
