"""Offline chapter-package validation; never fetches, imports, or reads credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

MAX_TEXT = 200_000


def normalize(text: str) -> str:
    """Match Reader's plain-text paragraph joining, without normalizing prose."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return "\n\n".join(part.strip() for part in re.split(r"\n[ \t]*\n+", text) if part.strip())


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_bundle(data: dict, *, expected_count: int, expected_story_key: str) -> str:
    """Return the exact expected Reader text, or reject a suspicious package."""
    if type(expected_count) is not int or expected_count < 1:
        raise ValueError("expected_count must be a positive integer")
    if not isinstance(data, dict) or data.get("story_key") != expected_story_key:
        raise ValueError("story identity mismatch")
    if not isinstance(expected_story_key, str) or not 1 <= len(expected_story_key) <= 200:
        raise ValueError("invalid story identity")
    intro = data.get("intro")
    if not isinstance(intro, str) or not intro.strip() or len(intro) > MAX_TEXT:
        raise ValueError("intro must be nonempty and fit one MCP write")
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or len(chapters) != expected_count:
        raise ValueError("chapter count mismatch")
    hashes: set[str] = set()
    urls: set[str] = set()
    keys: set[str] = set()
    texts = [normalize(intro)]
    for position, chapter in enumerate(chapters, 1):
        if not isinstance(chapter, dict):
            raise ValueError(f"chapter {position}: expected an object")
        if type(chapter.get("number")) is not int or chapter["number"] != position:
            raise ValueError(f"chapter {position}: delivery order mismatch")
        key = chapter.get("chapter_key")
        if not isinstance(key, str) or not 1 <= len(key) <= 200 or key in keys:
            raise ValueError(f"chapter {position}: invalid or repeated identity")
        title, text, url = (chapter.get(field) for field in ("title", "text", "source_url"))
        if not isinstance(title, str) or not title.strip() or len(title) > 500:
            raise ValueError(f"chapter {position}: invalid title")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError(f"chapter {position}: empty or oversized text")
        if not isinstance(url, str) or len(url) > 2048:
            raise ValueError(f"chapter {position}: invalid source URL")
        try:
            parsed = urlsplit(url)
            valid_url = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not any(character.isspace() for character in url)
            )
        except ValueError:
            valid_url = False
        if not valid_url or url in urls:
            raise ValueError(f"chapter {position}: invalid or repeated source URL")
        normalized = normalize(text)
        heading, separator, body = normalized.partition("\n\n")
        if heading != title.strip() or not separator or not body.strip():
            raise ValueError(f"chapter {position}: missing heading or chapter body")
        if re.fullmatch(r"https?://\S+", body.strip(), re.IGNORECASE):
            raise ValueError(f"chapter {position}: URL-only body, not a chapter")
        if chapter.get("sha256") != digest(text):
            raise ValueError(f"chapter {position}: source hash mismatch")
        body_hash = digest(body)
        if body_hash in hashes:
            raise ValueError(f"chapter {position}: repeated body requires source review")
        hashes.add(body_hash)
        urls.add(url)
        keys.add(key)
        texts.append(normalized)
    return "\n\n".join(texts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--story-key", required=True)
    parser.add_argument("--article-text", type=Path, help="Full MCP readback, not the first page")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.bundle.read_text(encoding="utf-8-sig"))
        expected = validate_bundle(
            data, expected_count=args.expected_count, expected_story_key=args.story_key
        )
        if args.article_text is not None:
            actual = args.article_text.read_text(encoding="utf-8-sig")
            if actual != expected:
                raise ValueError("full Reader text differs from the normalized source package")
    except OSError:
        print(json.dumps({"valid": False, "error": "cannot read input file"}))
        return 1
    except (ValueError, UnicodeError) as error:
        message = (
            "invalid JSON or text encoding"
            if isinstance(error, (json.JSONDecodeError, UnicodeError))
            else str(error)
        )
        print(json.dumps({"valid": False, "error": message}))
        return 1
    print(
        json.dumps(
            {
                "valid": True,
                "chapters": args.expected_count,
                "expected_text_characters": len(expected),
                "expected_text_sha256": digest(expected),
                "exact_readback_match": args.article_text is not None,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
