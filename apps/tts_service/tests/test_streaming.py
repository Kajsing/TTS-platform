from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from tts_service.config import AppConfig
from tts_service.main import create_app


def build_test_bundle(
    tmp_path: Path,
    *,
    config_data: dict | None = None,
) -> tuple[TestClient, dict[str, str], object]:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "voices").mkdir()
    (models_dir / "MANIFEST.json").write_text(
        """
        {
          "version": 1,
          "voices": [
            {
              "id": "manifest-voice",
              "name": "Manifest Voice",
              "engine": "sherpa_onnx",
              "language": "en",
              "sample_rate_hz": 22050,
              "license": "Apache-2.0",
              "source": "models/voices/manifest-voice",
              "tags": ["manifest"],
              "capabilities": {
                "supports_pitch": false,
                "supports_streaming": true,
                "supports_multi_speaker": false
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    base_config = {"tts": {"default_voice": "manifest-voice"}}
    if config_data:
        base_config.update(config_data)
    app = create_app(config=AppConfig.from_mapping(base_config), repo_root=tmp_path)
    auth_headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    return TestClient(app), auth_headers, app


def _read_next_message(websocket):
    message = websocket.receive()
    if message.get("bytes") is not None:
        return ("bytes", message["bytes"])
    if message.get("text") is not None:
        return ("json", json.loads(message["text"]))
    return ("other", message)


def test_websocket_stream_requires_auth(tmp_path: Path) -> None:
    client, _, _ = build_test_bundle(tmp_path)

    with client.websocket_connect("/v1/tts/stream") as websocket:
        message_type, payload = _read_next_message(websocket)

    assert message_type == "json"
    assert payload["type"] == "error"
    assert payload["error"]["type"] == "unauthorized"


def test_websocket_stream_returns_audio_frames_and_done_event(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "text": "Hello streaming world.",
                    "voice": "manifest-voice",
                },
            }
        )

        started = websocket.receive_json()
        assert started["type"] == "started"
        assert started["job_id"]

        binary_frames = 0
        done_payload = None
        for _ in range(64):
            message_type, payload = _read_next_message(websocket)
            if message_type == "bytes":
                binary_frames += 1
                assert payload
                continue
            if message_type == "json" and payload["type"] == "done":
                done_payload = payload
                break

        assert binary_frames > 0
        assert done_payload is not None
        assert done_payload["chunks_sent"] == binary_frames

    health_response = client.get("/v1/health")
    streaming_metrics = health_response.json()["streaming"]
    assert streaming_metrics["total_streams"] >= 1
    assert streaming_metrics["completed_streams"] >= 1
    assert streaming_metrics["active_streams"] == 0


def test_websocket_stream_can_be_cancelled(tmp_path: Path, monkeypatch) -> None:
    client, auth_headers, app = build_test_bundle(tmp_path)
    original_stream = app.state.container.backend.synthesize_stream

    def delayed_stream(self, request):
        for index, chunk in enumerate(original_stream(request)):
            yield chunk
            if index == 0:
                time.sleep(0.05)

    monkeypatch.setattr(type(app.state.container.backend), "synthesize_stream", delayed_stream)

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "text": "Hello streaming world.",
                    "voice": "manifest-voice",
                },
            }
        )

        started = websocket.receive_json()
        assert started["type"] == "started"

        first_message_type, first_payload = _read_next_message(websocket)
        assert first_message_type == "bytes"
        assert first_payload

        websocket.send_json({"type": "cancel"})

        cancelled_payload = None
        for _ in range(32):
            message_type, payload = _read_next_message(websocket)
            if message_type == "json" and payload["type"] == "cancelled":
                cancelled_payload = payload
                break

        assert cancelled_payload is not None
        assert cancelled_payload["chunks_sent"] >= 1

    health_response = client.get("/v1/health")
    streaming_metrics = health_response.json()["streaming"]
    assert streaming_metrics["cancelled_streams"] >= 1
