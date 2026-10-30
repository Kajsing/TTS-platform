"""Read bounded chapter metadata without loading any source blocks."""

from __future__ import annotations

import json

from ..chapter_index import (
    ChapterAnchor,
    ChapterDocumentAccess,
    ChapterIndex,
    ChapterIndexConflictError,
)
from ..chapters import CHAPTER_KEY, read_markers
from ..errors import ReaderConflictError, ReaderNotFoundError, ReaderValidationError

MARKER_LOOKUP_BATCH = 500


def read_chapter_access(repository, document_id: str) -> ChapterDocumentAccess:
    """Keep privacy enforceable even when the document's JSON is corrupt."""
    with repository._connection() as connection:
        row = connection.execute(
            "SELECT folder_id, content_revision, deleted_at FROM reader_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    if row is None:
        raise ReaderNotFoundError("Reader document was not found.")
    return ChapterDocumentAccess(
        row["folder_id"], int(row["content_revision"]), row["deleted_at"] is not None
    )


def read_chapter_index(repository, document_id: str, expected_revision: int) -> ChapterIndex:
    if type(expected_revision) is not int or expected_revision < 1:
        raise ReaderValidationError("Chapter navigation requires a positive content revision.")
    with repository._connection() as connection:
        connection.execute("BEGIN")
        document = connection.execute(
            "SELECT content_revision, deleted_at, metadata_json FROM reader_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if document is None:
            raise ReaderNotFoundError("Reader document was not found.")
        revision = int(document["content_revision"])
        if document["deleted_at"] is not None or revision != expected_revision:
            raise ReaderConflictError(document_id, expected=expected_revision, actual=revision)
        try:
            metadata = json.loads(document["metadata_json"])
            if not isinstance(metadata, dict) or (
                CHAPTER_KEY in metadata and metadata[CHAPTER_KEY] is None
            ):
                raise ReaderValidationError("Chapter metadata must contain valid markers.")
            first = connection.execute(
                "SELECT id, ordinal, character_count FROM reader_blocks "
                "WHERE document_id = ? ORDER BY ordinal LIMIT 1",
                (document_id,),
            ).fetchone()
            if first is None:
                if CHAPTER_KEY in metadata:
                    raise ReaderValidationError("Chapter markers cannot anchor an empty article.")
                return ChapterIndex(document_id, revision, ())
            markers = read_markers(metadata, str(first["id"]))
            # IDs are bounded before building SQL parameters, even for corrupted metadata.
            if any(len(marker.block_id) > 100 for marker in markers):
                raise ReaderValidationError("Chapter block IDs exceed their bounds.")
            locations = {str(first["id"]): first}
            wanted = tuple(
                dict.fromkeys(
                    marker.block_id for marker in markers if marker.block_id not in locations
                )
            )
            for start in range(0, len(wanted), MARKER_LOOKUP_BATCH):
                batch = wanted[start : start + MARKER_LOOKUP_BATCH]
                # Without the primary-key index hint SQLite may choose a document
                # scan for a wide IN clause. Work must depend on markers, not blocks.
                rows = connection.execute(
                    "SELECT id, ordinal, character_count FROM reader_blocks "
                    "INDEXED BY sqlite_autoindex_reader_blocks_1 "
                    f"WHERE id IN ({','.join('?' for _ in batch)}) AND document_id = ?",
                    (*batch, document_id),
                )
                locations.update((str(row["id"]), row) for row in rows)
            anchors = []
            previous = None
            for marker in markers:
                location = locations.get(marker.block_id)
                if location is None or marker.codepoint_offset > int(location["character_count"]):
                    raise ReaderValidationError("Chapter boundary is outside its source block.")
                position = (int(location["ordinal"]), marker.codepoint_offset)
                if previous is None:
                    if position != (int(first["ordinal"]), 0):
                        raise ReaderValidationError(
                            "The first chapter must start with the article."
                        )
                elif position <= previous:
                    raise ReaderValidationError("Chapter boundaries must be unique and ordered.")
                previous = position
                anchors.append(ChapterAnchor(marker.id, marker.title, marker.block_id, *position))
            return ChapterIndex(document_id, revision, tuple(anchors))
        except (ReaderValidationError, ValueError, TypeError) as error:
            raise ChapterIndexConflictError(
                "The article chapter metadata is invalid. Its stored content was kept unchanged."
            ) from error
