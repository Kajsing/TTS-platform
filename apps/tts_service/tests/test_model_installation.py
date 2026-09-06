from __future__ import annotations

import hashlib
import json
import threading
import zipfile
from pathlib import Path

import pytest
from tts_service import cli
from tts_service import model_installation as installation
from tts_service.model_installation import (
    ModelInstallCancelled,
    ModelInstallControl,
    manifest_lock,
)


def fixture(root: Path, *, variants: bool = False) -> tuple[Path, Path, Path]:
    artifact = root / "voice.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("model.onnx", "synthetic model" * 100_000)
        archive.writestr("tokens.txt", "synthetic tokens")
    model: dict[str, object] = {
        "id": "new-voice",
        "name": "Synthetic voice",
        "engine": "sherpa_onnx",
        "language": "en-US",
        "license": "synthetic fixture only",
        "artifact_url": str(artifact),
        "artifact_size_bytes": artifact.stat().st_size,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "backend": {"model_type": "vits", "model": "model.onnx", "tokens": "tokens.txt"},
    }
    if variants:
        model["voices"] = [
            {"id": "new-voice", "name": "First speaker", "speaker_id": 0},
            {"id": "second-voice", "name": "Second speaker", "speaker_id": 1},
        ]
    catalog = root / "catalog.json"
    catalog.write_text(json.dumps({"version": 1, "models": [model]}), encoding="utf-8")
    manifest = root / "models" / "MANIFEST.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "custom_field": "keep me",
                "voices": [{"id": "existing", "custom": 42}],
            }
        ),
        encoding="utf-8",
    )
    return catalog, manifest, root / "models" / "voices"


