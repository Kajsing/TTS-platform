from __future__ import annotations

from dataclasses import dataclass

from .models import ReaderBlock

MAX_BLOCK_PAGE_CHARACTERS = 1_000_000


@dataclass(frozen=True, slots=True)
class BoundedReaderBlockPage:
    """Complete source blocks admitted under a raw UTF-8 materialization budget."""

    blocks: tuple[ReaderBlock, ...]
    next_after_ordinal: int | None
