from __future__ import annotations

from pathlib import Path

from tts_service.config import AppConfig
from tts_service.main import create_app


def test_create_app_bootstraps_registry_from_manifest(
    tmp_path: Path,
) -> None:
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

    assert app.state.container.voice_registry.default_voice is not None
    assert app.state.container.voice_registry.default_voice.id == "manifest-voice"
    assert app.state.container.backend.name == "sherpa_onnx"
    assert app.state.container.text_pipeline is not None
    assert app.state.container.chunk_planner is not None


def test_create_app_marks_backend_not_ready_when_real_assets_are_missing(
    tmp_path: Path,
) -> None:
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
              "backend": {
                "model_type": "vits",
                "model": "models/voices/manifest-voice/model.onnx",
                "tokens": "models/voices/manifest-voice/tokens.txt"
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    config = AppConfig.from_mapping(
        {
            "tts": {"default_voice": "manifest-voice"},
            "backend": {"mode": "real"},
        }
    )
    app = create_app(config=config, repo_root=tmp_path)

    assert app.state.container.backend_ready is False
    assert "missing backend asset" in (app.state.container.startup_error or "")
