from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE_SCRIPT_PATH = REPO_ROOT / "scripts" / "smoke_service.py"


def test_smoke_service_script_runs_across_public_contract_steps(monkeypatch) -> None:
    smoke_module = _load_smoke_module()
    requested_urls: list[tuple[str, str]] = []
    created_job_ids: list[str] = []

    class FakeResponse:
        def __init__(self, *, json_payload=None, content: bytes = b"") -> None:
            self._json_payload = json_payload
            self.content = content

        def raise_for_status(self) -> None:
            return

        def json(self):
            return self._json_payload

    class FakeHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            return

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, headers=None):
            requested_urls.append(("GET", url))
            if url.endswith("/v1/health"):
                return FakeResponse(
                    json_payload={
                        "status": "ok",
                        "checks": {
                            "backend_ready": True,
                            "default_voice_loaded": True,
                        },
                    }
                )
            if url.endswith("/v1/voices"):
                return FakeResponse(
                    json_payload={
                        "default_voice": "manifest-voice",
                        "voices": [{"id": "manifest-voice"}],
                    }
                )
            if url.endswith("/result"):
                return FakeResponse(content=_wav_bytes())
            if "/v1/tts/jobs/" in url:
                return FakeResponse(json_payload={"status": "completed"})
            raise AssertionError(f"Unexpected GET {url}")

        def post(self, url: str, json=None, headers=None):
            requested_urls.append(("POST", url))
            if url.endswith("/v1/tts"):
                return FakeResponse(content=_wav_bytes())
            if url.endswith("/v1/tts/jobs"):
                created_job_ids.append("job-123")
                return FakeResponse(json_payload={"job_id": "job-123", "status": "queued"})
            raise AssertionError(f"Unexpected POST {url}")

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent_messages: list[dict[str, object]] = []
            self._messages = [
                json.dumps(
                    {
                        "type": "started",
                        "sample_rate_hz": 22050,
                        "channels": 1,
                    }
                ),
                json.dumps({"type": "mark"}),
                b"\x01\x00" * 4096,
                json.dumps({"type": "done"}),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def send(self, message: str) -> None:
            self.sent_messages.append(json.loads(message))

        async def recv(self):
            if not self._messages:
                raise AssertionError("Streaming smoke requested more events than expected.")
            return self._messages.pop(0)

    monkeypatch.setattr(smoke_module.httpx, "Client", FakeHttpClient)
    monkeypatch.setattr(smoke_module.websockets, "connect", lambda *args, **kwargs: FakeWebSocket())

    summary = smoke_module.run_smoke(
        base_url="http://127.0.0.1:7777",
        token="test-token",
        voice=None,
        text="Hello from the automated smoke script test.",
        poll_interval_ms=1,
        job_timeout_s=5.0,
    )

    assert summary["voice"] == "manifest-voice"
    assert summary["health"]["status"] == "ok"
    assert summary["voices"]["count"] == 1
    assert summary["http"]["bytes"] > 0
    assert summary["stream"]["frames"] == 1
    assert summary["stream"]["marks"] == 1
    assert summary["job"]["job_id"] == "job-123"
    assert summary["job"]["status"] == "completed"
    assert ("GET", "http://127.0.0.1:7777/v1/health") in requested_urls
    assert ("POST", "http://127.0.0.1:7777/v1/tts") in requested_urls
    assert created_job_ids == ["job-123"]


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("tts_platform_smoke_service", SMOKE_SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wav_bytes() -> bytes:
    smoke_module = _load_smoke_module()
    return smoke_module.encode_wav_pcm16(
        b"\x01\x00" * 4096,
        sample_rate_hz=22050,
        channels=1,
    )
