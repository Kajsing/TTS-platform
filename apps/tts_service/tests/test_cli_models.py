from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from tts_service import cli
from tts_service.config import load_config


def _build_zip(path: Path, *, files: dict[str, str]) -> bytes:
    with zipfile.ZipFile(path, "w") as archive:
        for relative_path, content in files.items():
            archive.writestr(relative_path, content)
    return path.read_bytes()


def _write_manifest(path: Path, *, voice_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "voices": [{"id": voice_id, "name": voice_id} for voice_id in voice_ids],
            }
        ),
        encoding="utf-8",
    )


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
    assert result["checksum_verified"] is True
    assert result["files_installed"] == 2
    assert [step["step"] for step in result["install_steps"]] == [
        "resolve_catalog_model",
        "load_artifact",
        "verify_checksum",
        "extract_artifact",
        "update_manifest",
    ]
    assert result["next_steps"][0] == "tts model-activate voice-a"


def test_model_install_command_can_activate_model(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    config_path = tmp_path / "config" / "config.toml"
    manifest_path = tmp_path / "models" / "MANIFEST.json"

    cli.main(
        [
            "model-install",
            "voice-a",
            "--catalog",
            str(catalog_path),
            "--models-root",
            str(tmp_path / "models" / "voices"),
            "--manifest-path",
            str(manifest_path),
            "--config-path",
            str(config_path),
            "--activate",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["installed_model"] == "voice-a"
    assert payload["activated_model"] == "voice-a"
    assert payload["checksum_verified"] is True
    assert payload["files_installed"] == 2
    assert payload["install_steps"][-1]["step"] == "activate_model"
    assert payload["next_steps"] == [
        "restart the local service if it is already running",
        "tts list-voices",
    ]
    assert load_config(config_path, env={}).tts.default_voice == "voice-a"
    assert "[model-install] resolve catalog model: completed" in captured.err
    assert "[model-install] activate model: completed" in captured.err


def test_model_install_requires_checksum_by_default(tmp_path: Path) -> None:
    artifact_path = tmp_path / "voice-a.zip"
    _build_zip(artifact_path, files={"model.onnx": "fake-model"})
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "voice-a",
                        "artifact_url": str(artifact_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="missing artifact_sha256"):
        cli._install_model_from_catalog(
            catalog_source=str(catalog_path),
            model_id="voice-a",
            models_root=tmp_path / "models" / "voices",
            manifest_path=tmp_path / "models" / "MANIFEST.json",
            overwrite=False,
        )
    assert not (tmp_path / "models" / "voices" / "voice-a").exists()


def test_model_install_can_allow_missing_checksum_for_trusted_local_artifact(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "voice-a.zip"
    _build_zip(artifact_path, files={"model.onnx": "fake-model"})
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "voice-a",
                        "artifact_url": str(artifact_path),
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
        allow_missing_checksum=True,
    )

    assert result["checksum_verified"] is False
    assert result["warning"] == (
        "Catalog entry has no artifact_sha256; install was allowed only because "
        "--allow-missing-checksum was set."
    )
    assert result["install_steps"][2] == {
        "step": "verify_checksum",
        "status": "skipped",
        "reason": "allowed missing artifact_sha256 for trusted local artifact",
    }


def test_model_install_command_allows_missing_checksum_with_explicit_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_path = tmp_path / "voice-a.zip"
    _build_zip(artifact_path, files={"model.onnx": "fake-model"})
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "voice-a",
                        "artifact_url": str(artifact_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cli.main(
        [
            "model-install",
            "voice-a",
            "--catalog",
            str(catalog_path),
            "--models-root",
            str(tmp_path / "models" / "voices"),
            "--manifest-path",
            str(tmp_path / "models" / "MANIFEST.json"),
            "--allow-missing-checksum",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["checksum_verified"] is False
    assert payload["warning"].endswith("--allow-missing-checksum was set.")


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
                    {
                        "id": "voice-a",
                        "name": "Voice A",
                        "artifact_url": "voice-a.zip",
                        "artifact_sha256": "a" * 64,
                    },
                    {
                        "id": "voice-b",
                        "name": "Voice B",
                        "artifact_url": "voice-b.zip",
                        "artifact_sha256": "b" * 64,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    cli.main(["catalog-list", "--catalog", str(catalog_path)])

    payload = json.loads(capsys.readouterr().out)
    assert payload["catalog"] == {
        "source": str(catalog_path),
        "version": 1,
        "model_count": 2,
        "installable_count": 2,
        "checksum_count": 2,
    }
    assert [model["id"] for model in payload["models"]] == ["voice-a", "voice-b"]
    assert [summary["id"] for summary in payload["model_summaries"]] == [
        "voice-a",
        "voice-b",
    ]
    assert payload["model_summaries"][0]["checksum"] == "sha256"
    assert payload["warnings"] == []
    assert payload["next_steps"] == [
        "review model_summaries for installable models and checksum coverage",
        "tts model-install <model-id> --catalog <catalog> --activate",
    ]


def test_catalog_list_reports_install_readiness_warnings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "voice-a",
                        "name": "Voice A",
                        "artifact_url": "voice-a.zip",
                    },
                    {"id": "voice-b", "name": "Voice B"},
                    {
                        "id": "voice-a",
                        "name": "Voice A Duplicate",
                        "artifact_url": "voice-a-duplicate.zip",
                        "artifact_sha256": "a" * 64,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    cli.main(["catalog-list", "--catalog", str(catalog_path)])

    payload = json.loads(capsys.readouterr().out)
    assert payload["catalog"]["model_count"] == 3
    assert payload["catalog"]["installable_count"] == 2
    assert payload["catalog"]["checksum_count"] == 1
    assert payload["model_summaries"][0]["installable"] is True
    assert payload["model_summaries"][0]["checksum"] == "missing"
    assert payload["model_summaries"][1]["installable"] is False
    assert payload["warnings"] == [
        "Model 'voice-a' is missing artifact_sha256; installs cannot verify integrity.",
        "Model 'voice-b' is missing artifact_url and cannot be installed.",
        "Model 'voice-b' is missing artifact_sha256; installs cannot verify integrity.",
        "Duplicate model id 'voice-a' at index 2; install uses the first match.",
    ]


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


def test_model_remove_warns_when_removed_model_is_active_default(tmp_path: Path) -> None:
    voice_dir = tmp_path / "models" / "voices" / "voice-a"
    voice_dir.mkdir(parents=True)
    (voice_dir / "model.onnx").write_text("fake", encoding="utf-8")
    manifest_path = tmp_path / "models" / "MANIFEST.json"
    _write_manifest(manifest_path, voice_ids=["voice-a", "voice-b"])
    config_path = tmp_path / "config" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text('[tts]\ndefault_voice = "voice-a"\n', encoding="utf-8")

    payload = cli._remove_model(
        model_id="voice-a",
        models_root=tmp_path / "models" / "voices",
        manifest_path=manifest_path,
        config_path=config_path,
    )

    assert payload["removed_files"] is True
    assert payload["removed_manifest_entry"] is True
    assert payload["active_default_voice"] is True
    assert payload["config_path"] == str(config_path)
    assert payload["warning"] == (
        "This model id is still configured as [tts].default_voice. "
        "Activate another installed model before restarting the service."
    )
    assert payload["next_steps"] == [
        "tts model-activate <model-id>",
        "restart the local service",
        "tts list-voices",
    ]


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


def test_model_activate_updates_existing_default_voice(tmp_path: Path) -> None:
    manifest_path = tmp_path / "models" / "MANIFEST.json"
    _write_manifest(manifest_path, voice_ids=["voice-a"])
    config_path = tmp_path / "config" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "[server]",
                'host = "127.0.0.1"',
                "",
                "[tts]",
                'default_voice = "old-voice"',
                "max_chars_per_request = 8000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = cli._activate_model(
        model_id="voice-a",
        manifest_path=manifest_path,
        config_path=config_path,
    )

    assert payload["activated_model"] == "voice-a"
    config = load_config(config_path, env={})
    assert config.tts.default_voice == "voice-a"
    assert config.tts.max_chars_per_request == 8000
    assert config.server.host == "127.0.0.1"


def test_model_activate_inserts_tts_section_when_missing(tmp_path: Path) -> None:
    manifest_path = tmp_path / "models" / "MANIFEST.json"
    _write_manifest(manifest_path, voice_ids=["voice-a"])
    config_path = tmp_path / "config" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("[server]\nport = 9001\n", encoding="utf-8")

    cli._activate_model(
        model_id="voice-a",
        manifest_path=manifest_path,
        config_path=config_path,
    )

    config = load_config(config_path, env={})
    assert config.server.port == 9001
    assert config.tts.default_voice == "voice-a"


def test_model_activate_creates_missing_config(tmp_path: Path) -> None:
    manifest_path = tmp_path / "models" / "MANIFEST.json"
    _write_manifest(manifest_path, voice_ids=["voice-a"])
    config_path = tmp_path / "config" / "config.toml"

    cli._activate_model(
        model_id="voice-a",
        manifest_path=manifest_path,
        config_path=config_path,
    )

    assert config_path.read_text(encoding="utf-8") == '[tts]\ndefault_voice = "voice-a"\n'
    assert load_config(config_path, env={}).tts.default_voice == "voice-a"


def test_model_activate_rejects_missing_manifest_voice_without_changing_config(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "models" / "MANIFEST.json"
    _write_manifest(manifest_path, voice_ids=["voice-a"])
    config_path = tmp_path / "config" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text('[tts]\ndefault_voice = "voice-a"\n', encoding="utf-8")

    with pytest.raises(SystemExit, match="was not found in manifest"):
        cli._activate_model(
            model_id="missing-voice",
            manifest_path=manifest_path,
            config_path=config_path,
        )

    assert load_config(config_path, env={}).tts.default_voice == "voice-a"


def test_model_check_reports_default_stub_voice_is_not_real_ready(tmp_path: Path) -> None:
    config_path = _write_model_check_config(tmp_path, default_voice="sherpa-en-debug")
    manifest_path = tmp_path / "models" / "MANIFEST.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "voices": [
                    {
                        "id": "sherpa-en-debug",
                        "name": "Sherpa English Debug",
                        "engine": "sherpa_onnx",
                        "language": "en",
                        "sample_rate_hz": 24000,
                        "license": "development-only",
                        "source": "models/voices/sherpa-en-debug",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = cli._check_model_readiness(
        model_id=None,
        repo_root=tmp_path,
        manifest_path=manifest_path,
        config_path=config_path,
    )

    assert payload["ready"] is False
    assert payload["model_id"] == "sherpa-en-debug"
    assert payload["selected_source"] == "config_default"
    assert payload["manifest"]["voice"]["has_backend_config"] is False
    assert payload["backend"]["configured"] is False
    assert payload["next_steps"][0] == (
        "tts model-install sherpa-en-debug --catalog <catalog> --activate --overwrite"
    )


def test_model_check_reports_real_voice_ready_when_assets_and_runtime_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_model_check_config(tmp_path, default_voice="voice-a")
    manifest_path = _write_model_check_manifest(tmp_path)
    _write_real_voice_assets(tmp_path)
    monkeypatch.setattr(
        cli.importlib.util,
        "find_spec",
        lambda name: object() if name == "sherpa_onnx" else None,
    )

    payload = cli._check_model_readiness(
        model_id="voice-a",
        repo_root=tmp_path,
        manifest_path=manifest_path,
        config_path=config_path,
    )

    assert payload["ready"] is True
    assert payload["selected_source"] == "argument"
    assert payload["backend"]["configured"] is True
    assert payload["backend"]["assets_ready"] is True
    assert payload["backend"]["missing_assets"] == []
    assert payload["runtime"]["sherpa_onnx_installed"] is True
    assert payload["next_steps"] == [
        "restart the local service if it is already running",
        "python3 scripts/smoke_service.py --token-file config/token.txt --voice voice-a",
    ]


def test_model_check_reports_missing_real_voice_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_model_check_config(tmp_path, default_voice="voice-a")
    manifest_path = _write_model_check_manifest(tmp_path)
    voice_dir = tmp_path / "models" / "voices" / "voice-a"
    voice_dir.mkdir(parents=True)
    (voice_dir / "model.onnx").write_text("fake", encoding="utf-8")
    monkeypatch.setattr(
        cli.importlib.util,
        "find_spec",
        lambda name: object() if name == "sherpa_onnx" else None,
    )

    payload = cli._check_model_readiness(
        model_id="voice-a",
        repo_root=tmp_path,
        manifest_path=manifest_path,
        config_path=config_path,
    )

    assert payload["ready"] is False
    assert payload["backend"]["assets_ready"] is False
    assert payload["backend"]["missing_assets"] == [
        str((voice_dir / "tokens.txt").resolve())
    ]
    assert payload["next_steps"][0] == (
        "tts model-install voice-a --catalog <catalog> --activate --overwrite"
    )


def _write_model_check_config(tmp_path: Path, *, default_voice: str) -> Path:
    config_path = tmp_path / "config" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                "[server]",
                'host = "127.0.0.1"',
                "port = 7777",
                "",
                "[auth]",
                "enabled = true",
                'token_file = "./config/token.txt"',
                "",
                "[tts]",
                f'default_voice = "{default_voice}"',
                "max_chars_per_request = 4000",
                "max_chars_per_stream = 48000",
                "",
                "[backend]",
                'mode = "auto"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _write_model_check_manifest(tmp_path: Path) -> Path:
    manifest_path = tmp_path / "models" / "MANIFEST.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "voices": [
                    {
                        "id": "voice-a",
                        "name": "Voice A",
                        "engine": "sherpa_onnx",
                        "language": "en",
                        "sample_rate_hz": 24000,
                        "license": "test-only",
                        "source": "models/voices/voice-a",
                        "backend": {
                            "model_type": "vits",
                            "model": "models/voices/voice-a/model.onnx",
                            "tokens": "models/voices/voice-a/tokens.txt",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _write_real_voice_assets(tmp_path: Path) -> None:
    voice_dir = tmp_path / "models" / "voices" / "voice-a"
    voice_dir.mkdir(parents=True)
    (voice_dir / "model.onnx").write_text("fake-model", encoding="utf-8")
    (voice_dir / "tokens.txt").write_text("a\nb\nc\n", encoding="utf-8")


def test_model_activate_command_prints_activation_payload(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = tmp_path / "models" / "MANIFEST.json"
    _write_manifest(manifest_path, voice_ids=["voice-a"])
    config_path = tmp_path / "config" / "config.toml"

    cli.main(
        [
            "model-activate",
            "voice-a",
            "--manifest-path",
            str(manifest_path),
            "--config-path",
            str(config_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["activated_model"] == "voice-a"
    assert load_config(config_path, env={}).tts.default_voice == "voice-a"
