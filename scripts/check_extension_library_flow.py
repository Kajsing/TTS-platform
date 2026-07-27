from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
EXTENSION_ROOT = REPO_ROOT / "apps" / "chrome_extension"
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"
READER_CORE_SRC = REPO_ROOT / "packages" / "reader_core" / "src"
DOCUMENT_IMPORT_SRC = REPO_ROOT / "packages" / "document_import" / "src"
SPEECH_RULES_SRC = REPO_ROOT / "packages" / "speech_rules" / "src"
EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"

for path in (
    SCRIPT_DIR,
    SERVICE_SRC,
    CORE_SRC,
    READER_CORE_SRC,
    DOCUMENT_IMPORT_SRC,
    SPEECH_RULES_SRC,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import check_local_service_bootstrap as service_bootstrap  # noqa: E402


class ExtensionLibraryFlowError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_extension_library_flow")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--startup-timeout-s", type=float, default=30.0)
    parser.add_argument("--command-timeout-s", type=float, default=60.0)
    args = parser.parse_args(argv)

    summary = check_extension_library_flow(
        python_executable=args.python_executable,
        startup_timeout_s=args.startup_timeout_s,
        command_timeout_s=args.command_timeout_s,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def check_extension_library_flow(
    *,
    python_executable: str,
    startup_timeout_s: float,
    command_timeout_s: float,
) -> dict[str, object]:
    wiring = _verify_extension_wiring()
    with tempfile.TemporaryDirectory(prefix="tts-platform-extension-library-") as temp_dir:
        temp_root = Path(temp_dir)
        repo_root = temp_root / "repo"
        service_bootstrap._seed_temp_repo(repo_root)
        env = service_bootstrap._source_env()
        service_bootstrap._configure_temp_reader_env(env, repo_root)
        setup = service_bootstrap._run_json_command(
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
        token_file = Path(str(setup.get("token_file", "")))
        if not token_file.is_file():
            raise ExtensionLibraryFlowError("setup-local did not create a token file")
        service_bootstrap._run_json_command(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "extension-allow-origin",
                EXTENSION_ORIGIN,
                "--repo-root",
                str(repo_root),
            ],
            env=env,
            timeout_s=command_timeout_s,
        )

        port = service_bootstrap._reserve_loopback_port()
        base_url = f"http://127.0.0.1:{port}"
        process = subprocess.Popen(
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
                process=process,
                timeout_s=startup_timeout_s,
            )
            service = _verify_live_capture(
                base_url,
                token_file.read_text(encoding="utf-8").strip(),
            )
        finally:
            service_bootstrap._stop_process(process)

    return {"extension_wiring": wiring, "service_capture": service}


def _verify_extension_wiring() -> dict[str, object]:
    popup_html = (EXTENSION_ROOT / "src" / "popup.html").read_text(encoding="utf-8")
    popup_js = (EXTENSION_ROOT / "src" / "popup.js").read_text(encoding="utf-8")
    background = (EXTENSION_ROOT / "src" / "background.js").read_text(encoding="utf-8")
    content = (EXTENSION_ROOT / "src" / "content-script.js").read_text(encoding="utf-8")
    required = {
        "popup.html": [
            'id="save-selection"',
            'id="save-page"',
            'id="add-page-to-queue"',
            'id="open-page-desktop"',
            'id="reader-status"',
        ],
        "popup.js": [
            '"tts-extension:save-selection"',
            '"tts-extension:save-page"',
            '"tts-extension:add-page-to-queue"',
            '"tts-extension:open-page-in-desktop"',
            "formatReaderStatus",
        ],
        "background.js": [
            "async function saveCaptureToLibrary(",
            'readerFetchJson(config, "/v1/reader/browser-captures"',
            "Authorization: `Bearer ${config.token}`",
            "reuse_existing: true",
            "add_to_queue: addToQueue",
            "open_in_desktop: openInDesktop",
            "sanitizeBrowserSource",
            "sanitizeLibraryBlocks",
        ],
        "content-script.js": [
            '"tts-extension:get-library-page"',
            "limitBlockEntries",
            "MAX_LIBRARY_CAPTURE_CHARS",
            "blocks: capturedBlocks",
        ],
    }
    sources = {
        "popup.html": popup_html,
        "popup.js": popup_js,
        "background.js": background,
        "content-script.js": content,
    }
    missing = [
        f"{name}: {fragment}"
        for name, fragments in required.items()
        for fragment in fragments
        if fragment not in sources[name]
    ]
    if missing:
        raise ExtensionLibraryFlowError(
            "Extension library wiring is incomplete:\n" + "\n".join(missing)
        )

    sanitizer = background.split("function sanitizePageCaptureMeta", 1)[-1].split(
        "function sanitizePageStructureMeta", 1
    )[0]
    if "blocks" in sanitizer or "text:" in sanitizer:
        raise ExtensionLibraryFlowError(
            "Raw browser blocks or text entered persisted page-capture metadata"
        )
    if "pageCapture: capture.meta" not in background:
        raise ExtensionLibraryFlowError(
            "Playback must continue to persist metadata rather than raw page content"
        )
    return {
        "selection_save": True,
        "page_save": True,
        "queue_action": True,
        "desktop_handoff": True,
        "raw_text_persisted": False,
    }


def _verify_live_capture(base_url: str, token: str) -> dict[str, object]:
    payload = {
        "title": "Browser flow fixture",
        "source_uri": "https://example.test/reader-flow",
        "source_name": "example.test",
        "language_hint": "en",
        "blocks": [
            {"kind": "heading", "text": "Browser heading", "heading_level": 1},
            {"kind": "paragraph", "text": "Unique browser library body."},
            {"kind": "list_item", "text": "Captured list item."},
        ],
        "extraction_source": "readable-blocks",
        "truncated": False,
        "add_to_queue": True,
        "open_in_desktop": True,
    }
    auth_headers = {
        "Authorization": f"Bearer {token}",
        "Origin": EXTENSION_ORIGIN,
    }
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        unauthenticated = client.post(
            "/v1/reader/browser-captures",
            headers={"Origin": EXTENSION_ORIGIN},
            json=payload,
        )
        wrong_origin = client.post(
            "/v1/reader/browser-captures",
            headers={**auth_headers, "Origin": "https://evil.example"},
            json=payload,
        )
        created = client.post(
            "/v1/reader/browser-captures",
            headers=auth_headers,
            json=payload,
        )
        if unauthenticated.status_code != 401 or wrong_origin.status_code != 403:
            raise ExtensionLibraryFlowError(
                "Browser capture did not enforce token and extension-origin policy"
            )
        if created.status_code != 201:
            raise ExtensionLibraryFlowError(
                f"Browser capture failed with HTTP {created.status_code}"
            )
        body = created.json()
        document_id = body.get("document", {}).get("id")
        listed = client.get(
            "/v1/reader/documents",
            headers=auth_headers,
            params={"query": "Unique browser library"},
        ).json()
        blocks = client.get(
            f"/v1/reader/documents/{document_id}/blocks",
            headers=auth_headers,
        ).json()
        queue = client.get("/v1/reader/queue", headers=auth_headers).json()
        handoff = client.get(
            "/v1/reader/desktop/open-requests/next",
            headers=auth_headers,
        ).json()
        unsafe = client.post(
            "/v1/reader/browser-captures",
            headers=auth_headers,
            json={**payload, "source_uri": "file:///C:/private.txt"},
        )
        if document_id not in {
            item.get("id") for item in listed.get("documents", [])
        }:
            raise ExtensionLibraryFlowError("Saved browser document is absent from the library")
        if [item.get("kind") for item in blocks.get("blocks", [])] != [
            "heading",
            "paragraph",
            "list_item",
        ]:
            raise ExtensionLibraryFlowError("Browser block structure was not preserved")
        if body.get("queue_item", {}).get("document_id") != document_id:
            raise ExtensionLibraryFlowError("Browser queue handoff was not persisted")
        if not any(item.get("document_id") == document_id for item in queue.get("items", [])):
            raise ExtensionLibraryFlowError("Saved browser document is absent from the queue")
        if handoff.get("document_id") != document_id:
            raise ExtensionLibraryFlowError("Desktop open request was not persisted")
        if unsafe.status_code != 400:
            raise ExtensionLibraryFlowError("Browser capture accepted a filesystem source URI")
        reused = client.post(
            "/v1/reader/browser-captures",
            headers=auth_headers,
            json=payload,
        )
        if reused.status_code != 201 or not reused.json().get("reused_existing"):
            raise ExtensionLibraryFlowError("Repeated browser actions were not idempotent")
        if reused.json().get("document", {}).get("id") != document_id:
            raise ExtensionLibraryFlowError("Repeated browser action created another document")
        different_source = client.post(
            "/v1/reader/browser-captures",
            headers=auth_headers,
            json={**payload, "source_uri": "https://other.example/same-text"},
        )
        if different_source.status_code != 409:
            raise ExtensionLibraryFlowError(
                "Browser capture reused content from a different source URL"
            )

    return {
        "token_required": True,
        "allowed_origin_required": True,
        "document_visible": True,
        "structured_block_count": 3,
        "queue_persisted": True,
        "desktop_handoff_persisted": True,
        "repeated_action_idempotent": True,
        "distinct_source_metadata_preserved": True,
        "filesystem_source_rejected": True,
    }


if __name__ == "__main__":
    try:
        main()
    except ExtensionLibraryFlowError as exc:
        raise SystemExit(str(exc)) from exc
