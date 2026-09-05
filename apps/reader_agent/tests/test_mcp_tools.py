from __future__ import annotations

import asyncio

import httpx
import pytest
from reader_agent.client import AgentHttpClient
from reader_agent.config import AgentConnection
from reader_agent.server import build_server
from tts_service.config import AppConfig
from tts_service.main import create_app

mcp = pytest.importorskip("mcp")
if not hasattr(mcp, "Client"):
    pytest.skip("MCP SDK 2 is required for the optional agent tests", allow_module_level=True)


def test_real_mcp_session_through_service_scope_and_chapter_retry(tmp_path):
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"warmup_on_start": False},
                "reader": {"home_path": str(tmp_path / "reader"), "exports": {"formats": ["wav"]}},
            }
        ),
        repo_root=tmp_path,
    )

    async def run():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 34567))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:7777"
        ) as owner:
            owner.headers["Authorization"] = "Bearer " + app.state.container.auth.token
            folder = (await owner.post("/v1/reader/folders", json={"name": "Agent test"})).json()
            provision = (
                await owner.post("/v1/reader/agent-access/grants", json={"folder_id": folder["id"]})
            ).json()
            connection = AgentConnection(
                "http://127.0.0.1:7777/", provision["grant"]["id"], tmp_path
            )
            server = build_server(
                AgentHttpClient(
                    connection,
                    credential_loader=lambda: provision["credential"],
                    transport=transport,
                )
            )
            async with mcp.Client(server) as session:
                tools = (await session.list_tools()).tools
                names = {tool.name for tool in tools}
                assert names == {
                    "reader_workspace",
                    "reader_list_articles",
                    "reader_read_article",
                    "reader_create_article",
                    "reader_rename_article",
                    "reader_append_text",
                    "reader_replace_text",
                    "reader_list_chapters",
                    "reader_deliver_chapter",
                }
                annotations = {tool.name: tool.annotations for tool in tools}
                assert annotations["reader_read_article"].read_only_hint
                assert annotations["reader_deliver_chapter"].idempotent_hint
                workspace = await session.call_tool("reader_workspace", {})
                assert workspace.structured_content["folder_id"] == folder["id"]
                created = await session.call_tool(
                    "reader_create_article", {"title": "Story", "text": "First paragraph."}
                )
                assert not created.is_error, created
                identifier = created.structured_content["id"]
                read = await session.call_tool("reader_read_article", {"article_id": identifier})
                assert read.structured_content["text"] == "First paragraph."
                edited = await session.call_tool(
                    "reader_replace_text",
                    {
                        "article_id": identifier,
                        "old_text": "First",
                        "new_text": "Opening",
                        "expected_row_version": 1,
                    },
                )
                assert not edited.is_error, edited
                payload = {
                    "article_id": identifier,
                    "story_key": "story",
                    "chapter_key": "two",
                    "retry_key": "one",
                    "source_url": "https://example.com/two",
                    "title": "Two",
                    "text": "Chapter two.",
                    "expected_row_version": 2,
                }
                imported = await session.call_tool("reader_deliver_chapter", payload)
                assert imported.structured_content["outcome"] == "imported", imported
                retry = await session.call_tool("reader_deliver_chapter", payload)
                assert retry.structured_content["outcome"] == "already_imported"
                conflict = await session.call_tool(
                    "reader_deliver_chapter", payload | {"text": "Changed"}
                )
                assert conflict.is_error and conflict.structured_content["outcome"] == "conflict"
                await owner.delete("/v1/reader/agent-access/grants/" + provision["grant"]["id"])
                denied = await session.call_tool("reader_read_article", {"article_id": identifier})
                assert denied.is_error and denied.structured_content["outcome"] == "unauthorized"

    asyncio.run(run())
