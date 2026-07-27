from __future__ import annotations

from document_import import (
    ImportArchiveUnsafeError,
    ImportCancelledError,
    ImportInvalidError,
    ImportTooLargeError,
    ImportUnsupportedError,
)
from reader_core import (
    ReaderConflictError,
    ReaderDatabaseError,
    ReaderEditHistoryError,
    ReaderMigrationError,
    ReaderNotFoundError,
    ReaderStaleCursorError,
    ReaderValidationError,
)
from speech_rules import SpeechRuleError, SpeechRuleInterchangeError

from .errors import APIError, ErrorBody
from .reader_service import (
    ReaderDocumentLockedError,
    ReaderDuplicateDocumentError,
    ReaderImportPreviewCapacityError,
    ReaderImportPreviewNotFoundError,
)


def reader_api_error(
    error_type: str,
    *,
    status_code: int,
    message: str,
    param: str | None = None,
    details: dict[str, object] | None = None,
) -> APIError:
    return APIError(
        status_code=status_code,
        error=ErrorBody(
            type=error_type,
            message=message,
            param=param,
            details=details or {},
        ),
    )


def reader_disabled() -> APIError:
    return reader_api_error(
        "reader_disabled",
        status_code=503,
        message="Reader features are disabled.",
    )


def reader_database_unavailable() -> APIError:
    return reader_api_error(
        "reader_database_unavailable",
        status_code=503,
        message="Reader storage is unavailable.",
    )


def translate_reader_error(
    error: Exception,
    *,
    missing_entity: str = "document",
    cursor_input: bool = False,
) -> APIError:
    if isinstance(error, ReaderDuplicateDocumentError):
        return reader_api_error(
            "reader_duplicate_document",
            status_code=409,
            message="An identical Reader document already exists.",
            details={"document_id": error.document_id},
        )
    if isinstance(error, ReaderDocumentLockedError):
        return reader_api_error(
            "reader_document_locked",
            status_code=409,
            message="Reader content is locked by active playback. Pause or stop before editing.",
            details={"document_id": error.document_id},
        )
    if isinstance(error, ReaderConflictError):
        return reader_api_error(
            "reader_revision_conflict",
            status_code=409,
            message="The Reader entity was changed by another operation.",
            details={
                "entity_id": error.entity_id,
                "expected_row_version": error.expected,
                "actual_row_version": error.actual,
            },
        )
    if isinstance(error, ReaderStaleCursorError):
        return reader_api_error(
            "reader_stale_cursor",
            status_code=409,
            message="The Reader cursor cannot be mapped to the current content revision.",
        )
    if isinstance(error, ReaderNotFoundError):
        error_type = {
            "block": "reader_block_not_found",
            "document": "reader_document_not_found",
        }.get(missing_entity, "reader_conflict")
        return reader_api_error(
            error_type,
            status_code=404,
            message=f"Reader {missing_entity} was not found.",
        )
    if isinstance(error, ReaderEditHistoryError):
        return reader_api_error(
            "reader_conflict",
            status_code=409,
            message="The requested Reader history operation is not available.",
        )
    if isinstance(error, ReaderValidationError):
        return reader_api_error(
            "reader_invalid_cursor" if cursor_input else "reader_conflict",
            status_code=400,
            message=(
                "The Reader cursor is invalid."
                if cursor_input
                else "The Reader request violates a content or state constraint."
            ),
        )
    if isinstance(error, ReaderDatabaseError):
        is_busy = "locked" in str(error).lower() or "busy" in str(error).lower()
        return reader_api_error(
            "reader_database_busy" if is_busy else "reader_database_unavailable",
            status_code=503,
            message=(
                "Reader storage is busy; retry the operation."
                if is_busy
                else "Reader storage is unavailable."
            ),
        )
    if isinstance(error, ReaderMigrationError):
        return reader_database_unavailable()
    return reader_api_error(
        "reader_database_unavailable",
        status_code=503,
        message="Reader storage is unavailable.",
    )


def translate_import_error(error: Exception) -> APIError:
    if isinstance(error, ImportUnsupportedError):
        return reader_api_error(
            "reader_import_unsupported",
            status_code=415,
            message="The selected document format is not supported.",
        )
    if isinstance(error, ImportTooLargeError):
        return reader_api_error(
            "reader_import_too_large",
            status_code=413,
            message="The imported document exceeds a configured safety limit.",
        )
    if isinstance(error, ImportArchiveUnsafeError):
        return reader_api_error(
            "reader_archive_unsafe",
            status_code=400,
            message="The imported archive contains unsafe content or paths.",
        )
    if isinstance(error, ImportCancelledError):
        return reader_api_error(
            "reader_import_cancelled",
            status_code=409,
            message="The document import was cancelled.",
        )
    if isinstance(error, (ImportInvalidError, ReaderImportPreviewNotFoundError)):
        return reader_api_error(
            "reader_import_invalid",
            status_code=404 if isinstance(error, ReaderImportPreviewNotFoundError) else 400,
            message=(
                "The import preview no longer exists. Preview the file again."
                if isinstance(error, ReaderImportPreviewNotFoundError)
                else "The imported document is invalid or contains no readable text."
            ),
        )
    if isinstance(error, ReaderImportPreviewCapacityError):
        return reader_api_error(
            "reader_conflict",
            status_code=409,
            message="Another large import preview is still active. Cancel or finish it first.",
        )
    return reader_api_error(
        "reader_import_invalid",
        status_code=400,
        message="The document could not be imported.",
    )


def translate_rule_error(error: SpeechRuleError) -> APIError:
    return reader_api_error(
        "reader_rule_invalid",
        status_code=400,
        message=(
            "The rule interchange file is invalid or unsupported."
            if isinstance(error, SpeechRuleInterchangeError)
            else "The speech rule is invalid or exceeds a safety limit."
        ),
    )
