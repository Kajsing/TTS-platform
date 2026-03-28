from __future__ import annotations

from pathlib import Path

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
