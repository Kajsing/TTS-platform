from __future__ import annotations

import asyncio
import json
from uuid import uuid4

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
                    "reader_create_article_once",
                    "reader_rename_article",
                    "reader_append_text",
                    "reader_replace_text",
                    "reader_list_chapters",
                    "reader_deliver_chapter",
                    "reader_list_content_chapters",
                    "reader_read_chapter",
                    "reader_search_article",
                    "reader_preview_import",
                    "reader_deliver_import_chapter",
                    "reader_story_status",
                }
                annotations = {tool.name: tool.annotations for tool in tools}
                assert annotations["reader_read_article"].read_only_hint
                assert annotations["reader_deliver_chapter"].idempotent_hint
                assert annotations["reader_create_article_once"].idempotent_hint
                workspace = await session.call_tool("reader_workspace", {})
                assert workspace.structured_content["folder_id"] == folder["id"]
                created = await session.call_tool(
                    "reader_create_article", {"title": "Story", "text": "First paragraph."}
                )
                assert not created.is_error, created
                identifier = created.structured_content["id"]
                once_payload = {"title": "Once", "text": "Kept.", "retry_key": "creation-1"}
                once = await session.call_tool("reader_create_article_once", once_payload)
                replay = await session.call_tool("reader_create_article_once", once_payload)
                assert not replay.is_error
                assert once.structured_content["id"] == replay.structured_content["id"]
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
                version = imported.structured_content["result_row_version"]
                content = await session.call_tool(
                    "reader_list_content_chapters",
                    {"article_id": identifier, "expected_row_version": version},
                )
                assert not content.is_error
                assert len(content.structured_content["items"]) == 2
                texts = []
                for item in content.structured_content["items"]:
                    page_offset = 0
                    while True:
                        page = await session.call_tool(
                            "reader_read_chapter",
                            {"article_id": identifier, "chapter_id": item["id"],
                             "expected_row_version": version, "offset": page_offset, "limit": 5},
                        )
                        assert not page.is_error
                        texts.append(page.structured_content["text"])
                        page_offset = page.structured_content["next_offset"]
                        if page_offset is None:
                            break
                assert "".join(texts) == "Opening paragraph.\n\nChapter two."
                found = await session.call_tool(
                    "reader_search_article",
                    {"article_id": identifier, "expected_row_version": version,
                     "query": "paragraph.\n\nChapter"},
                )
                assert not found.is_error and len(found.structured_content["items"]) == 1
                chapters = [
                    {"story_key": "managed", "chapter_key": str(index),
                     "retry_key": "delivery-" + str(index), "title": "Chapter " + str(index),
                     "source_url": "https://example.com/" + str(index), "text": "abcdefgh",
                     "order_index": index}
                    for index in range(1, 4)
                ]
                preparation = {"title": "T", "retry_key": "managed-plan", "chapters": chapters,
                               "max_characters": 22}
                preview = await session.call_tool("reader_preview_import", preparation)
                assert not preview.is_error, preview
                plan = preview.structured_content
                assert [part["codepoints"] for part in plan["parts"]] == [21, 11]
                replay = await session.call_tool("reader_preview_import", preparation)
                assert replay.structured_content["plan_id"] == plan["plan_id"]
                for chapter in chapters:
                    delivery = {"plan_id": plan["plan_id"], "chapter": chapter}
                    imported_part = await session.call_tool(
                        "reader_deliver_import_chapter", delivery
                    )
                    assert not imported_part.is_error, imported_part
                    replay = await session.call_tool("reader_deliver_import_chapter", delivery)
                    assert replay.structured_content["outcome"] == "already_imported"
                assert imported_part.structured_content["complete"]
                status = await session.call_tool("reader_story_status", {"story_key": "managed"})
                assert not status.is_error
                assert len(status.structured_content["items"]) == 3
                assert status.structured_content["current_text_verified"] is False
                conflict = await session.call_tool(
                    "reader_deliver_chapter", payload | {"text": "Changed"}
                )
                assert conflict.is_error and conflict.structured_content["outcome"] == "conflict"
                await owner.delete("/v1/reader/agent-access/grants/" + provision["grant"]["id"])
                denied = await session.call_tool("reader_read_article", {"article_id": identifier})
                assert denied.is_error and denied.structured_content["outcome"] == "unauthorized"

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,code,reason,expected_timing",
    [
        (
            429,
            "rate_limited",
            "rate_limited",
            {"retry_after_seconds": 17, "request_budget": "agent"},
        ),
        (409, "reader_document_locked", "reader_document_locked", {}),
        (503, "reader_database_busy", "reader_database_busy", {}),
    ],
)
def test_mcp_busy_results_preserve_safe_reason_and_timing(
    tmp_path, status, code, reason, expected_timing
):
    def handler(request):
        return httpx.Response(
            status,
            headers={"Retry-After": "17", "X-TTS-Request-Budget": "agent"} if status == 429 else {},
            json={"error": {"type": code, "message": "SECRET PRIVATE TEXT"}},
        )

    async def run():
        server = build_server(
            AgentHttpClient(
                AgentConnection("http://127.0.0.1:7777/", str(uuid4()), tmp_path),
                credential_loader=lambda: "test-secret",
                transport=httpx.MockTransport(handler),
            )
        )
        async with mcp.Client(server) as session:
            result = await session.call_tool("reader_list_articles", {})
            expected = {
                "outcome": "busy",
                "code": "reader_busy",
                "retryable": True,
                "reason": reason,
                **expected_timing,
            }
            assert result.is_error
            assert result.structured_content == expected
            assert json.loads(result.content[0].text) == expected

    asyncio.run(run())
