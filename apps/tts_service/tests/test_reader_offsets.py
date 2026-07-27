from __future__ import annotations

import pytest
from tts_service.reader_offsets import (
    ReaderOffsetError,
    python_offset_to_utf16,
    utf16_offset_to_python,
)


@pytest.mark.parametrize(
    ("python_offset", "utf16_offset"),
    [(0, 0), (1, 1), (2, 3), (3, 4), (4, 5)],
)
def test_reader_offsets_round_trip_emoji_boundaries(
    python_offset: int,
    utf16_offset: int,
) -> None:
    text = "A😀e\u0301"

    assert python_offset_to_utf16(text, python_offset) == utf16_offset
    assert utf16_offset_to_python(text, utf16_offset) == python_offset


def test_reader_offset_rejects_middle_of_surrogate_pair() -> None:
    with pytest.raises(ReaderOffsetError, match="surrogate pair"):
        utf16_offset_to_python("😀", 1)


def test_reader_offset_rejects_out_of_range_values() -> None:
    with pytest.raises(ReaderOffsetError, match="exceeds"):
        utf16_offset_to_python("abc", 4)
    with pytest.raises(ReaderOffsetError, match="outside"):
        python_offset_to_utf16("abc", 4)
