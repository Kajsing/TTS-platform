from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
EXTENSION_ROOT = REPO_ROOT / "apps" / "chrome_extension"
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"
DEFAULT_MIN_STREAM_TEXT_CHUNKS = 8
DEFAULT_ARTICLE_SECTIONS = 12
DEFAULT_PARAGRAPHS_PER_SECTION = 4

for path in (SCRIPT_DIR, SERVICE_SRC, CORE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import check_local_service_bootstrap as service_bootstrap  # noqa: E402


class ExtensionReaderFlowError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_extension_reader_flow")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--startup-timeout-s", type=float, default=30.0)
    parser.add_argument("--command-timeout-s", type=float, default=90.0)
    parser.add_argument(
        "--min-stream-text-chunks",
        type=int,
        default=DEFAULT_MIN_STREAM_TEXT_CHUNKS,
    )
    args = parser.parse_args(argv)

    try:
        summary = check_extension_reader_flow(
            python_executable=args.python_executable,
            startup_timeout_s=args.startup_timeout_s,
            command_timeout_s=args.command_timeout_s,
            min_stream_text_chunks=args.min_stream_text_chunks,
        )
    except ExtensionReaderFlowError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_extension_reader_flow(
    *,
    python_executable: str,
    startup_timeout_s: float = 30.0,
    command_timeout_s: float = 90.0,
    min_stream_text_chunks: int = DEFAULT_MIN_STREAM_TEXT_CHUNKS,
) -> dict[str, object]:
    if min_stream_text_chunks <= 0:
        raise ExtensionReaderFlowError("--min-stream-text-chunks must be positive.")

    reader_contract = _verify_extension_reader_contract()
    article = _build_long_article_fixture()
    fixture_summary = _summarize_article_fixture(article)
    if fixture_summary["word_count"] < 1000:
        raise ExtensionReaderFlowError("Long article fixture must contain at least 1000 words.")
    if fixture_summary["section_count"] < 4:
        raise ExtensionReaderFlowError("Long article fixture must contain multiple sections.")

    with tempfile.TemporaryDirectory(prefix="tts-platform-reader-flow-") as temp_dir:
        temp_root = Path(temp_dir)
        repo_root = temp_root / "repo"
        article_path = temp_root / "long_article.txt"
        article_path.write_text(article, encoding="utf-8")

        service_bootstrap._seed_temp_repo(repo_root)
        env = service_bootstrap._source_env()
        setup_payload = service_bootstrap._run_json_command(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "setup-local",
                "--repo-root",
                str(repo_root),
            ],
            env=env,
            timeout_s=command_timeout_s,
        )
        token_file = Path(str(setup_payload.get("token_file", "")))
        if not token_file.is_file():
            raise ExtensionReaderFlowError("setup-local did not create a token file.")

        port = service_bootstrap._reserve_loopback_port()
        base_url = f"http://127.0.0.1:{port}"
        service_process = subprocess.Popen(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "serve",
                "--repo-root",
                str(repo_root),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            service_bootstrap._wait_for_health(
                base_url=base_url,
                process=service_process,
                timeout_s=startup_timeout_s,
            )
            smoke_payload = service_bootstrap._run_json_command(
                [
                    python_executable,
                    "scripts/smoke_service.py",
                    "--base-url",
                    base_url,
                    "--token-file",
                    str(token_file),
                    "--stream-text-file",
                    str(article_path),
                    "--min-stream-text-chunks",
                    str(min_stream_text_chunks),
                ],
                env=env,
                timeout_s=command_timeout_s,
            )
        finally:
            service_bootstrap._stop_process(service_process)

    return {
        "reader_contract": reader_contract,
        "article_fixture": fixture_summary,
        "service_stream": _summarize_smoke(smoke_payload),
    }


def _verify_extension_reader_contract() -> dict[str, object]:
    files = {
        "popup.html": EXTENSION_ROOT / "src" / "popup.html",
        "popup.js": EXTENSION_ROOT / "src" / "popup.js",
        "background.js": EXTENSION_ROOT / "src" / "background.js",
        "content-script.js": EXTENSION_ROOT / "src" / "content-script.js",
        "offscreen.js": EXTENSION_ROOT / "offscreen" / "offscreen.js",
    }
    contents = {
        label: path.read_text(encoding="utf-8")
        for label, path in files.items()
    }
    required_fragments = {
        "popup.html": [
            'id="speak-page"',
            'id="resume-page"',
            'id="next-section"',
            'id="status-text"',
        ],
        "popup.js": [
            '"tts-extension:speak-page"',
            '"tts-extension:resume-page"',
            '"tts-extension:next-section"',
            "formatReaderProgress",
            "formatPageCapture",
            "formatPageStructure",
            "Progress:",
            "Page Capture:",
        ],
        "background.js": [
            "async function speakPage()",
            "async function resumePage()",
            "async function nextSection()",
            "getPageCapture(tab.id, config.maxChars",
            "resolveResumeTextChunkIndex",
            "resolveNextSectionIndex",
            "startTextChunkIndex",
            "pageCapture: capture.meta",
            "sanitizePageCaptureMeta",
            "sanitizePageStructureMeta",
            "sanitizePageSections",
            "textCharStart",
        ],
        "content-script.js": [
            "function getPageCapture(maxChars = 24000, startSectionIndex = 0)",
            "sanitizeMaxChars",
            "Math.min(48000",
            "startSectionIndex",
            "buildCapturedSections",
            "textCharStart",
            "headingCount",
            "capturedHeadingCount",
            "readableBlocks",
            "truncated",
            "minimumBlockLength(blockKind)",
        ],
        "offscreen.js": [
            "readerProgress",
            "start_text_chunk_index",
            "event.progress",
            "type: \"tts-extension:playback-state\"",
        ],
    }
    errors: list[str] = []
    for label, fragments in required_fragments.items():
        for fragment in fragments:
            if fragment not in contents[label]:
                errors.append(f"{label} must contain {fragment!r}")

    _reject_raw_text_persistence(errors=errors, background_js=contents["background.js"])
    if errors:
        raise ExtensionReaderFlowError(
            "Extension reader-flow contract failed:\n" + "\n".join(errors)
        )

    return {
        "checked_files": len(files),
        "popup_actions": 3,
        "page_capture_metadata": True,
        "resume_and_next_section": True,
        "raw_page_text_persistence": False,
    }


def _reject_raw_text_persistence(*, errors: list[str], background_js: str) -> None:
    forbidden_state_fragments = [
        "pageText:",
        "rawText:",
        "capturedText:",
        "chrome.storage.local.set({ text",
        "chrome.storage.session.set({ text",
    ]
    for fragment in forbidden_state_fragments:
        if fragment in background_js:
            errors.append(f"background.js must not persist raw page text via {fragment!r}")
    required_fragments = [
        "text: capture.text",
        "pageCapture: capture.meta",
        "chrome.storage.session.set({\n    playbackState: nextState,",
    ]
    for fragment in required_fragments:
        if fragment not in background_js:
            errors.append(f"background.js must contain {fragment!r}")


def _build_long_article_fixture(
    *,
    section_count: int = DEFAULT_ARTICLE_SECTIONS,
    paragraphs_per_section: int = DEFAULT_PARAGRAPHS_PER_SECTION,
) -> str:
    paragraphs: list[str] = [
        "Local Reader Long Article",
        "This generated article exercises the same long page path that the Chrome "
        "extension sends to the local streaming endpoint.",
    ]
    sentence = (
        "The local reader captures structured page text, preserves useful headings, "
        "streams audio incrementally, records reader progress, and can resume from "
        "a later planned text chunk without storing the raw article body."
    )
    for section_index in range(section_count):
        paragraphs.append(f"Section {section_index + 1}: Reader Flow Check")
        for paragraph_index in range(paragraphs_per_section):
            paragraphs.append(
                " ".join(
                    [
                        sentence,
                        f"This is paragraph {paragraph_index + 1} in section {section_index + 1}.",
                        "It includes enough words to push the service through many planned "
                        "text chunks while keeping HTTP and async job smoke inputs short.",
                    ]
                )
            )
    return "\n\n".join(paragraphs)


def _summarize_article_fixture(article: str) -> dict[str, object]:
    words = [word for word in article.replace("\n", " ").split(" ") if word.strip()]
    section_count = article.count("Reader Flow Check")
    return {
        "chars": len(article),
        "word_count": len(words),
        "section_count": section_count,
    }


def _summarize_smoke(payload: dict[str, object]) -> dict[str, object]:
    stream = payload.get("stream", {})
    return {
        "health": payload.get("health"),
        "voice": payload.get("voice"),
        "input": payload.get("input"),
        "stream_frames": _dict_get(stream, "frames"),
        "stream_marks": _dict_get(stream, "marks"),
        "stream_text_chunk_count": _dict_get(stream, "text_chunk_count"),
        "stream_text_chars": _dict_get(stream, "text_chars"),
        "job_status": _dict_get(payload.get("job", {}), "status"),
    }


def _dict_get(raw_payload: object, key: str) -> object:
    if not isinstance(raw_payload, dict):
        return None
    return raw_payload.get(key)


if __name__ == "__main__":
    main()
