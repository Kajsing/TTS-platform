from __future__ import annotations

from tts_core.text import SentenceSegmenter, TextNormalizer, TextPipeline


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
