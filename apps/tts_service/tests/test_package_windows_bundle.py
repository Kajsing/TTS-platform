from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_SCRIPT_PATH = REPO_ROOT / "scripts" / "package_windows_bundle.py"


def test_package_windows_bundle_builds_source_and_extension_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_module = _load_package_module()
    extension_calls: list[Path] = []

    def fake_package_extension(*, out_path: Path) -> dict[str, object]:
        extension_calls.append(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, mode="w") as archive:
            archive.writestr("manifest.json", "{}")
        return {
            "package_path": str(out_path),
            "file_count": 1,
            "manifest_path": "manifest.json",
        }

    monkeypatch.setattr(
        package_module.extension_packager,
        "package_extension",
        fake_package_extension,
    )

    out_path = tmp_path / "tts-platform-local-reader.zip"
    payload = package_module.package_windows_bundle(out_path=out_path)

    assert len(extension_calls) == 1
    assert payload["package_path"] == str(out_path.resolve())
    assert payload["bundle_root"] == "tts-platform"
    assert payload["extension_package"] == {
        "archive_path": "dist/chrome_extension/tts-platform-prototype.zip",
        "file_count": 1,
        "manifest_path": "manifest.json",
    }

    with zipfile.ZipFile(out_path) as archive:
        names = set(archive.namelist())
        readme = archive.read("tts-platform/WINDOWS_BUNDLE_README.md").decode()

    assert "tts-platform/pyproject.toml" in names
    assert "tts-platform/config/config.example.toml" in names
    assert "tts-platform/docs/v1_readiness.md" in names
    assert "tts-platform/models/MANIFEST.json" in names
    assert "tts-platform/apps/tts_service/src/tts_service/main.py" in names
    assert "tts-platform/packages/tts_core/src/tts_core/text.py" in names
    assert "tts-platform/apps/chrome_extension/manifest.json" in names
    assert "tts-platform/scripts/windows/run_service.ps1" in names
    assert "tts-platform/scripts/windows/run_service.cmd" in names
    assert "tts-platform/scripts/check_extension_onboarding.py" in names
    assert "tts-platform/scripts/check_extension_reader_flow.py" in names
    assert "tts-platform/scripts/check_security_defaults.py" in names
    assert "tts-platform/scripts/check_local_service_bootstrap.py" in names
    assert "tts-platform/scripts/check_model_management_flow.py" in names
    assert "tts-platform/scripts/check_v1_readiness.py" in names
    assert "tts-platform/scripts/check_windows_bundle_bootstrap.py" in names
    assert "tts-platform/scripts/check_windows_bundle_install.py" in names
    assert "tts-platform/scripts/package_windows_bundle.py" in names
    assert "tts-platform/scripts/release_check.py" in names
    assert "tts-platform/dist/chrome_extension/tts-platform-prototype.zip" in names
    assert "persistent Windows service" in readme
    assert "manager" in readme

    assert all(name.startswith("tts-platform/") for name in names)
    assert all("\\" not in name for name in names)
    assert all(not name.startswith("/") for name in names)
    assert "tts-platform/config/token.txt" not in names
    assert not any(name.startswith("tts-platform/models/voices/") for name in names)


def _load_package_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_package_windows_bundle",
        PACKAGE_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
