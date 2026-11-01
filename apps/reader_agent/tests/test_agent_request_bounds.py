from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from reader_agent import client as client_module
from reader_agent.client import AgentHttpClient, AgentServiceError
from reader_agent.config import AgentConnection


@pytest.mark.parametrize("text", ["😀" * 20, "\ud800"])
def test_encoded_body_limit_and_invalid_unicode_fail_before_http(tmp_path, monkeypatch, text):
    monkeypatch.setattr(client_module, "MAX_REQUEST_BYTES", 100)

    def forbidden(request):
        pytest.fail("Invalid or oversized encoded requests must not reach HTTP")

    async def run():
        connection = AgentConnection("http://127.0.0.1:7777/", str(uuid.uuid4()), tmp_path)
        client = AgentHttpClient(
            connection, credential_loader=lambda: "test", transport=httpx.MockTransport(forbidden)
        )
        try:
            with pytest.raises(AgentServiceError) as error:
                await client.call("create", title="Title", text=text)
            assert error.value.payload() == {
                "outcome": "invalid_request", "code": "reader_invalid_request", "retryable": False
            }
        finally:
            await client.close()

    asyncio.run(run())
