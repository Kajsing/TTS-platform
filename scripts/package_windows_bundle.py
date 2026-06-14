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
    "models/catalog.json",
    "models/MANIFEST.json",
    "scripts/benchmark.py",
    "scripts/check_extension.py",
    "scripts/check_chrome_extension_smoke.py",
    "scripts/check_extension_onboarding.py",
    "scripts/check_extension_reader_flow.py",
    "scripts/check_local_service_bootstrap.py",
    "scripts/check_model_management_flow.py",
    "scripts/check_security_defaults.py",
    "scripts/check_v1_readiness.py",
    "scripts/check_windows_bundle_bootstrap.py",
    "scripts/check_windows_bundle_install.py",
    "scripts/check_windows_launchers.py",
    "scripts/demo_real_voice.py",
    "scripts/dev_run.py",
    "scripts/package_extension.py",
    "scripts/package_windows_bundle.py",
    "scripts/release_check.py",
    "scripts/smoke_service.py",
    "scripts/windows/install_local.cmd",
    "scripts/windows/install_local.ps1",
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
    parser.add_argument("--node-executable", default=None)
    parser.add_argument(
        "--require-js-syntax",
        action="store_true",
        help="Fail extension validation when JavaScript syntax checks cannot run.",
    )
    args = parser.parse_args(argv)

    payload = package_windows_bundle(
        out_path=Path(args.out),
        node_executable=args.node_executable,
        require_js_syntax=args.require_js_syntax,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


def package_windows_bundle(
    *,
    out_path: Path,
    node_executable: str | None = None,
    require_js_syntax: bool = False,
) -> dict[str, object]:
    resolved_out_path = out_path.expanduser().resolve()
    bundle_files = _collect_bundle_files()
    resolved_out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tts-platform-extension-") as temp_dir:
        extension_zip_path = Path(temp_dir) / "tts-platform-prototype.zip"
        extension_payload = extension_packager.package_extension(
            out_path=extension_zip_path,
            node_executable=node_executable,
            require_js_syntax=require_js_syntax,
        )

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

    extension_summary = {
        "archive_path": EXTENSION_PACKAGE_ARCNAME.removeprefix(f"{BUNDLE_ROOT}/"),
        "file_count": extension_payload["file_count"],
        "manifest_path": extension_payload["manifest_path"],
    }
    if "install_guide_path" in extension_payload:
        extension_summary["install_guide_path"] = extension_payload["install_guide_path"]
    if "troubleshooting_path" in extension_payload:
        extension_summary["troubleshooting_path"] = extension_payload[
            "troubleshooting_path"
        ]
    if "icon_count" in extension_payload:
        extension_summary["icon_count"] = extension_payload["icon_count"]
    if "js_syntax_required" in extension_payload:
        extension_summary["js_syntax_required"] = extension_payload[
            "js_syntax_required"
        ]

    return {
        "package_path": str(resolved_out_path),
        "bundle_root": BUNDLE_ROOT,
        "file_count": len(bundle_files) + 2,
        "extension_package": extension_summary,
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
3. Install the local package:

   ```powershell
   .\\scripts\\windows\\install_local.ps1
   ```

   The installer creates `.venv`, installs the local package with its base
   dependencies, and runs `tts setup-local`. Use `install_local.cmd` when
   launching from `cmd.exe`. Use `-NoDependencies` only when the environment is
   already provisioned and dependency installation should be skipped.
   Add `-InstallRealRuntime` when this machine should install the optional
   `.[real]` runtime dependencies during bootstrap:

   ```powershell
   .\\scripts\\windows\\install_local.ps1 -InstallRealRuntime
   ```

   The equivalent manual commands are:

   ```powershell
   py -3 -m venv .venv
   .\\.venv\\Scripts\\Activate.ps1
   python -m pip install -e ".[dev]"
   python -m pip install -e ".[real]"
   python -m tts_service.cli setup-local --repo-root .
   ```

4. Install the default English voice and re-check readiness before expecting
   real acoustic output:

   ```powershell
   .\\.venv\\Scripts\\tts.exe catalog-list
   .\\.venv\\Scripts\\tts.exe model-list
   .\\.venv\\Scripts\\python.exe -m pip install -e ".[real]"
   .\\.venv\\Scripts\\python.exe -m pip install sherpa-onnx
   .\\.venv\\Scripts\\python.exe -m pip install numpy
   .\\.venv\\Scripts\\tts.exe model-install vits-piper-en_US-lessac-medium --activate
   .\\.venv\\Scripts\\tts.exe model-check vits-piper-en_US-lessac-medium
   ```

   The bundled manifest includes the development/debug voice for local service
   smoke tests. `setup-local` prints JSON next steps and, with the bundled
   default catalog, should put the `model-install` command above first. If
   `sherpa_onnx` or `numpy` is not importable in `.venv`, setup/list/check
   guidance also includes the runtime install commands above. For alternate
   catalogs, install and activate a real model from that catalog, then re-check
   readiness:

   ```powershell
   .\\.venv\\Scripts\\tts.exe model-install <model-id> --catalog <catalog> --activate
   .\\.venv\\Scripts\\tts.exe model-check <model-id>
   ```

5. Optionally generate a real English voice demo WAV from an isolated
   `dist\\real-demo` root:

   ```powershell
   .\\.venv\\Scripts\\python.exe scripts\\demo_real_voice.py `
     --python-executable .\\.venv\\Scripts\\python.exe
   .\\.venv\\Scripts\\python.exe scripts\\demo_real_voice.py `
     --python-executable .\\.venv\\Scripts\\python.exe `
     --install-real-runtime
   ```

   The demo script installs the default catalog model in the ignored demo
   root, starts a temporary loopback service, runs public-contract smoke with a
   token file, writes `dist\\real-demo\\lessac-demo.wav`, and stops the
   service process. Use `--install-real-runtime` when this environment should
   install `.[real]` as part of the demo run.

6. Start the local service:

   ```powershell
   .\\scripts\\windows\\run_service.ps1 -SetupOnly
   .\\scripts\\windows\\run_service.ps1
   ```

   The optional `-SetupOnly` check creates `config\\config.toml` and
   `config\\token.txt` without starting the service. Running the launcher
   without `-SetupOnly` then starts `tts serve` on the configured loopback
   address.

   `scripts\\check_windows_launchers.py` validates both the setup-only path and
   the foreground service smoke path for the bundled PowerShell/CMD launchers on
   Windows.

7. Load the Chrome extension:

   - use `apps\\chrome_extension` with Chrome's `Load unpacked`, or
   - extract `dist\\chrome_extension\\tts-platform-prototype.zip` for a packaged
     local handoff build.
   - follow `apps\\chrome_extension\\INSTALL.md` for the local loading and first
     playback checklist.
   - use `apps\\chrome_extension\\TROUBLESHOOTING.md` if the popup cannot reach
     the service, backend readiness is not green, or long-page playback needs
     recovery.

8. Copy the `Allow-List Command` from the popup, then run it to update
   `security.allowed_origins`:

   ```powershell
   .\\.venv\\Scripts\\tts.exe extension-allow-origin <copied-origin>
   ```

   Restart the service, then save the token from `config\\token.txt` in the
   popup.

## Notes

- Real acoustic output still requires installing and activating a local model.
- Keep `config\\token.txt` local. It is generated after extraction and is not
  included in this bundle.
- Use `docs\\backend_model_setup.md` for model-management and troubleshooting.
"""


if __name__ == "__main__":
    main()
