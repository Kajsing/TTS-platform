from __future__ import annotations

from pathlib import Path

import pytest
from reader_core import ReaderLibrary, SqliteReaderRepository


@pytest.fixture
def repository(tmp_path: Path) -> SqliteReaderRepository:
    return SqliteReaderRepository(tmp_path / "reader.db")


@pytest.fixture
def document(repository: SqliteReaderRepository):
    return ReaderLibrary(repository).create_plain_text_document(
        title="Test document",
        text="Alpha beta gamma.\n\nSecond paragraph.",
    )
