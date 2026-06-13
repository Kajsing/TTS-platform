from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_extension.py"
EXTENSION_ROOT = REPO_ROOT / "apps" / "chrome_extension"


def test_check_extension_accepts_repo_manifest_and_privacy_boundaries() -> None:
    check_module = _load_check_extension_module()
    manifest = json.loads((EXTENSION_ROOT / "manifest.json").read_text(encoding="utf-8"))

    check_module.verify_manifest_policy(manifest)
    check_module.verify_extension_privacy_boundaries(EXTENSION_ROOT)


def test_check_extension_rejects_broad_host_permissions() -> None:
    check_module = _load_check_extension_module()
    manifest = json.loads((EXTENSION_ROOT / "manifest.json").read_text(encoding="utf-8"))
    manifest["host_permissions"] = [
        *manifest["host_permissions"],
        "<all_urls>",
    ]

    with pytest.raises(SystemExit, match="host_permissions"):
        check_module.verify_manifest_policy(manifest)


def test_check_extension_rejects_content_script_network_access(tmp_path: Path) -> None:
    check_module = _load_check_extension_module()
    extension_root = tmp_path / "chrome_extension"
    shutil.copytree(EXTENSION_ROOT, extension_root)
    content_script_path = extension_root / "src" / "content-script.js"
    content_script_path.write_text(
        content_script_path.read_text(encoding="utf-8") + "\nfetch('https://example.test');\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="content script must not contain 'fetch\\('"):
        check_module.verify_extension_privacy_boundaries(extension_root)


def _load_check_extension_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_extension",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
