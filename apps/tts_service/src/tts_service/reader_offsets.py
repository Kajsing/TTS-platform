from __future__ import annotations


class ReaderOffsetError(ValueError):
    pass


def utf16_offset_to_python(text: str, offset: int) -> int:
    """Convert an API UTF-16 code-unit boundary to a Python string index."""
    if offset < 0:
        raise ReaderOffsetError("UTF-16 offset must not be negative")
    utf16_offset = 0
    for python_offset, character in enumerate(text):
        if utf16_offset == offset:
            return python_offset
        width = 2 if ord(character) > 0xFFFF else 1
        if utf16_offset < offset < utf16_offset + width:
            raise ReaderOffsetError("UTF-16 offset splits a surrogate pair")
        utf16_offset += width
    if utf16_offset == offset:
        return len(text)
    raise ReaderOffsetError("UTF-16 offset exceeds the source text")


def python_offset_to_utf16(text: str, offset: int) -> int:
    """Convert an internal Python string index to a UTF-16 code-unit boundary."""
    if offset < 0 or offset > len(text):
        raise ReaderOffsetError("Python offset is outside the source text")
    return sum(2 if ord(character) > 0xFFFF else 1 for character in text[:offset])
