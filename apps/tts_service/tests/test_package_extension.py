from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_SCRIPT_PATH = REPO_ROOT / "scripts" / "package_extension.py"


def test_package_extension_builds_chrome_loadable_zip(tmp_path: Path, monkeypatch) -> None:
    package_module = _load_package_module()
    check_calls: list[bool] = []
    monkeypatch.setattr(package_module.check_extension, "main", lambda: check_calls.append(True))

    out_path = tmp_path / "extension.zip"
    payload = package_module.package_extension(out_path=out_path)

    assert check_calls == [True]
    assert payload["package_path"] == str(out_path.resolve())
    assert payload["manifest_path"] == "manifest.json"
    assert payload["install_guide_path"] == "INSTALL.md"
    assert payload["icon_count"] == 4
    assert payload["file_count"] > 0

    with zipfile.ZipFile(out_path) as archive:
        names = set(archive.namelist())
        install_guide = archive.read("INSTALL.md").decode()

    assert "manifest.json" in names
    assert "INSTALL.md" in names
    assert "icons/icon-16.png" in names
    assert "icons/icon-32.png" in names
    assert "icons/icon-48.png" in names
    assert "icons/icon-128.png" in names
    assert "src/popup.html" in names
    assert "src/popup.js" in names
    assert "offscreen/offscreen.html" in names
    assert "offscreen/offscreen.js" in names
    assert "scripts\\windows\\install_local.ps1" in install_guide
    assert "scripts\\windows\\run_service.ps1" in install_guide
    assert "tts setup-local" in install_guide
    assert "tts extension-allow-origin <copied-origin>" in install_guide
    assert "security.allowed_origins" in install_guide
    assert "config\\token.txt" in install_guide
    assert all(not name.startswith("/") for name in names)
    assert all("\\" not in name for name in names)


def _load_package_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_package_extension",
        PACKAGE_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
