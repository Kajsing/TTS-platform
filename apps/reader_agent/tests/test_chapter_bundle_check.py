from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path

import pytest
from reader_core.plain_text import split_plain_text_paragraphs

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/check_reader_chapter_bundle.py"
CHECK = runpy.run_path(str(SCRIPT))


def bundle():
    chapters = []
    for number, body in enumerate(
        ("Short, but real. æøå 😀", "Another paragraph.\r\n\r\nThe end."), 1
    ):
        text = f"Chapter {number}\n\n{body}"
        chapters.append(
            {
                "number": number,
                "chapter_key": f"chapter:{number}",
                "title": f"Chapter {number}",
                "source_url": f"https://example.com/story/{number}",
                "text": text,
                "sha256": CHECK["digest"](text),
            }
        )
    return {
        "story_key": "example/story",
        "intro": "Synthetic story\n\nBy Example.",
        "chapters": chapters,
    }


def validate(data):
    return CHECK["validate_bundle"](data, expected_count=2, expected_story_key="example/story")


def test_short_unicode_chapters_and_reader_normalization():
    data = bundle()
    expected = "\n\n".join(
        "\n\n".join(split_plain_text_paragraphs(text))
        for text in [data["intro"], *(chapter["text"] for chapter in data["chapters"])]
    )
    assert validate(data) == expected
    assert "æøå 😀" in expected


@pytest.mark.parametrize(
    "change",
    [
        "url_only",
        "heading_only",
        "wrong_hash",
        "missing_chapter",
        "reversed",
        "duplicate_body",
        "duplicate_key",
        "duplicate_url",
        "credential_url",
        "oversized",
        "wrong_story",
        "bool_number",
    ],
)
def test_refuses_incomplete_or_suspicious_payloads(change):
    data = copy.deepcopy(bundle())
    chapter = data["chapters"][0]
    if change == "url_only":
        chapter["text"] = "Chapter 1\n\nhttps://example.com/story/1"
        chapter["sha256"] = CHECK["digest"](chapter["text"])
    elif change == "heading_only":
        chapter["text"] = "Chapter 1"
    elif change == "wrong_hash":
        chapter["text"] += "Changed"
    elif change == "missing_chapter":
        data["chapters"].pop()
    elif change == "reversed":
        data["chapters"].reverse()
    elif change == "duplicate_body":
        second = data["chapters"][1]
        second["text"] = chapter["text"].replace("Chapter 1", "Chapter 2", 1)
        second["sha256"] = CHECK["digest"](second["text"])
    elif change == "duplicate_key":
        data["chapters"][1]["chapter_key"] = chapter["chapter_key"]
    elif change == "duplicate_url":
        data["chapters"][1]["source_url"] = chapter["source_url"]
    elif change == "credential_url":
        chapter["source_url"] = "https://secret@example.com/chapter/1"
    elif change == "oversized":
        chapter["text"] += "x" * 200_000
    elif change == "wrong_story":
        data["story_key"] = "wrong/story"
    elif change == "bool_number":
        chapter["number"] = True
    with pytest.raises(ValueError):
        validate(data)


def test_cli_exact_readback_and_silent_text_handling(tmp_path, capsys):
    data = bundle()
    source = tmp_path / "source.json"
    readback = tmp_path / "readback.txt"
    source.write_text(json.dumps(data), encoding="utf-8")
    args = [str(source), "--expected-count", "2", "--story-key", "example/story"]
    assert CHECK["main"](args) == 0
    assert json.loads(capsys.readouterr().out)["exact_readback_match"] is False
    readback.write_text(validate(data), encoding="utf-8")
    assert CHECK["main"]([*args, "--article-text", str(readback)]) == 0
    assert json.loads(capsys.readouterr().out)["exact_readback_match"] is True
    readback.write_text(validate(data)[:-1], encoding="utf-8")
    assert CHECK["main"]([*args, "--article-text", str(readback)]) == 1
    assert "Short, but real" not in capsys.readouterr().out


def test_cli_bad_file_reports_without_content(tmp_path, capsys):
    source = tmp_path / "source.json"
    source.write_bytes(b"\xffprivate invalid content")
    assert CHECK["main"]([str(source), "--expected-count", "2", "--story-key", "x"]) == 1
    assert "private" not in capsys.readouterr().out
