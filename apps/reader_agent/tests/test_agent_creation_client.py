from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from reader_agent.client import AgentHttpClient, AgentServiceError
from reader_agent.config import AgentConnection


def _client(tmp_path, handler):
    return AgentHttpClient(
        AgentConnection("http://127.0.0.1:7777/", str(uuid4()), tmp_path),
        credential_loader=lambda: "test-secret",
        transport=httpx.MockTransport(handler),
    )


def test_create_once_uses_fixed_create_route_and_preserves_retry_payload(tmp_path):
    requests = []
    payload = {"title": "Part", "text": "Text", "retry_key": "part:1"}

    def handler(request):
        requests.append(request)
        return httpx.Response(201, json={"id": "article"})

    async def run():
        client = _client(tmp_path, handler)
        try:
            assert await client.call("create_once", **payload) == {"id": "article"}
        finally:
            await client.close()

    asyncio.run(run())
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "http://127.0.0.1:7777/v1/reader/agent/articles"
    assert json.loads(requests[0].content) == payload


@pytest.mark.parametrize(
    "retry_key", [None, "", " ", "x" * 201, " " * 200 + "x", "bad\x00key", True, 2]
)
def test_create_once_requires_valid_identity_before_http(tmp_path, retry_key):
    def handler(request):
        pytest.fail("Invalid creation identity must not reach HTTP")

    async def run():
        client = _client(tmp_path, handler)
        try:
            arguments = {"title": "Part", "text": "Text"}
            if retry_key is not None:
                arguments["retry_key"] = retry_key
            with pytest.raises(AgentServiceError) as error:
                await client.call("create_once", **arguments)
            assert error.value.payload() == {
                "outcome": "invalid_request",
                "code": "reader_invalid_request",
                "retryable": False,
            }
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("operation,retryable", [("create_once", True), ("create", False)])
def test_creation_timeout_reports_retry_safety_without_automatically_replaying(
    tmp_path, operation, retryable
):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("SECRET PRIVATE TEXT", request=request)

    async def run():
        client = _client(tmp_path, handler)
        try:
            with pytest.raises(AgentServiceError) as error:
                arguments = {"title": "Part", "text": "Text"}
                if operation == "create_once":
                    arguments["retry_key"] = "part:1"
                await client.call(operation, **arguments)
            assert error.value.payload() == {
                "outcome": "service_unavailable",
                "code": "request_timeout",
                "retryable": retryable,
            }
        finally:
            await client.close()

    asyncio.run(run())
    assert len(requests) == 1


def test_create_once_mcp_tool_is_idempotent_and_supplies_the_identity(tmp_path):
    mcp = pytest.importorskip("mcp")
    if not hasattr(mcp, "Client"):
        pytest.skip("MCP SDK 2 is required")
    from reader_agent.server import build_server

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(201, json={"id": "article"})

    async def run():
        server = build_server(_client(tmp_path, handler))
        async with mcp.Client(server) as session:
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert tools["reader_create_article_once"].annotations.idempotent_hint
            assert not tools["reader_create_article"].annotations.idempotent_hint
            result = await session.call_tool(
                "reader_create_article_once",
                {"title": "Part", "text": "Text", "retry_key": "part:1"},
            )
            assert not result.is_error and result.structured_content == {"id": "article"}

    asyncio.run(run())
    assert len(requests) == 1
    assert json.loads(requests[0].content)["retry_key"] == "part:1"
