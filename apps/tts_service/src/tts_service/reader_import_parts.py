"""Owner import previews and atomic whole-chapter multi-document persistence."""

from __future__ import annotations

import time
import uuid
from dataclasses import replace

from document_import.parts import plan_import_parts, slice_import_part
from reader_core import ReaderValidationError
from reader_core.chapters import CHAPTER_KEY
from reader_core.sqlite.transactions import TransactionRepository

from .reader_privacy import ReaderPrivacyLockedError


class _PartsCommitRejected(Exception):
    """Unwind generator contexts before raising existing frozen error dataclasses."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        super().__init__("Import part commit was rejected")


class ReaderImportPartsMixin:
    def preview_import_parts(
        self,
        preview_id: str,
        *,
        max_characters: int = 900_000,
        heading_level: int = 1,
    ) -> dict:
        with self._import_preview_lock:
            preview = self._parts_import_preview(preview_id)
            plan = plan_import_parts(
                preview.imported,
                max_characters=max_characters,
                heading_level=heading_level,
            )
            return plan.preview(preview_id)

    def commit_import_parts(
        self,
        preview_id: str,
        *,
        plan_key: str,
        max_characters: int = 900_000,
        heading_level: int = 1,
        allow_duplicate: bool = False,
        folder_id: str | None = None,
        privacy_tokens: tuple[str, ...] = (),
    ) -> tuple:
        from .reader_service import (
            ReaderDuplicateDocumentError,
            ReaderImportPreviewNotFoundError,
            _bundle_with_source_uri,
            _reader_bundle_from_import,
        )

        # Serialize commit/cancel/new-parts attempts against this bounded cache.
        # The public operation has no automatic write retry or persisted job.
        with self._import_preview_lock:
            preview = self._parts_import_preview(preview_id)
            plan = plan_import_parts(
                preview.imported,
                max_characters=max_characters,
                heading_level=heading_level,
            )
            if plan.plan_key != plan_key:
                raise ReaderValidationError(
                    "The part preview changed; preview the selected limits again."
                )
            if not plan.can_commit:
                raise ReaderValidationError(
                    "The source cannot be imported with the selected part policy."
                )
            bundles = []
            for part in plan.parts:
                bundle = _reader_bundle_from_import(
                    slice_import_part(preview.imported, part),
                    folder_id=folder_id,
                )
                markers = [
                    {
                        "id": "root"
                        if chapter.number == part.first_chapter
                        else str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"{plan.plan_key}:{part.number}:{chapter.number}",
                            )
                        ),
                        "title": chapter.title[:300].strip() or f"Chapter {chapter.number}",
                        "block_id": bundle.blocks[chapter.start_block - part.start_block].id,
                        "codepoint_offset": 0,
                    }
                    for chapter in plan.chapters
                    if part.first_chapter <= chapter.number <= part.last_chapter
                ]
                metadata = {
                    **dict(bundle.document.metadata),
                    CHAPTER_KEY: markers,
                    "import_parts": {
                        "plan_key": plan.plan_key,
                        "part_number": part.number,
                        "first_chapter": part.first_chapter,
                        "last_chapter": part.last_chapter,
                        "source_first_block": part.start_block,
                        "source_end_block": part.end_block,
                    },
                }
                bundles.append(
                    replace(bundle, document=replace(bundle.document, metadata=metadata))
                )
            managed_path = None
            try:
                with self.repository._write() as connection:
                    bound = TransactionRepository(self.repository, connection)
                    if time.monotonic() - preview.created_at_monotonic >= 600:
                        raise _PartsCommitRejected(ReaderImportPreviewNotFoundError(preview_id))
                    unlocked = self.privacy.unlocked_folder_ids(privacy_tokens)
                    if folder_id is not None:
                        folder = bound.get_folder(folder_id)
                        if folder.privacy_locked and folder_id not in unlocked:
                            raise _PartsCommitRejected(ReaderPrivacyLockedError(folder_id))
                    duplicate = bound.find_document_by_source_hash(
                        preview.imported.source_sha256,
                        unlocked_folder_ids=unlocked,
                    )
                    if duplicate is not None and not allow_duplicate:
                        raise _PartsCommitRejected(ReaderDuplicateDocumentError(duplicate.id))
                    if preview.copy_source_file:
                        if preview.source_data is None:
                            raise ReaderValidationError(
                                "Copied imports require retained source bytes."
                            )
                        managed_path = self._write_managed_source(
                            bundles[0].document.id,
                            preview.imported.source_format,
                            preview.source_data,
                        )
                        bundles = [
                            _bundle_with_source_uri(bundle, f"managed/{managed_path.name}")
                            for bundle in bundles
                        ]
                    documents = tuple(bound.create_document(bundle) for bundle in bundles)
            except _PartsCommitRejected as rejected:
                # These are pre-write rejections; no source copy has been made.
                raise rejected.error from None
            except Exception:
                if managed_path is not None:
                    managed_path.unlink(missing_ok=True)
                raise
            self._import_previews.pop(preview_id, None)
        self._log_import(
            operation="import_parts",
            imported=preview.imported,
            outcome="success",
        )
        return documents

    def _parts_import_preview(self, preview_id):
        from .reader_service import ReaderImportPreviewNotFoundError

        self._purge_import_previews_locked()
        preview = self._import_previews.get(preview_id)
        if preview is None:
            raise ReaderImportPreviewNotFoundError(preview_id)
        return preview
