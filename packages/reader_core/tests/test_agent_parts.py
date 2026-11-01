from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from reader_core import ReaderLibrary, ReaderValidationError
from reader_core.agent_access import ChapterDelivery
from reader_core.agent_parts import (
    MAX_METADATA_BYTES,
    ChapterSpec,
    PartPolicy,
    estimated_append_metadata_bytes,
    normalize_text,
    normalized_wrapper,
    plan_next_part,
    plan_parts,
    wrapper_state,
)


def chapter(key="one", text="abc", title="One", **changes):
    return ChapterDelivery(
        **(
            {
                "story_key": "story",
                "chapter_key": key,
                "retry_key": "retry-" + key,
                "source_url": "https://example.com/" + key,
                "title": title,
                "text": text,
            }
            | changes
        )
    )


def test_exact_fit_and_whole_chapter_rollover():
    one = chapter()
    two = chapter("two")
    assert plan_parts("T", "", [one], PartPolicy(max_characters=6))[0].codepoints == 6
    assert len(plan_parts("T", "", [one, two], PartPolicy(max_characters=11))) == 1
    parts = plan_parts("T", "", [one, two], PartPolicy(max_characters=10))
    assert [part.chapter_keys for part in parts] == [("one",), ("two",)]
    assert [part.number for part in parts] == [1, 2]
    assert [part.title for part in parts] == ["T - Part 01", "T - Part 02"]
    assert all(part.codepoints == 6 and part.blocks == 2 for part in parts)
    with pytest.raises(ReaderValidationError, match="complete chapter"):
        plan_parts("T", "", [one], PartPolicy(max_characters=5))


def test_non_bmp_counts_utf16_as_well_as_codepoints():
    with pytest.raises(ReaderValidationError, match="complete chapter"):
        plan_parts("T", "", [chapter(text="😀")], PartPolicy(max_characters=4))
    part = plan_parts("T", "", [chapter(text="😀")], PartPolicy(max_characters=5))[0]
    assert (part.codepoints, part.utf16_units) == (4, 5)


def test_default_900000_ceiling_splits_large_complete_chapters():
    items = [chapter(str(index), text="x" * 200_000) for index in range(5)]
    parts = plan_parts("T", "", items)
    assert [len(part.chapter_keys) for part in parts] == [4, 1]
    assert [part.codepoints for part in parts] == [800_009, 200_003]
    assert all(part.utf16_units <= 900_000 for part in parts)


def test_wrapper_headings_normalization_and_exact_recombined_hash():
    first = chapter(text=" Chapter one \r\n\r\n A  passage. \r\n ")
    second = chapter("two", text=" Chapter two\n\n\nB.")
    wrapper = normalized_wrapper("Title", " Intro. \r\n\r\n Attribution. ")
    expected = wrapper + "\n\n" + normalize_text(first.text) + "\n\n" + normalize_text(second.text)
    part = plan_parts("Title", " Intro. \r\n\r\n Attribution. ", [ChapterSpec(first), second])[0]
    assert part.codepoints == len(expected)
    assert part.utf16_units == len(expected.encode("utf-16-le")) // 2
    assert part.blocks == 7
    assert part.text_sha256 == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert "A  passage." in expected  # Interior prose whitespace is preserved.


def test_block_limit_rolls_over_and_rejects_indivisible_chapter():
    items = [chapter("one", text="A\n\nB"), chapter("two", text="C\n\nD")]
    assert len(plan_parts("T", "", items, PartPolicy(max_blocks=3))) == 2
    with pytest.raises(ReaderValidationError, match="complete chapter"):
        plan_parts("T", "", items, PartPolicy(max_blocks=2))


def test_default_cap_and_input_bounds():
    policy = PartPolicy()
    assert policy.max_characters == 900_000
    assert policy.max_blocks == 20_000
    for values in (
        {"max_characters": 0},
        {"max_characters": True},
        {"max_characters": 1_000_001},
        {"max_blocks": 20_001},
    ):
        with pytest.raises(ReaderValidationError):
            PartPolicy(**values)
    for items in ([], [chapter()] * 101, [chapter(), chapter()]):
        with pytest.raises(ReaderValidationError):
            plan_parts("T", "", items)
    with pytest.raises(ReaderValidationError, match="one story"):
        plan_parts("T", "", [chapter(), chapter("two", story_key="other")])
    with pytest.raises(ReaderValidationError, match="retry identities"):
        plan_parts("T", "", [chapter(), replace(chapter("two"), retry_key="retry-one")])
    with pytest.raises(ReaderValidationError, match="4 MiB"):
        plan_parts("T", "", [chapter(str(i), text="x" * 200_000) for i in range(22)])


def test_metadata_limit_splits_even_when_text_fits():
    items = [chapter(str(i), title="😀" * 300, text="x") for i in range(100)]
    parts = plan_parts("T", "", items)
    assert len(parts) > 1
    assert sum(len(part.chapter_keys) for part in parts) == 100
    assert all(part.append_metadata_bytes <= MAX_METADATA_BYTES for part in parts)
    assert all(part.codepoints < 1_000 for part in parts)
    with pytest.raises(ReaderValidationError, match="complete chapter"):
        plan_parts("T", "", [chapter(text="\n\n".join("x" for _ in range(400)))])


def test_metadata_estimate_bounds_actual_repository_append_json(repository):
    wrapper = normalized_wrapper("Title", "Credit.")
    document = ReaderLibrary(repository).create_plain_text_document(title="Title", text=wrapper)
    state = wrapper_state(wrapper)
    for index in range(8):
        item = chapter(str(index), title='"\t😀' * 70, text="A\n\nB😀\n\nCCC")
        estimated = estimated_append_metadata_bytes(state, item)
        document, edit = repository.append_text(
            document.id,
            item.text,
            expected_row_version=document.row_version,
            new_chapter=True,
            chapter_title=item.title[:300],
        )
        actual = len(
            json.dumps(
                edit.metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        )
        assert actual <= estimated <= MAX_METADATA_BYTES
        next_part = plan_next_part(state, item, wrapper=wrapper)
        assert not next_part.new_part
        state = next_part.state


def test_wrapper_policy_and_invalid_unicode_fail_before_plan():
    with pytest.raises(ReaderValidationError):
        plan_parts("Long title", "", [chapter()], PartPolicy(max_characters=3))
    with pytest.raises(ReaderValidationError, match="Unicode"):
        plan_parts("T", "", [chapter(text="\ud800")])
    with pytest.raises(ReaderValidationError, match="chapter-title"):
        plan_parts("T", "", [chapter(title=" " * 300 + "X")])


def test_plan_deterministic_and_does_not_embed_source_body():
    items = [chapter(text="private prose")]
    first = plan_parts("T", "", items)
    assert first == plan_parts("T", "", items)
    assert "private prose" not in repr(first)
