from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from tts_service.config import AppConfig
from tts_service.main import create_app


def build_test_client(tmp_path: Path) -> TestClient:
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
                "supports_streaming": false,
                "supports_multi_speaker": false
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    config = AppConfig.from_mapping({"tts": {"default_voice": "manifest-voice"}})
    app = create_app(config=config, repo_root=tmp_path)
    return TestClient(app)


def test_health_endpoint_returns_service_status(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)

    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["default_voice"] == "manifest-voice"


def test_voices_endpoint_returns_registry(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)

    response = client.get("/v1/voices")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_voice"] == "manifest-voice"
    assert payload["voices"][0]["id"] == "manifest-voice"


def test_tts_endpoint_returns_wav_audio(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)

    response = client.post(
        "/v1/tts",
        json={
            "text": "Dr. Smith says hello.",
            "voice": "manifest-voice",
            "format": "wav",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"


def test_tts_endpoint_returns_structured_error_for_unknown_voice(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)

    response = client.post(
        "/v1/tts",
        json={
            "text": "Hello world",
            "voice": "missing-voice",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["type"] == "invalid_request"
    assert payload["error"]["param"] == "voice"
