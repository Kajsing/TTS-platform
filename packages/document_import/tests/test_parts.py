from __future__ import annotations

from dataclasses import replace

import pytest
from document_import import ImportOptions, ImportSource, import_document
from document_import.parts import plan_import_parts, slice_import_part
from reader_core import ReaderValidationError


def markdown(text, title="Book"):
    return import_document(
        ImportSource("book.md", "text/markdown", text.encode("utf-8")),
        options=ImportOptions(title=title),
    )


def canonical(document):
    return "\n\n".join(block.text for block in document.blocks)


def test_exact_fit_whole_chapters_and_recombined_source():
    imported = markdown("# One\n\nabcd\n\n# Two\n\nefgh\n\n# Three\n\nijkl")
    plan = plan_import_parts(imported, max_characters=20)
    assert plan.can_commit and [len(part.text_sha256) for part in plan.parts] == [64, 64]
    assert [(part.first_chapter, part.last_chapter) for part in plan.parts] == [(1, 2), (3, 3)]
    assert plan.parts[0].codepoints == 20
    assert plan.parts[0].title == "Book - Part 01 (Chapters 1-2)"
    parts = [slice_import_part(imported, part) for part in plan.parts]
    assert "\n\n".join(canonical(part) for part in parts) == canonical(imported)
    assert all(part.source_sha256 == imported.source_sha256 for part in parts)
    assert [block.text for part in parts for block in part.blocks] == [
        block.text for block in imported.blocks
    ]


def test_utf16_bound_counts_non_bmp_characters():
    imported = markdown("# One\n\n😀😀")
    rejected = plan_import_parts(imported, max_characters=8)
    assert not rejected.can_commit and "whole" in rejected.issues[0]
    accepted = plan_import_parts(imported, max_characters=9)
    assert accepted.can_commit
    assert accepted.parts[0].codepoints == 7 and accepted.parts[0].utf16_units == 9
    assert accepted.parts[0].title == "Book"


def test_only_selected_non_root_heading_level_defines_chapters():
    imported = markdown("Preamble.\n\n# Main\n\nBody.\n\n## Sub\n\nMore.\n\n# End\n\nLast.")
    first_level = plan_import_parts(imported)
    second_level = plan_import_parts(imported, heading_level=2)
    assert [chapter.title for chapter in first_level.chapters] == ["Book", "Main", "End"]
    assert [chapter.title for chapter in second_level.chapters] == ["Book", "Sub"]
    assert plan_import_parts(imported, heading_level=9).chapters[0].end_block == len(
        imported.blocks
    )
    assert len(plan_import_parts(imported, heading_level=9).chapters) == 1
    at_start = plan_import_parts(markdown("# Main\n\nBody."))
    assert len(at_start.chapters) == 1 and at_start.chapters[0].title == "Main"


def test_plain_chapter_lines_and_paragraphs_are_never_guessed_or_split():
    imported = markdown("Chapter 1\nordinary prose\n\nChapter 2\nmore prose")
    plan = plan_import_parts(imported, max_characters=20)
    assert len(plan.chapters) == 1 and not plan.can_commit
    assert "heading level" in plan.issues[0]
    assert not plan.parts


def test_owner_import_does_not_apply_mcp_per_write_200k_limit():
    imported = markdown("# Long\n\n" + "a" * 200_001)
    plan = plan_import_parts(imported, max_characters=210_000)
    assert plan.can_commit and len(plan.parts) == 1 and plan.parts[0].codepoints > 200_000


def test_sections_ancestors_code_whitespace_and_metadata_are_retained():
    imported = markdown(
        "# One\n\n## Detail\n\n```python\n  code()\n\n    more()\n```\n\n# Two\n\n## Other\n\nLast."
    )
    plan = plan_import_parts(imported, max_characters=50)
    assert plan.can_commit and len(plan.parts) == 2
    parts = [slice_import_part(imported, part) for part in plan.parts]
    assert "\n\n".join(canonical(part) for part in parts) == canonical(imported)
    codes = [block for part in parts for block in part.blocks if block.kind == "code"]
    assert len(codes) == 1 and codes[0].text == "  code()\n\n    more()"
    assert codes[0].metadata == {"markdown_fence_language": "python"}
    assert [section.heading for section in parts[1].sections] == ["Book", "Two", "Other"]
    assert parts[1].sections[2].parent_ordinal == 1
    assert all(
        block.section_ordinal < len(part.sections) for part in parts for block in part.blocks
    )


def test_marker_snapshot_headroom_splits_even_small_text_parts():
    imported = markdown(
        "\n\n".join(f"# {number} " + "a" * 290 + "\n\nBody." for number in range(300))
    )
    plan = plan_import_parts(imported)
    assert plan.can_commit and len(plan.parts) > 1
    assert plan.parts[-1].last_chapter == 300
    assert all(part.codepoints < 900_000 for part in plan.parts)


def test_more_than_1024_chapters_is_actionable_cannot_commit():
    imported = markdown("\n\n".join(f"# Chapter {number}\n\nBody." for number in range(1025)))
    plan = plan_import_parts(imported)
    assert not plan.can_commit and "1024" in plan.issues[0]


def test_more_than_100_parts_is_actionable_cannot_commit():
    imported = markdown("\n\n".join(f"# C{number}\n\nBody." for number in range(101)))
    plan = plan_import_parts(imported, max_characters=11)
    assert not plan.can_commit and "100 parts" in plan.issues[0]


def test_plan_identity_changes_with_policy_boundaries_source_text_and_metadata():
    imported = markdown("# One\n\nBody.\n\n## Sub\n\nOther.")
    original = plan_import_parts(imported).plan_key
    assert plan_import_parts(imported).plan_key == original
    assert plan_import_parts(imported, heading_level=2).plan_key != original
    assert plan_import_parts(imported, max_characters=800_000).plan_key != original
    assert plan_import_parts(replace(imported, metadata={"changed": True})).plan_key != original
    block = replace(imported.blocks[1], text="Changed")
    assert (
        plan_import_parts(
            replace(imported, blocks=(imported.blocks[0], block, *imported.blocks[2:]))
        ).plan_key
        != original
    )


@pytest.mark.parametrize("max_characters", [0, -1, 1_000_001, True])
def test_part_policy_validation(max_characters):
    with pytest.raises(ReaderValidationError):
        plan_import_parts(markdown("Body."), max_characters=max_characters)


@pytest.mark.parametrize("target", ["document", "block", "section"])
def test_large_source_metadata_is_not_mistaken_for_a_ready_part_preview(target):
    imported = markdown("# One\n\nBody.")
    metadata = {"large": "😀" * 17_000}
    if target == "document":
        imported = replace(imported, metadata=metadata)
    elif target == "block":
        block = replace(imported.blocks[0], metadata=metadata)
        imported = replace(imported, blocks=(block, *imported.blocks[1:]))
    else:
        section = replace(imported.sections[0], metadata=metadata)
        imported = replace(imported, sections=(section, *imported.sections[1:]))
    plan = plan_import_parts(imported)
    assert not plan.can_commit and plan.issues and not plan.parts
