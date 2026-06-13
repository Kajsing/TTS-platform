from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "README.md",
    "TESTING.md",
    "TASKS.md",
    "config/config.example.toml",
    "models/MANIFEST.json",
    "docs/backend_model_setup.md",
    "docs/v1_readiness.md",
    "scripts/release_check.py",
    "scripts/check_security_defaults.py",
    "scripts/check_extension.py",
    "scripts/check_extension_onboarding.py",
    "scripts/check_extension_reader_flow.py",
    "scripts/check_local_service_bootstrap.py",
    "scripts/check_model_management_flow.py",
    "scripts/check_windows_bundle_bootstrap.py",
    "scripts/check_windows_bundle_install.py",
    "scripts/check_windows_launchers.py",
    "scripts/package_extension.py",
    "scripts/package_windows_bundle.py",
    "scripts/smoke_service.py",
    "scripts/windows/install_local.ps1",
    "scripts/windows/install_local.cmd",
    "scripts/windows/run_service.ps1",
    "scripts/windows/run_service.cmd",
    "apps/chrome_extension/manifest.json",
    "apps/chrome_extension/src/background.js",
    "apps/chrome_extension/src/content-script.js",
    "apps/chrome_extension/src/popup.js",
    "apps/chrome_extension/offscreen/offscreen.js",
    "apps/tts_service/src/tts_service/cli.py",
    "packages/tts_core/src/tts_core/text.py",
)

READINESS_MARKERS = (
    "# V1 Readiness Audit",
    "## Automated Gates",
    "## Manual Gates",
    "## Product Choices",
    "## Known Not Yet Automated",
    "python3 scripts/release_check.py",
    "python3 scripts/check_security_defaults.py",
    "python3 scripts/check_extension.py",
    "python3 scripts/check_extension_onboarding.py",
    "python3 scripts/check_extension_reader_flow.py",
    "python3 scripts/check_local_service_bootstrap.py",
    "python3 scripts/check_model_management_flow.py",
    "python3 scripts/package_windows_bundle.py",
    "scripts/windows/install_local.ps1",
    "python3 scripts/check_windows_bundle_bootstrap.py",
    "python3 scripts/check_windows_launchers.py",
    "python3 scripts/check_windows_bundle_install.py",
    "launcher foreground service smoke",
    "python3 scripts/release_check.py --live-smoke --token-file config/token.txt",
    "--stream-text-repeat 200 --min-stream-text-chunks 2",
    "tts model-install <model-id> --catalog ./models/catalog.json --activate",
    "tts model-check <model-id>",
    "no full automated Chrome MV3 browser harness",
    "Permanent Windows auto-start/service-manager installation remains undecided",
)

REQUIRED_TEXT_MARKERS = {
    "scripts/release_check.py": (
        '"security_defaults"',
        '"v1_readiness"',
        '"local_service_bootstrap"',
        '"model_management_flow"',
        '"extension"',
        '"extension_onboarding"',
        '"extension_reader_flow"',
        '"extension_package"',
        '"windows_bundle"',
        '"windows_bundle_bootstrap"',
        '"windows_launchers"',
        '"windows_bundle_install"',
    ),
    "scripts/check_extension.py": (
        "verify_manifest_policy",
        "verify_extension_privacy_boundaries",
        "LOCAL_SERVICE_HOST_PERMISSIONS",
    ),
    "scripts/smoke_service.py": (
        "--stream-text-repeat",
        "--min-stream-text-chunks",
    ),
    "scripts/package_windows_bundle.py": (
        "docs/v1_readiness.md",
        "scripts/check_v1_readiness.py",
        "scripts/check_extension_onboarding.py",
        "scripts/check_extension_reader_flow.py",
        "scripts/check_local_service_bootstrap.py",
        "scripts/check_model_management_flow.py",
        "scripts/check_windows_bundle_bootstrap.py",
        "scripts/check_windows_bundle_install.py",
        "scripts/check_windows_launchers.py",
        "scripts/windows/install_local.ps1",
        "scripts/windows/install_local.cmd",
    ),
    "scripts/check_windows_bundle_install.py": (
        "_run_windows_install_script",
        '"installer_script"',
    ),
    "scripts/check_windows_launchers.py": (
        "_check_launcher_service",
        '"service_smoke"',
        '"foreground_service"',
    ),
    "TESTING.md": (
        "v1-readiness",
        "manual",
    ),
}


class V1ReadinessError(RuntimeError):
    pass


def main() -> None:
    summary = check_v1_readiness(repo_root=REPO_ROOT)
    print(json.dumps(summary, indent=2, sort_keys=True))


def check_v1_readiness(*, repo_root: Path) -> dict[str, object]:
    errors: list[str] = []
    missing_files = [
        relative_path
        for relative_path in REQUIRED_FILES
        if not (repo_root / relative_path).is_file()
    ]
    for relative_path in missing_files:
        errors.append(f"Missing required v1 artifact: {relative_path}")

    _check_markers(
        errors=errors,
        path=repo_root / "docs" / "v1_readiness.md",
        markers=READINESS_MARKERS,
    )
    for relative_path, markers in REQUIRED_TEXT_MARKERS.items():
        _check_markers(
            errors=errors,
            path=repo_root / relative_path,
            markers=markers,
        )

    if errors:
        raise V1ReadinessError("V1 readiness check failed:\n" + "\n".join(errors))

    return {
        "checked_files": len(REQUIRED_FILES),
        "readiness_markers": len(READINESS_MARKERS),
        "text_marker_files": sorted(REQUIRED_TEXT_MARKERS),
        "manual_gates_documented": True,
        "product_choices_documented": True,
    }


def _check_markers(*, errors: list[str], path: Path, markers: tuple[str, ...]) -> None:
    if not path.is_file():
        errors.append(f"Missing marker source: {_display_path(path)}")
        return
    contents = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in contents:
            errors.append(f"{_display_path(path)} must include {marker!r}")


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
