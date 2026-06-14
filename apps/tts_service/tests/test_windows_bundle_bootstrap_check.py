from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_windows_bundle_bootstrap.py"
PACKAGE_SCRIPT_PATH = REPO_ROOT / "scripts" / "package_windows_bundle.py"


def test_windows_bundle_bootstrap_check_runs_setup_from_extracted_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_module = _load_script_module(
        "tts_platform_check_windows_bundle_bootstrap",
        BOOTSTRAP_SCRIPT_PATH,
    )
    package_module = _load_script_module(
        "tts_platform_package_windows_bundle_for_bootstrap_test",
        PACKAGE_SCRIPT_PATH,
    )

    def fake_package_extension(
        *,
        out_path: Path,
        node_executable: str | None = None,
        require_js_syntax: bool = False,
    ) -> dict[str, object]:
        assert node_executable is None
        assert require_js_syntax is False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, mode="w") as archive:
            archive.writestr("manifest.json", "{}")
            archive.writestr("INSTALL.md", "Load unpacked")
            archive.writestr("TROUBLESHOOTING.md", "Chrome Extension Troubleshooting")
            archive.writestr("icons/icon-16.png", b"icon")
            archive.writestr("icons/icon-32.png", b"icon")
            archive.writestr("icons/icon-48.png", b"icon")
            archive.writestr("icons/icon-128.png", b"icon")
        return {
            "package_path": str(out_path),
            "file_count": 7,
            "manifest_path": "manifest.json",
            "install_guide_path": "INSTALL.md",
            "troubleshooting_path": "TROUBLESHOOTING.md",
            "icon_count": 4,
        }

    monkeypatch.setattr(
        package_module.extension_packager,
        "package_extension",
        fake_package_extension,
    )

    bundle_path = tmp_path / "tts-platform-local-reader.zip"
    package_module.package_windows_bundle(out_path=bundle_path)

    summary = bootstrap_module.check_windows_bundle_bootstrap(
        bundle_path=bundle_path,
        python_executable=sys.executable,
    )

    assert summary["bundle_root"] == "tts-platform"
    assert summary["extension_package"] == {
        "archive_path": "dist/chrome_extension/tts-platform-prototype.zip",
        "file_count": 7,
        "manifest_path": "manifest.json",
        "install_guide_path": "INSTALL.md",
        "troubleshooting_path": "TROUBLESHOOTING.md",
    }
    assert summary["setup"]["config_created"] is True
    assert summary["setup"]["token_created"] is True
    assert summary["setup"]["base_url"] == "http://127.0.0.1:7777"
    assert summary["setup"]["manifest_default_voice"] is True
    assert (
        summary["setup"]["catalog_single_installable_model"]
        == "vits-piper-en_US-lessac-medium"
    )
    assert summary["setup"]["next_steps"][0] == (
        "tts model-install vits-piper-en_US-lessac-medium --activate"
    )
    assert "tts model-check" in summary["setup"]["next_steps"]
    assert "tts serve" in summary["setup"]["next_steps"]


def test_windows_bundle_bootstrap_check_rejects_token_file_in_bundle(
    tmp_path: Path,
) -> None:
    bootstrap_module = _load_script_module(
        "tts_platform_check_windows_bundle_bootstrap_token_test",
        BOOTSTRAP_SCRIPT_PATH,
    )
    bundle_path = tmp_path / "unsafe.zip"
    extension_zip_path = tmp_path / "extension.zip"
    with zipfile.ZipFile(extension_zip_path, mode="w") as extension_archive:
        extension_archive.writestr("manifest.json", "{}")
        extension_archive.writestr("INSTALL.md", "Load unpacked")
        extension_archive.writestr(
            "TROUBLESHOOTING.md",
            "Chrome Extension Troubleshooting",
        )
        extension_archive.writestr("icons/icon-16.png", b"icon")
        extension_archive.writestr("icons/icon-32.png", b"icon")
        extension_archive.writestr("icons/icon-48.png", b"icon")
        extension_archive.writestr("icons/icon-128.png", b"icon")

    required_entries = [
        "tts-platform/pyproject.toml",
        "tts-platform/config/config.example.toml",
        "tts-platform/models/catalog.json",
        "tts-platform/models/MANIFEST.json",
        "tts-platform/docs/v1_readiness.md",
        "tts-platform/scripts/check_local_reader_bundle.py",
        "tts-platform/scripts/check_windows_service_task.py",
        "tts-platform/scripts/windows/run_service.ps1",
        "tts-platform/scripts/windows/run_service.cmd",
        "tts-platform/scripts/windows/run_scheduled_service.ps1",
        "tts-platform/WINDOWS_BUNDLE_README.md",
    ]
    with zipfile.ZipFile(bundle_path, mode="w") as archive:
        for entry in required_entries:
            archive.writestr(entry, _entry_payload(entry))
        archive.write(
            extension_zip_path,
            "tts-platform/dist/chrome_extension/tts-platform-prototype.zip",
        )
        archive.writestr("tts-platform/config/token.txt", "secret-token")

    with pytest.raises(
        bootstrap_module.WindowsBundleBootstrapError,
        match="config/token.txt",
    ):
        bootstrap_module.check_windows_bundle_bootstrap(
            bundle_path=bundle_path,
            python_executable=sys.executable,
        )


def _entry_payload(entry: str) -> str:
    if entry.endswith("WINDOWS_BUNDLE_README.md"):
        return "\n".join(
            [
                "py -3 -m venv .venv",
                'python -m pip install -e ".[dev]"',
                "python -m tts_service.cli setup-local --repo-root .",
                ".\\.venv\\Scripts\\tts.exe model-check",
                ".\\.venv\\Scripts\\tts.exe catalog-list",
                ".\\.venv\\Scripts\\python.exe -m pip install sherpa-onnx",
                ".\\.venv\\Scripts\\python.exe -m pip install -e \".[real]\"",
                "tts.exe model-install vits-piper-en_US-lessac-medium --activate",
                "tts.exe model-install <model-id> --catalog <catalog> --activate",
                ".\\scripts\\windows\\run_service.ps1 -SetupOnly",
                ".\\scripts\\windows\\run_service.ps1",
                "apps\\chrome_extension\\INSTALL.md",
                "apps\\chrome_extension\\TROUBLESHOOTING.md",
                "scripts\\check_local_reader_bundle.py",
                "scripts\\check_windows_service_task.py",
                "scripts\\check_chrome_extension_smoke.py",
                "--require-browser",
                "--browser-executable <path-to-browser>",
                "Chrome for Testing or Chromium",
                "config\\token.txt",
                "security.allowed_origins",
                "per-user autostart",
                "Task Scheduler",
                "tts.exe service-install --user",
                "logs\\tts-service.log",
            ]
        )
    return "placeholder"


def _load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
