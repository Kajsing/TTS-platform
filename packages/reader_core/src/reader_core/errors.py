from __future__ import annotations


class ReaderError(Exception):
    """Base error for the Reader domain and persistence layer."""


class ReaderValidationError(ReaderError):
    """Raised when Reader input violates a domain invariant."""


class ReaderNotFoundError(ReaderError):
    """Raised when a requested Reader entity does not exist."""


class ReaderConflictError(ReaderError):
    """Raised when an optimistic concurrency check fails."""

    def __init__(self, entity_id: str, *, expected: int, actual: int) -> None:
        self.entity_id = entity_id
        self.expected = expected
        self.actual = actual
        super().__init__(f"Reader entity {entity_id} has row version {actual}, expected {expected}")


class ReaderStaleCursorError(ReaderError):
    """Raised when a cursor cannot safely resolve against current content."""


class ReaderEditHistoryError(ReaderError):
    """Raised when Undo or Redo has no applicable edit."""


class ReaderMigrationError(ReaderError):
    """Raised when the Reader schema cannot be migrated safely."""


class ReaderDatabaseError(ReaderError):
    """Raised when SQLite cannot satisfy a Reader persistence operation."""


class ReaderConfigurationError(ReaderError):
    """Raised when Reader paths or limits are invalid."""
