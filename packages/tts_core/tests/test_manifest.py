from __future__ import annotations

from pathlib import Path

import pytest
from tts_core.manifest import VoiceManifestError, load_voice_manifest, load_voice_manifest_bundle


def test_load_voice_manifest_reads_voice_descriptors(tmp_path: Path) -> None:
    manifest_path = tmp_path / "MANIFEST.json"
    manifest_path.write_text(
        """
        {
          "version": 1,
          "voices": [
            {
              "id": "voice-a",
              "name": "Voice A",
              "engine": "sherpa_onnx",
              "language": "en",
              "sample_rate_hz": 24000,
              "license": "Apache-2.0",
              "source": "models/voice-a",
              "tags": ["general"],
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

    voices = load_voice_manifest(manifest_path)

    assert len(voices) == 1
    assert voices[0].id == "voice-a"
    assert voices[0].capabilities.supports_streaming is True


def test_load_voice_manifest_rejects_unknown_version(tmp_path: Path) -> None:
    manifest_path = tmp_path / "MANIFEST.json"
    manifest_path.write_text('{"version": 2, "voices": []}', encoding="utf-8")

    with pytest.raises(VoiceManifestError):
        load_voice_manifest(manifest_path)


def test_load_voice_manifest_bundle_keeps_backend_config_out_of_voice_descriptor(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "MANIFEST.json"
    manifest_path.write_text(
        """
        {
          "version": 1,
          "voices": [
            {
              "id": "voice-a",
              "name": "Voice A",
              "engine": "sherpa_onnx",
              "language": "en",
              "sample_rate_hz": 24000,
              "license": "Apache-2.0",
              "source": "models/voice-a",
              "backend": {
                "model_type": "vits",
                "model": "models/voices/voice-a/model.onnx",
                "tokens": "models/voices/voice-a/tokens.txt"
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    bundle = load_voice_manifest_bundle(manifest_path)

    assert bundle.voices[0].id == "voice-a"
    assert not hasattr(bundle.voices[0], "backend")
    assert bundle.backend_configs["voice-a"]["model_type"] == "vits"
