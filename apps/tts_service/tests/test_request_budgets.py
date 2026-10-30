from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from reader_core import ReaderLibrary
from tts_service import security
from tts_service.config import AppConfig
from tts_service.errors import APIError
from tts_service.main import create_app

CASES = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/reader/request_budget_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("method,path,budget", CASES)
def test_route_budget_contract(method, path, budget):
    assert security.request_budget(method, path) == budget


def test_sliding_window_is_atomic_and_recovers_at_retry_deadline(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(security, "time", SimpleNamespace(monotonic=lambda: now[0]))
    limiter = security.RateLimiter(7, budget="playback")

    def admit(_):
        try:
            limiter.check("same-client")
            return True
        except APIError as error:
            assert error.headers == {"Retry-After": "60", "X-TTS-Request-Budget": "playback"}
            assert error.error.details["request_budget"] == "playback"
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(admit, range(100))) == 7
    now[0] = 159.2
    with pytest.raises(APIError) as rejected:
        limiter.check("same-client")
    assert rejected.value.headers["Retry-After"] == "1"
    now[0] = 160
    limiter.check("same-client")
    assert len(limiter._events["same-client"]) == 1


@pytest.mark.parametrize("limit", [0, -1])
def test_playback_limit_must_be_positive(limit):
    with pytest.raises(ValueError, match="playback_requests_per_minute"):
        AppConfig.from_mapping({"limits": {"playback_requests_per_minute": limit}})


def test_background_saturation_preserves_large_article_playback_and_positions(tmp_path):
    config = AppConfig.from_mapping(
        {
            "tts": {"warmup_on_start": False},
            "backend": {"mode": "stub"},
            "reader": {"home_path": str(tmp_path / "reader"), "exports": {"formats": ["wav"]}},
            "limits": {"requests_per_minute": 30, "playback_requests_per_minute": 90},
        }
    )
    app = create_app(config=config, repo_root=tmp_path)
    headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    service = app.state.container.reader.service
    # Seed isolated multi-million-character data without a monolithic HTTP read.
    text = "Short opening.\n\n" + "\n\n".join("Synthetic paragraph. " * 65 for _ in range(1600))
    document = ReaderLibrary(service.repository).create_plain_text_document(
        title="Large", text=text
    )
    assert document.total_characters > 2_000_000
    path = f"/v1/reader/documents/{document.id}"
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        for _ in range(30):
            assert client.get("/v1/service/status", headers=headers).status_code == 200
        for _ in range(50):
            denied = client.get("/v1/reader/desktop/open-requests/next", headers=headers)
            assert denied.status_code == 429
            assert denied.headers[security.REQUEST_BUDGET_HEADER] == "background"
        # Caller-controlled headers cannot promote an import/library operation.
        assert (
            client.get(
                "/v1/reader/documents",
                headers={**headers, security.REQUEST_BUDGET_HEADER: "playback"},
            ).status_code
            == 429
        )
        assert client.get(path, headers=headers).status_code == 200
        page = client.get(path + "/blocks?limit=2", headers=headers).json()
        assert len(page["blocks"]) == 2
        assert len(json.dumps(page)) < 10_000
        block = page["blocks"][0]
        cursor = {
            "block_id": block["id"],
            "block_ordinal": 0,
            "character_offset": 0,
            "content_revision": document.content_revision,
        }
        for version in range(60):
            saved = client.put(
                path + "/position",
                headers=headers,
                json={
                    "cursor": cursor,
                    "expected_row_version": version,
                    "pipeline_version": 1,
                    "rules_version": 1,
                },
            )
            assert saved.status_code == 200, saved.text
        for _ in range(2):
            with client.websocket_connect("/v1/reader/stream", headers=headers) as ws:
                ws.send_json(
                    {
                        "type": "start",
                        "payload": {
                            "document_id": document.id,
                            "cursor": cursor,
                            "window": {"max_blocks": 1},
                        },
                    }
                )
                started = ws.receive_json()
                assert started["type"] == "started"
                pcm = 0
                while True:
                    message = ws.receive()
                    if message.get("bytes"):
                        pcm += len(message["bytes"])
                    elif message.get("text"):
                        event = json.loads(message["text"])
                        assert event["type"] != "error", event
                        if event["type"] == "done":
                            assert event["next_window_available"]
                            cursor = event["cursor"]
                            break
                assert pcm > 0
                ws.send_json({"type": "release", "stream_id": started["stream_id"]})
        # Playback remains enforced too, and saturation cannot spill into the agent budget.
        while client.get(path + "/position", headers=headers).status_code == 200:
            pass
        limited = client.get(path + "/position", headers=headers)
        assert limited.headers[security.REQUEST_BUDGET_HEADER] == "playback"
        with client.websocket_connect("/v1/tts/stream", headers=headers) as ws:
            assert ws.receive_json()["error"]["details"]["request_budget"] == "playback"
        app.state.reader_agent_limiter.check("local-agent")
        assert client.get("/v1/health").status_code == 200


def test_playback_saturation_does_not_block_background_and_auth_still_applies(tmp_path):
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"warmup_on_start": False},
                "limits": {"requests_per_minute": 5, "playback_requests_per_minute": 1},
                "reader": {"home_path": str(tmp_path / "reader")},
            }
        ),
        repo_root=tmp_path,
    )
    headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    with TestClient(app) as client:
        # A request without a credential still consumes the selected budget, as before.
        assert client.get("/v1/reader/documents/missing/position").status_code == 401
        assert (
            client.get("/v1/reader/documents/missing/position", headers=headers).status_code == 429
        )
        assert client.get("/v1/reader/capabilities", headers=headers).status_code == 200
        assert client.get("/v1/reader/capabilities").status_code == 401
