from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import (
    Bookmark,
    DocumentEdit,
    DocumentPage,
    DocumentState,
    ExportPhase,
    ExportStatus,
    PlaybackPosition,
    QueueItem,
    QueueStatus,
    ReaderBlock,
    ReaderCursor,
    ReaderDatabaseReport,
    ReaderDesktopOpenRequest,
    ReaderDocument,
    ReaderDocumentBundle,
    ReaderExportJob,
    SpeechRule,
    SpeechRuleSet,
)


class ReaderRepository(Protocol):
    @property
    def search_available(self) -> bool: ...

    def create_document(self, bundle: ReaderDocumentBundle) -> ReaderDocument: ...

    def get_document(self, document_id: str) -> ReaderDocument: ...

    def get_document_bundle(self, document_id: str) -> ReaderDocumentBundle: ...

    def list_documents(
        self,
        *,
        state: DocumentState | None = None,
        query: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> DocumentPage: ...

    def find_document_by_source_hash(self, source_sha256: str) -> ReaderDocument | None: ...

    def document_counts_by_state(self) -> dict[DocumentState, int]: ...

    def list_blocks(
        self,
        document_id: str,
        *,
        after_ordinal: int = -1,
        limit: int = 200,
    ) -> tuple[ReaderBlock, ...]: ...

    def update_document(
        self,
        document_id: str,
        *,
        expected_row_version: int,
        title: str | None = None,
        state: DocumentState | None = None,
    ) -> ReaderDocument: ...

    def soft_delete_document(
        self,
        document_id: str,
        *,
        expected_row_version: int,
    ) -> ReaderDocument: ...

    def restore_document(
        self,
        document_id: str,
        *,
        expected_row_version: int,
    ) -> ReaderDocument: ...

    def replace_block_text(
        self,
        document_id: str,
        block_id: str,
        *,
        start_offset: int,
        end_offset: int,
        replacement_text: str,
        expected_row_version: int,
    ) -> tuple[ReaderDocument, DocumentEdit]: ...

    def append_text(
        self,
        document_id: str,
        text: str,
        *,
        expected_row_version: int,
    ) -> tuple[ReaderDocument, DocumentEdit]: ...

    def undo(
        self,
        document_id: str,
        *,
        expected_row_version: int,
    ) -> ReaderDocument: ...

    def redo(
        self,
        document_id: str,
        *,
        expected_row_version: int,
    ) -> ReaderDocument: ...

    def clear_edit_history(self, document_id: str) -> None: ...

    def resolve_cursor(self, cursor: ReaderCursor) -> ReaderCursor: ...

    def get_position(self, document_id: str) -> PlaybackPosition | None: ...

    def save_position(
        self,
        position: PlaybackPosition,
        *,
        expected_row_version: int | None = None,
    ) -> PlaybackPosition: ...

    def create_bookmark(self, bookmark: Bookmark) -> Bookmark: ...

    def get_bookmark(self, bookmark_id: str) -> Bookmark: ...

    def list_bookmarks(self, document_id: str) -> tuple[Bookmark, ...]: ...

    def update_bookmark(
        self,
        bookmark_id: str,
        *,
        expected_row_version: int,
        cursor: ReaderCursor | None = None,
        label: str | None = None,
        note: str | None = None,
    ) -> Bookmark: ...

    def delete_bookmark(self, bookmark_id: str, *, expected_row_version: int) -> None: ...

    def add_queue_item(self, item: QueueItem) -> QueueItem: ...

    def list_queue(self) -> tuple[QueueItem, ...]: ...

    def update_queue_item(
        self,
        item_id: str,
        *,
        expected_row_version: int,
        status: QueueStatus,
    ) -> QueueItem: ...

    def remove_queue_item(self, item_id: str, *, expected_row_version: int) -> None: ...

    def reorder_queue(self, item_ids: tuple[str, ...]) -> tuple[QueueItem, ...]: ...

    def activate_queue_item(self, item_id: str) -> QueueItem: ...

    def advance_queue(self, document_id: str) -> QueueItem | None: ...

    def request_desktop_open(
        self,
        request: ReaderDesktopOpenRequest,
    ) -> ReaderDesktopOpenRequest: ...

    def peek_desktop_open_request(self) -> ReaderDesktopOpenRequest | None: ...

    def acknowledge_desktop_open_request(self, request_id: str) -> None: ...

    def create_export_job(self, job: ReaderExportJob) -> ReaderExportJob: ...

    def get_export_job(self, job_id: str) -> ReaderExportJob: ...

    def list_export_jobs(
        self,
        statuses: tuple[ExportStatus, ...] | None = None,
        *,
        limit: int = 100,
    ) -> tuple[ReaderExportJob, ...]: ...

    def claim_export_job(self, job_id: str) -> ReaderExportJob: ...

    def update_export_progress(
        self,
        job_id: str,
        *,
        completed_documents: int,
        current_document_id: str | None,
        output_files: tuple[str, ...],
        progress_phase: ExportPhase,
        progress_percent: int,
    ) -> ReaderExportJob: ...

    def finish_export_job(
        self,
        job_id: str,
        *,
        status: ExportStatus,
        output_files: tuple[str, ...] = (),
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> ReaderExportJob: ...

    def request_export_cancel(self, job_id: str) -> ReaderExportJob: ...

    def recover_export_jobs(self) -> tuple[ReaderExportJob, ...]: ...

    def create_rule_set(self, rule_set: SpeechRuleSet) -> SpeechRuleSet: ...

    def get_rule_set(self, rule_set_id: str) -> SpeechRuleSet: ...

    def list_rule_sets(self) -> tuple[SpeechRuleSet, ...]: ...

    def update_rule_set(
        self, rule_set: SpeechRuleSet, *, expected_row_version: int
    ) -> SpeechRuleSet: ...

    def delete_rule_set(self, rule_set_id: str, *, expected_row_version: int) -> None: ...

    def create_rule(self, rule: SpeechRule) -> SpeechRule: ...

    def get_rule(self, rule_id: str) -> SpeechRule: ...

    def list_rules(self, rule_set_ids: tuple[str, ...] | None = None) -> tuple[SpeechRule, ...]: ...

    def update_rule(
        self, rule: SpeechRule, *, expected_row_version: int
    ) -> SpeechRule: ...

    def delete_rule(self, rule_id: str, *, expected_row_version: int) -> None: ...

    def get_rules_version(self) -> int: ...

    def report(self) -> ReaderDatabaseReport: ...

    def backup_to(self, destination: Path, *, overwrite: bool = False) -> Path: ...
