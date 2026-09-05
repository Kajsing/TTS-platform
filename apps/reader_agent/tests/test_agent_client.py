from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from reader_agent.client import AgentHttpClient, AgentServiceError
from reader_agent.config import AgentConfigurationError, AgentConnection, local_service_url


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1",
        "http://example.com",
        "http://user@127.0.0.1",
        "http://127.0.0.1/path",
        "http://127.0.0.1/?token=secret",
        "http://127.0.0.1/#fragment",
        "http://127.0.0.1\n",
        "http://127.0.0.1:99999",
        "file:///etc/passwd",
        "http://2130706433",
        "http://localhost.evil",
    ],
)
def test_only_literal_loopback_service_connections(url):
    with pytest.raises(AgentConfigurationError):
        local_service_url(url)


def test_localhost_is_pinned_and_config_has_no_secret_field(tmp_path):
    assert local_service_url("http://localhost:7777") == "http://127.0.0.1:7777/"
    assert local_service_url("http://[::1]:7777/") == "http://[::1]:7777/"
    path = tmp_path / "connection.json"
    payload = {"version": 1, "service_base_url": "http://localhost:7777", "grant_id": str(uuid4())}
    path.write_text(json.dumps(payload), encoding="utf-8")
    connection = AgentConnection.load(path)
    assert connection.grant_id == payload["grant_id"]
    path.write_text(json.dumps(payload | {"version": True}), encoding="utf-8")
    with pytest.raises(AgentConfigurationError):
        AgentConnection.load(path)
    path.write_text(json.dumps(payload | {"credential": "not permitted"}), encoding="utf-8")
    with pytest.raises(AgentConfigurationError):
        AgentConnection.load(path)


@pytest.mark.parametrize(
    "status,code,outcome",
    [
        (403, "secret", "unauthorized"),
        (409, "reader_revision_conflict", "conflict"),
        (409, "reader_agent_conflict", "conflict"),
        (409, "reader_document_locked", "busy"),
        (503, "reader_database_busy", "busy"),
        (503, "secret", "service_unavailable"),
        (429, "secret", "busy"),
        (400, "secret", "invalid_request"),
    ],
)
def test_safe_distinct_error_outcomes(tmp_path, status, code, outcome):
    async def run():
        client = AgentHttpClient(
            AgentConnection("http://127.0.0.1:7777/", str(uuid4()), tmp_path),
            credential_loader=lambda: "test-secret",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    status,
                    json={
                        "error": {"type": code, "message": "test-secret and PRIVATE TEXT"},
                    },
                )
            ),
        )
        try:
            with pytest.raises(AgentServiceError) as error:
                await client.call("list")
            assert error.value.outcome == outcome
            assert "secret" not in str(error.value.payload())
            assert "PRIVATE" not in str(error.value.payload())
        finally:
            await client.close()

    asyncio.run(run())


def test_no_redirects_no_arbitrary_routes_and_no_automatic_write_retry(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://example.com/steal"})

    async def run():
        client = AgentHttpClient(
            AgentConnection("http://localhost:7777", str(uuid4()), tmp_path),
            credential_loader=lambda: "test-secret",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(AgentServiceError, match="redirect_refused"):
                await client.call("create", title="Private", text="Text")
            assert len(requests) == 1
            assert str(requests[0].url) == "http://127.0.0.1:7777/v1/reader/agent/articles"
            with pytest.raises(AgentServiceError):
                await client.call("read", article_id="../../documents")
            with pytest.raises(AgentServiceError):
                await client.call("delete")
            assert len(requests) == 1
        finally:
            await client.close()

    asyncio.run(run())


def test_windows_dpapi_file_roundtrip_and_corruption(tmp_path):
    win32crypt = pytest.importorskip("win32crypt")
    grant_id = str(uuid4())
    connection = AgentConnection("http://127.0.0.1:7777/", grant_id, tmp_path)
    token = "rdr_agent_" + "a" * 43
    path = tmp_path / f"{grant_id}.bin"
    path.write_bytes(
        win32crypt.CryptProtectData(token.encode(), "Reader agent", None, None, None, 1)
    )
    assert token.encode() not in path.read_bytes()
    assert connection.credential() == token
    path.write_bytes(b"corrupted ciphertext")
    with pytest.raises(AgentConfigurationError):
        connection.credential()


@pytest.mark.parametrize("operation,retryable", [("create", False), ("deliver", True)])
def test_uncertain_timeout_never_retries_and_reports_only_safe_retries(
    tmp_path, operation, retryable
):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("PRIVATE TEXT AND SECRET", request=request)

    async def run():
        client = AgentHttpClient(
            AgentConnection("http://127.0.0.1:7777/", str(uuid4()), tmp_path),
            credential_loader=lambda: "test-secret",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(AgentServiceError) as error:
                await client.call(operation, article_id=str(uuid4()), text="Private")
            assert len(requests) == 1
            assert error.value.retryable is retryable
            assert error.value.code == "request_timeout"
            assert "PRIVATE" not in str(error.value.payload())
        finally:
            await client.close()

    asyncio.run(run())


def test_oversized_response_and_grant_mismatch_fail_closed(tmp_path):
    responses = [
        httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)),
        httpx.Response(200, json={"grant_id": str(uuid4())}),
    ]

    async def run():
        client = AgentHttpClient(
            AgentConnection("http://127.0.0.1:7777/", str(uuid4()), tmp_path),
            credential_loader=lambda: "test-secret",
            transport=httpx.MockTransport(lambda _: responses.pop(0)),
        )
        try:
            with pytest.raises(AgentServiceError, match="response_too_large"):
                await client.call("workspace")
            with pytest.raises(AgentServiceError, match="grant_mismatch"):
                await client.call("workspace")
        finally:
            await client.close()

    asyncio.run(run())
