"""Isolated Windows Options -> DPAPI -> stdio MCP -> service -> Reader smoke.

Run with .venv-agent/Scripts/python.exe after building/publishing Reader. No
live profile, clipboard, audio endpoint, database or port 7777 is used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import uvicorn
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from reader_agent.config import AgentConnection
from tts_service.config import AppConfig
from tts_service.main import create_app


@contextmanager
def service(root: Path, port: int = 0):
    config = AppConfig.from_mapping(
        {
            "auth": {"enabled": True, "token_file": str(root / "service" / "token.txt")},
            "backend": {"mode": "stub"},
            "tts": {"warmup_on_start": False},
            "limits": {"requests_per_minute": 1000},
            "reader": {"home_path": str(root / "reader"), "exports": {"formats": ["wav"]}},
        }
    )
    app = create_app(config=config, repo_root=root)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", port))
        port = listener.getsockname()[1]
        if port == 7777:
            raise RuntimeError("Smoke must not use the normal service port")
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Isolated service did not start")
                time.sleep(0.05)
            yield f"http://127.0.0.1:{port}/", app
        finally:
            server.should_exit = True
            thread.join(15)
            if thread.is_alive():
                raise RuntimeError("Isolated service did not stop")


def desktop(executable: Path, root: Path, **scenario) -> dict:
    manifest = root / "desktop-smoke.json"
    marker = root / "desktop-result.json"
    marker.unlink(missing_ok=True)
    manifest.write_text(json.dumps(scenario), encoding="utf-8")
    environment = os.environ | {"TTS_PLATFORM_READER_AGENT_SMOKE": str(manifest)}
    run = subprocess.run(
        [str(executable), "--smoke-test"],
        env=environment,
        cwd=root,
        timeout=75,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    payload = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
    if run.returncode or payload.get("failed") or not payload:
        raise RuntimeError(f"Isolated desktop smoke failed: {payload}")
    return payload


async def exercise(session: Client) -> tuple[str, dict, str]:
    async def call(name, **arguments):
        result = await session.call_tool("reader_" + name, arguments)
        assert not result.is_error, result.structured_content
        return result.structured_content

    tools = (await session.list_tools()).tools
    assert len(tools) == 9
    assert (await call("workspace"))["folder_id"]
    article = await call("create_article", title="MCP Windows smoke", text="An opening sentence.")
    identifier = article["id"]
    article = await call(
        "rename_article",
        article_id=identifier,
        title="Delivered by MCP",
        expected_row_version=article["row_version"],
    )
    article = await call(
        "replace_text",
        article_id=identifier,
        old_text="An opening",
        new_text="The opening",
        expected_row_version=article["row_version"],
    )
    article = await call(
        "append_text",
        article_id=identifier,
        text="An ordinary appendix.",
        expected_row_version=article["row_version"],
    )
    chapter = {
        "article_id": identifier,
        "story_key": "smoke-story",
        "chapter_key": "second",
        "retry_key": "delivery-1",
        "source_url": "https://example.com/chapter-2",
        "title": "Chapter two",
        "text": "Chapter two. A new beginning.",
        "order_index": 2,
        "expected_row_version": article["row_version"],
    }
    results = await asyncio.gather(
        call("deliver_chapter", **chapter), call("deliver_chapter", **chapter)
    )
    assert {item["outcome"] for item in results} == {"imported", "already_imported"}
    assert (await call("deliver_chapter", **chapter))["outcome"] == "already_imported"
    receipts = await call("list_chapters", article_id=identifier)
    assert len(receipts["items"]) == 1
    assert receipts["items"][0]["chapter_key"] == chapter["chapter_key"]
    conflict = await session.call_tool("reader_deliver_chapter", chapter | {"text": "Changed"})
    assert conflict.is_error and conflict.structured_content["outcome"] == "conflict"
    listed = await call("list_articles", query="Delivered", limit=1)
    assert listed["items"][0]["id"] == identifier
    page = await call("read_article", article_id=identifier, limit=9)
    texts = [page["text"]]
    while page["next_offset"] is not None:
        page = await call(
            "read_article",
            article_id=identifier,
            offset=page["next_offset"],
            limit=9,
            expected_row_version=page["article"]["row_version"],
        )
        texts.append(page["text"])
    text = "".join(texts)
    assert text.count(chapter["text"]) == 1
    assert "The opening sentence." in text
    return identifier, chapter, text


async def run(executable: Path, root: Path) -> dict:
    (root / "isolated-reader-agent-smoke").touch()
    python = str(Path(sys.executable).resolve())
    with service(root) as (url, app):
        owner_token = app.state.container.auth.token
        with httpx.Client(
            base_url=url, trust_env=False, headers={"Authorization": "Bearer " + owner_token}
        ) as owner:
            assert owner.get("v1/reader/agent-access/grants").json()["grants"] == []
            folder = owner.post("v1/reader/folders", json={"name": "Agent workspace"}).json()
        provision = await asyncio.to_thread(
            desktop,
            executable,
            root,
            service_url=url,
            python=python,
            phase="provision",
            folder_id=folder["id"],
        )
        connection = AgentConnection.load(Path(provision["config_path"]))
        credential = connection.credential()
        parameters = StdioServerParameters(
            command=python,
            args=["-m", "reader_agent.server", "--config", provision["config_path"]],
        )
        async with Client(parameters) as session:
            identifier, chapter, article_text = await exercise(session)
        with httpx.Client(
            base_url=url, trust_env=False, headers={"Authorization": "Bearer " + credential}
        ) as restricted:
            assert restricted.get("v1/reader/documents").status_code == 401
            assert restricted.get("v1/reader/agent-access/grants").status_code == 401
        port = int(url.split(":")[-1].rstrip("/"))
    # Restart both service and MCP host against the same isolated persisted data.
    with service(root, port) as (url, _):
        async with Client(parameters) as session:
            retry = await session.call_tool("reader_deliver_chapter", chapter)
            assert retry.structured_content["outcome"] == "already_imported"
            desktop_result = await asyncio.to_thread(
                desktop,
                executable,
                root,
                service_url=url,
                python=python,
                phase="read-revoke",
                folder_id=folder["id"],
                grant_id=provision["grant_id"],
                article_id=identifier,
                expected_text=article_text,
            )
            denied = await session.call_tool("reader_read_article", {"article_id": identifier})
            assert denied.is_error and denied.structured_content["outcome"] == "unauthorized"
        # Already-running HTTP peers lose access too, independently of local key deletion.
        with httpx.Client(
            base_url=url, trust_env=False, headers={"Authorization": "Bearer " + credential}
        ) as restricted:
            assert restricted.get("v1/reader/agent/articles/" + identifier).status_code == 403
        with httpx.Client(
            base_url=url, trust_env=False, headers={"Authorization": "Bearer " + owner_token}
        ) as owner:
            assert owner.get("v1/reader/documents/" + identifier).status_code == 200
    return {
        "options_provision": provision["provisioned"],
        "dpapi_cross_language": provision["dpapi_cross_language"],
        "stdio_mcp_tools": 9,
        "article_crud": True,
        "chapter_concurrent_retry": True,
        "service_and_mcp_restart": True,
        "scope_and_revocation": True,
        "desktop": desktop_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reader-exe", required=True, type=Path)
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    if os.name != "nt" or not args.reader_exe.is_file():
        parser.error("Use Windows and an existing built/published Reader executable.")
    with tempfile.TemporaryDirectory(prefix="tts-reader-agent-smoke-") as directory:
        root = Path(directory)
        result = asyncio.run(run(args.reader_exe.resolve(), root))
        if args.artifacts:
            args.artifacts.mkdir(parents=True, exist_ok=True)
            for name in ("agent-options.png", "agent-article.png"):
                shutil.copyfile(root / name, args.artifacts / name)
            (args.artifacts / "smoke.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
