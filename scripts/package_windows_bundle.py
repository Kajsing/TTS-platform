from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import zipfile
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
DEFAULT_OUT_PATH = REPO_ROOT / "dist" / "windows" / "tts-platform-local-reader.zip"
BUNDLE_ROOT = "tts-platform"
EXTENSION_PACKAGE_ARCNAME = (
    f"{BUNDLE_ROOT}/dist/chrome_extension/tts-platform-prototype.zip"
)

INCLUDED_FILES = (
    "AGENTS.md",
    "README.md",
    "TESTING.md",
    "pyproject.toml",
    "config/config.example.toml",
    "docs/backend_model_setup.md",
    "docs/codex/Documentation.md",
    "docs/codex/Implement.md",
    "docs/codex/Plan.md",
    "docs/codex/Prompt.md",
    "docs/v1_readiness.md",
    "models/MANIFEST.json",
    "scripts/benchmark.py",
    "scripts/check_extension.py",
    "scripts/check_local_service_bootstrap.py",
    "scripts/check_security_defaults.py",
    "scripts/check_v1_readiness.py",
    "scripts/check_windows_bundle_bootstrap.py",
    "scripts/dev_run.py",
    "scripts/package_extension.py",
    "scripts/package_windows_bundle.py",
    "scripts/release_check.py",
    "scripts/smoke_service.py",
    "scripts/windows/run_service.cmd",
    "scripts/windows/run_service.ps1",
)

INCLUDED_DIRS = (
    "apps/chrome_extension",
    "apps/tts_service/src",
    "packages/tts_core/src",
)

EXCLUDED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
}

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="package_windows_bundle")
    parser.add_argument("--out", default=str(DEFAULT_OUT_PATH))
    args = parser.parse_args(argv)

    payload = package_windows_bundle(out_path=Path(args.out))
    print(json.dumps(payload, indent=2, sort_keys=True))


def package_windows_bundle(*, out_path: Path) -> dict[str, object]:
    resolved_out_path = out_path.expanduser().resolve()
    bundle_files = _collect_bundle_files()
    resolved_out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tts-platform-extension-") as temp_dir:
        extension_zip_path = Path(temp_dir) / "tts-platform-prototype.zip"
        extension_payload = extension_packager.package_extension(out_path=extension_zip_path)

        with zipfile.ZipFile(
            resolved_out_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in bundle_files:
                archive.write(path, _archive_name(path))
            archive.write(extension_zip_path, EXTENSION_PACKAGE_ARCNAME)
            archive.writestr(
                f"{BUNDLE_ROOT}/WINDOWS_BUNDLE_README.md",
                _windows_bundle_readme(),
            )

    return {
        "package_path": str(resolved_out_path),
        "bundle_root": BUNDLE_ROOT,
        "file_count": len(bundle_files) + 2,
        "extension_package": {
            "archive_path": EXTENSION_PACKAGE_ARCNAME.removeprefix(f"{BUNDLE_ROOT}/"),
            "file_count": extension_payload["file_count"],
            "manifest_path": extension_payload["manifest_path"],
        },
    }


def _collect_bundle_files() -> list[Path]:
    files: set[Path] = set()
    for relative_path in INCLUDED_FILES:
        path = REPO_ROOT / relative_path
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        files.add(path)

    for relative_dir in INCLUDED_DIRS:
        root = REPO_ROOT / relative_dir
        if not root.is_dir():
            raise FileNotFoundError(relative_dir)
        for path in root.rglob("*"):
            if path.is_file() and not _is_excluded(path):
                files.add(path)

    return sorted(files)


def _load_script_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extension_packager = _load_script_module(
    "tts_platform_package_extension",
    SCRIPT_DIR / "package_extension.py",
)


def _is_excluded(path: Path) -> bool:
    parts = set(path.relative_to(REPO_ROOT).parts)
    return bool(parts & EXCLUDED_PARTS)


def _archive_name(path: Path) -> str:
    relative_path = path.relative_to(REPO_ROOT).as_posix()
    return f"{BUNDLE_ROOT}/{relative_path}"


def _windows_bundle_readme() -> str:
    return """# TTS Platform Local Reader Bundle

This bundle is a Windows-friendly local source package for the TTS service and
Chrome extension prototype. It does not install a persistent Windows service
manager, scheduled task, or auto-start entry.

## First Run

1. Extract the zip.
2. Open PowerShell in the extracted `tts-platform` directory.
3. Create and activate a virtual environment:

   ```powershell
   py -3 -m venv .venv
   .\\.venv\\Scripts\\Activate.ps1
   python -m pip install -e ".[dev]"
   ```

4. Start the local service:

   ```powershell
   .\\scripts\\windows\\run_service.ps1
   ```

   The launcher creates `config\\config.toml` and `config\\token.txt` on first
   run when needed, then starts `tts serve` on the configured loopback address.

5. Load the Chrome extension:

   - use `apps\\chrome_extension` with Chrome's `Load unpacked`, or
   - extract `dist\\chrome_extension\\tts-platform-prototype.zip` for a packaged
     local handoff build.

6. Copy the extension origin from the popup into `security.allowed_origins` in
   `config\\config.toml`, restart the service, then save the token from
   `config\\token.txt` in the popup.

## Notes

- Real acoustic output still requires installing and activating a local model.
- Keep `config\\token.txt` local. It is generated after extraction and is not
  included in this bundle.
- Use `docs\\backend_model_setup.md` for model-management and troubleshooting.
"""


if __name__ == "__main__":
    main()
