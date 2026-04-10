from __future__ import annotations

from tts_core.text import ChunkPlanner, SentenceSegmenter, TextNormalizer, TextPipeline


def test_text_normalizer_collapses_whitespace_and_expands_abbreviations() -> None:
    normalizer = TextNormalizer()

    normalized = normalizer.normalize("Dr.  Smith\n\nbrought  tea & cake.", language_hint="en")

    assert normalized == "Doctor Smith brought tea and cake."


def test_sentence_segmenter_avoids_splitting_common_abbreviations() -> None:
    segmenter = SentenceSegmenter()

    segments = segmenter.segment("Dr. Smith arrived. Hello there.", language_hint="en")

    assert segments == ["Dr. Smith arrived.", "Hello there."]


def test_text_pipeline_returns_segments_from_normalized_text() -> None:
    pipeline = TextPipeline(
        normalizer=TextNormalizer(),
        segmenter=SentenceSegmenter(),
    )

    prepared = pipeline.process("Mr. Doe said hi!  Then he left.", language_hint="en")

    assert prepared.normalized_text == "Mister Doe said hi! Then he left."
    assert prepared.segments == ("Mister Doe said hi!", "Then he left.")


def test_chunk_planner_groups_segments_into_reviewable_chunks() -> None:
    planner = ChunkPlanner(max_chars_per_chunk=50)

    plan = planner.plan(
        (
            "This is sentence one.",
            "This is sentence two.",
            "This is sentence three.",
        ),
        sentence_pause_ms=150,
        comma_pause_ms=50,
    )

    assert len(plan.chunks) == 2
    assert plan.chunks[0].text == "This is sentence one. This is sentence two."
    assert plan.chunks[0].pause_ms_hint == 150
    assert plan.chunks[1].text == "This is sentence three."


def test_chunk_planner_splits_long_sentence_at_clause_boundaries() -> None:
    planner = ChunkPlanner(max_chars_per_chunk=120)

    plan = planner.plan(
        (
            "Alpha clause introduces the topic, beta clause adds more context, "
            "gamma clause closes the idea.",
        ),
        sentence_pause_ms=150,
        comma_pause_ms=50,
    )

    assert [chunk.text for chunk in plan.chunks] == [
        "Alpha clause introduces the topic, beta clause adds more context,",
        "gamma clause closes the idea.",
    ]
    assert [chunk.pause_ms_hint for chunk in plan.chunks] == [50, 150]


def test_chunk_planner_falls_back_to_whitespace_for_oversized_segments() -> None:
    planner = ChunkPlanner(max_chars_per_chunk=35)

    plan = planner.plan(("alpha beta gamma delta epsilon zeta eta theta",))

    assert [chunk.text for chunk in plan.chunks] == [
        "alpha beta gamma delta",
        "epsilon zeta eta theta",
    ]
    assert all(chunk.char_count <= 35 for chunk in plan.chunks)
