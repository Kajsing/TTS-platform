from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from test_model_manager import library, transport
from tts_service import cli, model_manager
from tts_service.model_installation import ModelInstallControl

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = ("kokoro-v1_0-us-20", "kokoro-v1_0-us-20-int8")


def catalog() -> dict:
    return json.loads((ROOT / "models/catalog.json").read_text(encoding="utf-8"))


def test_reviewed_catalog_pins_supported_US_speakers_and_separate_packages():
    models = catalog()["models"]
    assert len(models) == 3
    expected = {
        PACKAGES[0]: (
            349418188,
            "c133d26353d776da730870dac7da07dbfc9a5e3bc80cc5e8e83ab6e823be7046",
        ),
        PACKAGES[1]: (
            131839838,
            "75654a84864be26f345f020f4070c2c019e96dd1b7f9bf6e2ffd59efac6aa5a3",
        ),
    }
    voice_ids = set()
    for model in models[1:]:
        assert (model["artifact_size_bytes"], model["artifact_sha256"]) == expected[model["id"]]
        assert "Apache-2.0 model/voices" in model["license"]
        assert "GPL-3.0" in model["license"]
        assert model["license_url"].endswith("docs/voice_licenses/kokoro-v1.md")
        assert "full-bundle download" in model["install_note"]
        assert model["backend"]["lexicon"].endswith("/lexicon-us-en.txt")
        voices = cli._build_manifest_voice_entries(model_id=model["id"], model=model)
        assert len(voices) == 20
        assert [v["backend"]["speaker_id"] for v in voices] == list(range(20))
        assert voices[3]["id"] == model["id"]
        assert "af_heart" in voices[3]["name"]
        assert {v["language"] for v in voices} == {"en-US"}
        assert not voice_ids.intersection(v["id"] for v in voices)
        voice_ids.update(v["id"] for v in voices)
        assert "kokoro-en-v1_0-af-heart" not in voice_ids
        assert "kokoro-int8-en-v1_0-af-heart" not in voice_ids


@pytest.mark.parametrize("package_id", PACKAGES)
def test_actual_catalog_layout_installs_all_20_voices_atomically_with_synthetic_assets(
    tmp_path: Path, monkeypatch, package_id: str
):
    target, manifest, _ = library(tmp_path)
    model = next(m for m in catalog()["models"] if m["id"] == package_id)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:bz2") as archive:
        for key in ("model", "voices", "tokens", "lexicon", "data_dir"):
            name = model["backend"][key] + ("/en" if key == "data_dir" else "")
            content = b"synthetic structural fixture; not a native voice"
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
    content = buffer.getvalue()
    # Only this isolated fixture gets synthetic artifact metadata; repo stays pinned.
    model["artifact_size_bytes"] = len(content)
    model["artifact_sha256"] = hashlib.sha256(content).hexdigest()
    target.write_text(json.dumps({"version": 1, "models": [model]}), encoding="utf-8")
    before_config = (tmp_path / "config/config.toml").read_bytes()
    requests = transport(monkeypatch, content)
    reviewed = model_manager.inventory(tmp_path)
    package = reviewed["packages"][0]
    assert package["can_install"] and "full-bundle" in package["install_note"]
    result = model_manager.install_package(
        tmp_path, package_id, reviewed["catalog_fingerprint"], True, ModelInstallControl()
    )
    assert result["checksum_verified"] and result["activation"] == "restart_required"
    assert len(result["voice_ids"]) == 20
    assert requests == [model["artifact_url"]]
    stored = json.loads(manifest.read_text(encoding="utf-8"))
    assert stored["custom"] == "keep"
    after = model_manager.inventory(tmp_path)
    assert len(after["installed_voices"]) == 20
    assert all(v["assets_present"] for v in after["installed_voices"])
    assert not after["packages"][0]["can_install"]
    assert (tmp_path / "config/config.toml").read_bytes() == before_config
    assert not list((tmp_path / "models/voices").glob(".*.staging*"))
