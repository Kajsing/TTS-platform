from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import (
    Bookmark,
    DocumentEdit,
    DocumentPage,
    DocumentState,
    PlaybackPosition,
    QueueItem,
    QueueStatus,
    ReaderBlock,
    ReaderCursor,
    ReaderDatabaseReport,
    ReaderDocument,
    ReaderDocumentBundle,
)


class ReaderRepository(Protocol):
    def create_document(self, bundle: ReaderDocumentBundle) -> ReaderDocument: ...

    def get_document(self, document_id: str) -> ReaderDocument: ...

    def get_document_bundle(self, document_id: str) -> ReaderDocumentBundle: ...

    def list_documents(
        self,
        *,
        state: DocumentState | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> DocumentPage: ...

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

    def report(self) -> ReaderDatabaseReport: ...

    def backup_to(self, destination: Path, *, overwrite: bool = False) -> Path: ...
