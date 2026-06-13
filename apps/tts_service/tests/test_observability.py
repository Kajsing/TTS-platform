from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from tts_service.config import AppConfig
from tts_service.main import create_app


def build_test_bundle(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
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
    app = create_app(
        config=AppConfig.from_mapping({"tts": {"default_voice": "manifest-voice"}}),
        repo_root=tmp_path,
    )
    return TestClient(app), {"Authorization": f"Bearer {app.state.container.auth.token}"}


def test_health_exposes_observability_snapshot_and_request_id(tmp_path: Path) -> None:
    client, auth_headers = build_test_bundle(tmp_path)

    voices_response = client.get("/v1/voices")
    synth_response = client.post(
        "/v1/tts",
        headers=auth_headers,
        json={"text": "Hello world", "voice": "manifest-voice"},
    )
    health_response = client.get("/v1/health")

    assert voices_response.headers["x-request-id"]
    assert synth_response.headers["x-request-id"]
    snapshot = health_response.json()["observability"]
    assert snapshot["enabled"] is True
    assert snapshot["requests"]["request_count"] >= 2
    assert snapshot["requests"]["per_endpoint"]["/v1/voices"] >= 1
    assert snapshot["synthesis"]["request_count"] >= 1
    assert snapshot["synthesis"]["modes"]["sync"] >= 1


def test_health_exposes_job_observability(tmp_path: Path) -> None:
    client, auth_headers = build_test_bundle(tmp_path)

    create_response = client.post(
        "/v1/tts/jobs",
        headers=auth_headers,
        json={"text": "Hello world", "voice": "manifest-voice"},
    )
    job_id = create_response.json()["job_id"]
    client.get(f"/v1/tts/jobs/{job_id}", headers=auth_headers)
    client.get(f"/v1/tts/jobs/{job_id}/result", headers=auth_headers)
    health_response = client.get("/v1/health")

    snapshot = health_response.json()["observability"]["jobs"]
    assert snapshot["created_count"] >= 1
    assert snapshot["completed_count"] >= 1


def test_http_request_log_omits_query_token_and_body_text(tmp_path: Path, monkeypatch) -> None:
    client, auth_headers = build_test_bundle(tmp_path)
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    unsafe_request_id = f"Bearer {token}"
    log_messages: list[str] = []
    monkeypatch.setattr(
        client.app.state.container.observability.logger,
        "info",
        log_messages.append,
    )

    response = client.post(
        "/v1/tts?token=query-secret&text=query-text",
        headers={**auth_headers, "x-request-id": unsafe_request_id},
        json={
            "text": "body secret text",
            "voice": "manifest-voice",
        },
    )

    assert response.status_code == 200
    assert log_messages
    log_entry = json.loads(log_messages[-1])
    UUID(log_entry["request_id"])
    assert response.headers["x-request-id"] == log_entry["request_id"]
    assert log_entry["request_id"] != unsafe_request_id
    assert log_entry["endpoint"] == "/v1/tts"
    serialized = json.dumps(log_entry)
    assert token not in serialized
    assert "query-secret" not in serialized
    assert "query-text" not in serialized
    assert "body secret text" not in serialized


def test_http_request_log_preserves_safe_client_request_id(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_test_bundle(tmp_path)
    log_messages: list[str] = []
    monkeypatch.setattr(
        client.app.state.container.observability.logger,
        "info",
        log_messages.append,
    )

    response = client.get("/v1/voices", headers={"x-request-id": "reader-setup-1"})

    assert response.status_code == 200
    log_entry = json.loads(log_messages[-1])
    assert response.headers["x-request-id"] == "reader-setup-1"
    assert log_entry["request_id"] == "reader-setup-1"
