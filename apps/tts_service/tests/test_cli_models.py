from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from tts_service import cli


def _build_zip(path: Path, *, files: dict[str, str]) -> bytes:
    with zipfile.ZipFile(path, "w") as archive:
        for relative_path, content in files.items():
            archive.writestr(relative_path, content)
    return path.read_bytes()


def test_model_install_from_local_catalog_updates_manifest(tmp_path: Path) -> None:
    artifact_path = tmp_path / "voice-a.zip"
    artifact_bytes = _build_zip(
        artifact_path,
        files={
            "model.onnx": "fake-model",
            "tokens.txt": "fake-tokens",
        },
    )
    checksum = hashlib.sha256(artifact_bytes).hexdigest()

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "voice-a",
                        "name": "Voice A",
                        "language": "en",
                        "artifact_url": str(artifact_path),
                        "artifact_sha256": checksum,
                        "backend": {
                            "model_type": "vits",
                            "model": "model.onnx",
                            "tokens": "tokens.txt",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = cli._install_model_from_catalog(
        catalog_source=str(catalog_path),
        model_id="voice-a",
        models_root=tmp_path / "models" / "voices",
        manifest_path=tmp_path / "models" / "MANIFEST.json",
        overwrite=False,
    )

    assert result["installed_model"] == "voice-a"
    voice_dir = tmp_path / "models" / "voices" / "voice-a"
    assert (voice_dir / "model.onnx").exists()
    assert (voice_dir / "tokens.txt").exists()

    manifest_payload = json.loads(
        (tmp_path / "models" / "MANIFEST.json").read_text(encoding="utf-8")
    )
    voices = manifest_payload["voices"]
    assert len(voices) == 1
    assert voices[0]["id"] == "voice-a"
    assert voices[0]["backend"]["model"] == "models/voices/voice-a/model.onnx"
    assert voices[0]["backend"]["tokens"] == "models/voices/voice-a/tokens.txt"


def test_model_install_requires_overwrite_for_existing_directory(tmp_path: Path) -> None:
    existing_dir = tmp_path / "models" / "voices" / "voice-a"
    existing_dir.mkdir(parents=True)

    artifact_path = tmp_path / "voice-a.zip"
    artifact_bytes = _build_zip(artifact_path, files={"model.onnx": "fake"})
    checksum = hashlib.sha256(artifact_bytes).hexdigest()

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "voice-a",
                        "artifact_url": str(artifact_path),
                        "artifact_sha256": checksum,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="already exists"):
        cli._install_model_from_catalog(
            catalog_source=str(catalog_path),
            model_id="voice-a",
            models_root=tmp_path / "models" / "voices",
            manifest_path=tmp_path / "models" / "MANIFEST.json",
            overwrite=False,
        )


def test_catalog_list_command_prints_models(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {"id": "voice-a", "name": "Voice A"},
                    {"id": "voice-b", "name": "Voice B"},
                ],
            }
        ),
        encoding="utf-8",
    )

    cli.main(["catalog-list", "--catalog", str(catalog_path)])

    payload = json.loads(capsys.readouterr().out)
    assert [model["id"] for model in payload["models"]] == ["voice-a", "voice-b"]
