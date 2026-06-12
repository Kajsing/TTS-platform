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


def test_model_install_preserves_existing_directory_when_overwrite_artifact_fails(
    tmp_path: Path,
) -> None:
    existing_dir = tmp_path / "models" / "voices" / "voice-a"
    existing_dir.mkdir(parents=True)
    existing_file = existing_dir / "model.onnx"
    existing_file.write_text("existing", encoding="utf-8")

    artifact_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(artifact_path, "w") as archive:
        archive.writestr("../escape.txt", "nope")
    checksum = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

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

    with pytest.raises(SystemExit, match="unsafe path traversal"):
        cli._install_model_from_catalog(
            catalog_source=str(catalog_path),
            model_id="voice-a",
            models_root=tmp_path / "models" / "voices",
            manifest_path=tmp_path / "models" / "MANIFEST.json",
            overwrite=True,
        )

    assert existing_file.read_text(encoding="utf-8") == "existing"


def test_model_install_rejects_checksum_mismatch(tmp_path: Path) -> None:
    artifact_path = tmp_path / "voice-a.zip"
    _build_zip(artifact_path, files={"model.onnx": "fake"})

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "voice-a",
                        "artifact_url": str(artifact_path),
                        "artifact_sha256": "0" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="Checksum mismatch"):
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


def test_model_install_rejects_zip_traversal_paths(tmp_path: Path) -> None:
    artifact_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(artifact_path, "w") as archive:
        archive.writestr("../escape.txt", "nope")

    checksum = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "unsafe-voice",
                        "artifact_url": str(artifact_path),
                        "artifact_sha256": checksum,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="unsafe path traversal"):
        cli._install_model_from_catalog(
            catalog_source=str(catalog_path),
            model_id="unsafe-voice",
            models_root=tmp_path / "models" / "voices",
            manifest_path=tmp_path / "models" / "MANIFEST.json",
            overwrite=False,
        )
    assert not (tmp_path / "models" / "voices" / "unsafe-voice").exists()


def test_model_install_rejects_zip_backslash_traversal_paths(tmp_path: Path) -> None:
    artifact_path = tmp_path / "unsafe-backslash.zip"
    with zipfile.ZipFile(artifact_path, "w") as archive:
        archive.writestr("..\\escape.txt", "nope")

    checksum = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "unsafe-backslash-voice",
                        "artifact_url": str(artifact_path),
                        "artifact_sha256": checksum,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="unsafe path traversal"):
        cli._install_model_from_catalog(
            catalog_source=str(catalog_path),
            model_id="unsafe-backslash-voice",
            models_root=tmp_path / "models" / "voices",
            manifest_path=tmp_path / "models" / "MANIFEST.json",
            overwrite=False,
        )


def test_model_install_rejects_zip_drive_paths(tmp_path: Path) -> None:
    artifact_path = tmp_path / "unsafe-drive.zip"
    with zipfile.ZipFile(artifact_path, "w") as archive:
        archive.writestr("C:/escape.txt", "nope")

    checksum = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "unsafe-drive-voice",
                        "artifact_url": str(artifact_path),
                        "artifact_sha256": checksum,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="absolute path entry"):
        cli._install_model_from_catalog(
            catalog_source=str(catalog_path),
            model_id="unsafe-drive-voice",
            models_root=tmp_path / "models" / "voices",
            manifest_path=tmp_path / "models" / "MANIFEST.json",
            overwrite=False,
        )


def test_model_remove_deletes_files_and_manifest_entry(tmp_path: Path) -> None:
    voice_dir = tmp_path / "models" / "voices" / "voice-a"
    voice_dir.mkdir(parents=True)
    (voice_dir / "model.onnx").write_text("fake", encoding="utf-8")

    manifest_path = tmp_path / "models" / "MANIFEST.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "voices": [
                    {"id": "voice-a", "name": "Voice A"},
                    {"id": "voice-b", "name": "Voice B"},
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = cli._remove_model(
        model_id="voice-a",
        models_root=tmp_path / "models" / "voices",
        manifest_path=manifest_path,
    )

    assert payload["removed_files"] is True
    assert payload["removed_manifest_entry"] is True
    assert not voice_dir.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [voice["id"] for voice in manifest["voices"]] == ["voice-b"]


def test_model_remove_is_noop_when_model_is_missing(tmp_path: Path) -> None:
    manifest_path = tmp_path / "models" / "MANIFEST.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"version": 1, "voices": []}), encoding="utf-8")

    payload = cli._remove_model(
        model_id="missing-voice",
        models_root=tmp_path / "models" / "voices",
        manifest_path=manifest_path,
    )

    assert payload["removed_files"] is False
    assert payload["removed_manifest_entry"] is False
