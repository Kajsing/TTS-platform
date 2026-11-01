from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
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


async def _response_error_payload(tmp_path, response, *, operation="list"):
    requests = []

    def handler(request):
        requests.append(request)
        return response

    client = AgentHttpClient(
        AgentConnection("http://127.0.0.1:7777/", str(uuid4()), tmp_path),
        credential_loader=lambda: "test-secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(AgentServiceError) as error:
            await client.call(operation, title="Private", text="Private")
        assert len(requests) == 1
        return error.value.payload()
    finally:
        await client.close()


@pytest.mark.parametrize(
    "status,code,reason",
    [
        (429, "secret-type", "rate_limited"),
        (409, "reader_document_locked", "reader_document_locked"),
        (503, "reader_database_busy", "reader_database_busy"),
    ],
)
def test_busy_reasons_preserve_legacy_code_without_raw_details(tmp_path, status, code, reason):
    result = asyncio.run(
        _response_error_payload(
            tmp_path,
            httpx.Response(
                status,
                json={
                    "error": {
                        "type": code,
                        "message": "SECRET PRIVATE TEXT",
                        "details": {"document_id": "private-identifier", "secret": "SECRET"},
                    }
                },
            ),
        )
    )
    assert result == {"outcome": "busy", "code": "reader_busy", "retryable": True, "reason": reason}


@pytest.mark.parametrize(
    "details,headers,expected",
    [
        ({"retry_after_seconds": 12}, {}, 12),
        ({"retry_after_seconds": 1.1}, {}, 2),
        ({"retry_after_seconds": 0}, {}, 0),
        ({"retry_after_seconds": 86400}, {}, 86400),
        ({}, {"Retry-After": "31"}, 31),
        ({"retry_after_seconds": 40}, {"Retry-After": "31"}, 40),
        ({"retry_after_seconds": 12}, {"Retry-After": "31"}, 31),
        ({"retry_after_seconds": True}, {}, None),
        ({"retry_after_seconds": "SECRET"}, {}, None),
        ({"retry_after_seconds": -1}, {}, None),
        ({"retry_after_seconds": 86401}, {}, None),
        ({"retry_after_seconds": 2**1024}, {}, None),
        ({"retry_after_seconds": float("inf")}, {}, None),
        ({"retry_after_seconds": float("nan")}, {}, None),
        ({"retry_after_seconds": {}}, {}, None),
        ({"retry_after_seconds": []}, {}, None),
        ({}, {"Retry-After": "-1"}, None),
        ({}, {"Retry-After": "1.5"}, None),
        ({}, {"Retry-After": "86401"}, None),
        ({}, {"Retry-After": "SECRET PRIVATE TEXT"}, None),
        ({}, {"Retry-After": "1" * 129}, None),
    ],
)
def test_retry_timing_is_validated_and_uses_the_longer_supplied_delay(
    tmp_path, details, headers, expected
):
    response = httpx.Response(
        429,
        headers=headers,
        content=json.dumps({"error": {"type": "rate_limited", "details": details}}).encode(),
    )
    result = asyncio.run(_response_error_payload(tmp_path, response, operation="create"))
    assert result.get("retry_after_seconds") == expected
    assert set(result) <= {"outcome", "code", "retryable", "reason", "retry_after_seconds"}


@pytest.mark.parametrize(
    "header,expected",
    [
        ("Sun, 01 Nov 2026 12:00:31 GMT", 31),
        ("Sun, 01 Nov 2026 11:59:59 GMT", 0),
        ("Tue, 03 Nov 2026 12:00:00 GMT", None),
        ("Sun, 01 Nov 2026 12:00:31", None),
    ],
)
def test_retry_after_http_date_is_bounded_and_relative_to_now(
    tmp_path, monkeypatch, header, expected
):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 1, 12, tzinfo=timezone.utc)

    monkeypatch.setattr("reader_agent.client.datetime", FixedDatetime)
    response = httpx.Response(429, headers={"Retry-After": header}, json={"error": {}})
    result = asyncio.run(_response_error_payload(tmp_path, response))
    assert result.get("retry_after_seconds") == expected


@pytest.mark.parametrize(
    "details,header,expected",
    [
        ({"request_budget": "agent"}, None, "agent"),
        ({}, "background", "background"),
        ({"request_budget": "playback"}, "playback", "playback"),
        ({"request_budget": "agent"}, "playback", None),
        ({"request_budget": "SECRET"}, "agent", "agent"),
        ({"request_budget": {}}, "SECRET", None),
        ({"request_budget": []}, None, None),
    ],
)
def test_only_unambiguous_allowlisted_request_budgets_are_exposed(
    tmp_path, details, header, expected
):
    headers = {"X-TTS-Request-Budget": header} if header is not None else {}
    response = httpx.Response(429, headers=headers, json={"error": {"details": details}})
    result = asyncio.run(_response_error_payload(tmp_path, response))
    assert result.get("request_budget") == expected
    assert "SECRET" not in str(result)


def test_playback_lock_has_no_guessed_deadline_but_storage_can_supply_one(tmp_path):
    headers = {"Retry-After": "20", "X-TTS-Request-Budget": "agent"}
    details = {"retry_after_seconds": 10, "request_budget": "agent"}
    playback = asyncio.run(
        _response_error_payload(
            tmp_path,
            httpx.Response(
                409,
                headers=headers,
                json={"error": {"type": "reader_document_locked", "details": details}},
            ),
        )
    )
    assert "retry_after_seconds" not in playback and "request_budget" not in playback
    storage = asyncio.run(
        _response_error_payload(
            tmp_path,
            httpx.Response(
                503,
                headers=headers,
                json={"error": {"type": "reader_database_busy", "details": details}},
            ),
        )
    )
    assert storage["retry_after_seconds"] == 20 and storage["request_budget"] == "agent"


@pytest.mark.parametrize("details", [None, [], "SECRET", True])
def test_malformed_error_fields_never_escape_sanitization(tmp_path, details):
    response = httpx.Response(429, json={"error": {"type": {"SECRET": []}, "details": details}})
    result = asyncio.run(_response_error_payload(tmp_path, response))
    assert result == {
        "outcome": "busy",
        "code": "reader_busy",
        "retryable": True,
        "reason": "rate_limited",
    }