def install(
    paths: tuple[Path, Path, Path],
    control: ModelInstallControl | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    catalog, manifest, models = paths
    return cli._install_model_from_catalog(
        catalog_source=str(catalog),
        model_id="new-voice",
        models_root=models,
        manifest_path=manifest,
        overwrite=overwrite,
        control=control or ModelInstallControl(require_assets=True),
    )


@pytest.mark.parametrize(
    "phase", ["resolving", "downloading", "verifying", "extracting", "committing"]
)
def test_cancellation_before_commit_preserves_manifest_and_cleans_staging(
    tmp_path: Path, phase: str
) -> None:
    paths = fixture(tmp_path)
    original = paths[1].read_bytes()
    cancelled = threading.Event()
    control = ModelInstallControl(
        cancelled=cancelled.is_set,
        progress=lambda event: cancelled.set() if event["phase"] == phase else None,
    )
    with pytest.raises(ModelInstallCancelled):
        install(paths, control)
    assert paths[1].read_bytes() == original
    assert not (paths[2] / "new-voice").exists()
    assert not paths[2].exists() or list(paths[2].iterdir()) == []


def test_byte_progress_and_late_cancellation_report_the_committed_result(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    events: list[dict[str, object]] = []
    cancelled = threading.Event()

    def report(event: dict[str, object]) -> None:
        events.append(event)
        if event["phase"] == "completed":
            cancelled.set()

    result = install(
        paths, ModelInstallControl(cancelled=cancelled.is_set, progress=report, require_assets=True)
    )
    assert result["installed_model"] == "new-voice"
    assert result["checksum_verified"] is True
    assert any(
        event["phase"] == "downloading" and event["completed"] == event["total"] for event in events
    )
    assert events[-1] == {
        "phase": "completed",
        "completed": None,
        "total": None,
        "cancellable": False,
    }
    manifest = json.loads(paths[1].read_text(encoding="utf-8"))
    assert manifest["custom_field"] == "keep me"
    assert manifest["voices"][0] == {"id": "existing", "custom": 42}


@pytest.mark.parametrize("overwrite", [False, True])
def test_failed_manifest_write_rolls_back_files_without_touching_working_voice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overwrite: bool,
) -> None:
    paths = fixture(tmp_path)
    original = paths[1].read_bytes()
    if overwrite:
        (paths[2] / "new-voice").mkdir(parents=True)
        (paths[2] / "new-voice" / "old.onnx").write_text("working old voice", encoding="utf-8")

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("Simulated disk-full during manifest replacement")

    monkeypatch.setattr(cli, "atomic_write", fail)
    with pytest.raises(OSError, match="disk-full"):
        install(paths, overwrite=overwrite)
    assert paths[1].read_bytes() == original
    assert list(paths[2].iterdir()) == ([paths[2] / "new-voice"] if overwrite else [])
    if overwrite:
        assert (paths[2] / "new-voice" / "old.onnx").read_text(
            encoding="utf-8"
        ) == "working old voice"


def test_concurrent_manifest_edit_is_not_overwritten(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    changed = b'{"version": 1, "voices": [{"id": "user-added"}]}'

    def edit(event: dict[str, object]) -> None:
        if event["phase"] == "committing":
            paths[1].write_bytes(changed)

    with pytest.raises(RuntimeError, match="manifest changed"):
        install(paths, ModelInstallControl(progress=edit))
    assert paths[1].read_bytes() == changed
    assert list(paths[2].iterdir()) == []


def test_existing_manifest_voice_is_not_replaced_even_if_its_directory_is_missing(
    tmp_path: Path,
) -> None:
    paths = fixture(tmp_path)
    original = b'{"version":1,"voices":[{"id":"new-voice","custom":"user data"}]}'
    paths[1].write_bytes(original)
    with pytest.raises(SystemExit, match="already exists in the manifest"):
        install(paths)
    assert paths[1].read_bytes() == original
    assert not paths[2].exists()


def test_missing_required_assets_and_invalid_manifest_never_publish_a_package(
    tmp_path: Path,
) -> None:
    paths = fixture(tmp_path)
    original = paths[1].read_bytes()
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["models"][0]["backend"]["model"] = "missing.onnx"
    paths[0].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="missing required voice assets"):
        install(paths)
    assert paths[1].read_bytes() == original
    assert list(paths[2].iterdir()) == []
    payload["models"][0]["backend"]["model"] = "model.onnx"
    paths[0].write_text(json.dumps(payload), encoding="utf-8")
    invalid = b'{"version":1,"voices":[{"id":"existing"}, "unrecognized-user-data"]}'
    paths[1].write_bytes(invalid)
    with pytest.raises(SystemExit, match="invalid voice entry"):
        install(paths)
    assert paths[1].read_bytes() == invalid
    assert list(paths[2].iterdir()) == []


def test_multi_voice_package_uses_one_asset_directory_and_one_manifest_commit(
    tmp_path: Path,
) -> None:
    paths = fixture(tmp_path, variants=True)
    result = install(paths)
    assert result["installed_voice_ids"] == ["new-voice", "second-voice"]
    voices = json.loads(paths[1].read_text(encoding="utf-8"))["voices"][1:]
    assert voices[0]["source"] == voices[1]["source"] == "models/voices/new-voice"
    assert voices[0]["backend"]["model"] == voices[1]["backend"]["model"]
    assert [voice["backend"]["speaker_id"] for voice in voices] == [0, 1]
    assert list(paths[2].iterdir()) == [paths[2] / "new-voice"]


def test_manifest_lock_is_nonblocking_and_released(tmp_path: Path) -> None:
    path = tmp_path / "MANIFEST.json"
    with manifest_lock(path):
        with pytest.raises(RuntimeError, match="Another model operation"):
            with manifest_lock(path):
                pytest.fail("Second writer acquired the lock")
    with manifest_lock(path):
        pass


def test_expired_installation_never_starts_download(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    with pytest.raises(ModelInstallCancelled, match="time limit"):
        install(paths, ModelInstallControl(timeout_seconds=-1))
    assert not paths[2].exists()


def test_shared_assets_cannot_be_removed_while_another_voice_uses_them(tmp_path: Path) -> None:
    paths = fixture(tmp_path, variants=True)
    install(paths)
    original = paths[1].read_bytes()
    with pytest.raises(SystemExit, match="Other voices share this package"):
        cli._remove_model(model_id="new-voice", models_root=paths[2], manifest_path=paths[1])
    assert paths[1].read_bytes() == original
    assert (paths[2] / "new-voice" / "model.onnx").is_file()
    removed = cli._remove_model(
        model_id="second-voice", models_root=paths[2], manifest_path=paths[1]
    )
    assert removed["removed_manifest_entry"] is True
    assert removed["removed_files"] is False
    assert (paths[2] / "new-voice" / "model.onnx").is_file()


@pytest.mark.parametrize("invalid_asset", ["directory", "empty"])
def test_archive_asset_types_are_checked_before_commit(tmp_path: Path, invalid_asset: str) -> None:
    paths = fixture(tmp_path)
    artifact = tmp_path / "voice.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("model.onnx/" if invalid_asset == "directory" else "model.onnx", "")
        archive.writestr("tokens.txt", "tokens")
    catalog = json.loads(paths[0].read_bytes())
    catalog["models"][0]["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    catalog["models"][0]["artifact_size_bytes"] = artifact.stat().st_size
    paths[0].write_text(json.dumps(catalog), encoding="utf-8")
    original = paths[1].read_bytes()
    with pytest.raises(RuntimeError, match="empty asset or incorrect asset type"):
        install(paths)
    assert paths[1].read_bytes() == original
    assert list(paths[2].iterdir()) == []


def test_overwrite_cannot_change_assets_beneath_an_unlisted_shared_voice(tmp_path: Path) -> None:
    paths = fixture(tmp_path, variants=True)
    install(paths)
    original = paths[1].read_bytes()
    catalog = json.loads(paths[0].read_bytes())
    del catalog["models"][0]["voices"]
    paths[0].write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(SystemExit, match="Other voices share this package"):
        install(paths, overwrite=True)
    assert paths[1].read_bytes() == original
    assert (paths[2] / "new-voice" / "model.onnx").is_file()


def test_atomic_manifest_replace_failure_preserves_original_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "MANIFEST.json"
    path.write_bytes(b"original")

    def fail(*args: object) -> None:
        raise PermissionError("Synthetic replacement failure")

    monkeypatch.setattr(installation.os, "replace", fail)
    with pytest.raises(PermissionError):
        installation.atomic_write(path, b"replacement")
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]
