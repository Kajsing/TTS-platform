from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "README.md",
    "TESTING.md",
    "TASKS.md",
    "config/config.example.toml",
    "models/catalog.json",
    "models/MANIFEST.json",
    "docs/backend_model_setup.md",
    "docs/v1_readiness.md",
    "scripts/release_check.py",
    "scripts/check_security_defaults.py",
    "scripts/check_extension.py",
    "scripts/check_chrome_extension_smoke.py",
    "scripts/check_extension_onboarding.py",
    "scripts/check_extension_reader_flow.py",
    "scripts/check_local_service_bootstrap.py",
    "scripts/check_model_management_flow.py",
    "scripts/check_windows_bundle_bootstrap.py",
    "scripts/check_windows_bundle_install.py",
    "scripts/check_windows_launchers.py",
    "scripts/demo_real_voice.py",
    "scripts/package_extension.py",
    "scripts/package_windows_bundle.py",
    "scripts/smoke_service.py",
    "scripts/windows/install_local.ps1",
    "scripts/windows/install_local.cmd",
    "scripts/windows/run_service.ps1",
    "scripts/windows/run_service.cmd",
    "apps/chrome_extension/manifest.json",
    "apps/chrome_extension/INSTALL.md",
    "apps/chrome_extension/TROUBLESHOOTING.md",
    "apps/chrome_extension/icons/icon-16.png",
    "apps/chrome_extension/icons/icon-32.png",
    "apps/chrome_extension/icons/icon-48.png",
    "apps/chrome_extension/icons/icon-128.png",
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
    "Continue Page",
    "truncated text-offset continuation",
    "python3 scripts/check_local_service_bootstrap.py",
    "python3 scripts/check_model_management_flow.py",
    "python3 scripts/package_windows_bundle.py",
    "scripts/windows/install_local.ps1",
    "-InstallRealRuntime",
    "-NoDependencies",
    "python3 scripts/check_windows_bundle_bootstrap.py",
    "python3 scripts/check_windows_launchers.py",
    "python3 scripts/check_windows_bundle_install.py",
    "launcher foreground service smoke",
    "python3 scripts/release_check.py --live-smoke --token-file config/token.txt",
    "--stream-text-repeat 200 --min-stream-text-chunks 2",
    "tts model-install <model-id> --catalog ./models/catalog.json --activate",
    "tts model-install vits-piper-en_US-lessac-medium --activate",
    "catalog-aware first-run guidance",
    "tts model-list",
    "tts model-check <model-id>",
    "python -m pip install sherpa-onnx",
    "python -m pip install numpy",
    "--allow-missing-checksum",
    "python3 scripts/check_chrome_extension_smoke.py",
    "python3 scripts/release_check.py --require-browser",
    "Chrome for Testing",
    "python3 scripts/demo_real_voice.py",
    "python3 scripts/release_check.py --real-voice-demo --install-real-runtime",
    'pip install -e ".[real]"',
    "tts extension-allow-origin <copied-origin>",
    "copyable `tts extension-allow-origin`",
    "strict Chrome/MV3 smoke requires Chrome or Edge",
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
        '"chrome_extension_smoke"',
        '"extension_package"',
        '"windows_bundle"',
        '"windows_bundle_bootstrap"',
        '"windows_launchers"',
        '"windows_bundle_install"',
        "--browser-executable",
        "--require-browser",
        "--headed",
        "--node-executable",
        "--require-js-syntax",
        "--real-voice-demo",
        "--install-real-runtime",
        "TTS_PLATFORM_NODE",
        "_build_chrome_extension_smoke_command",
        "_build_package_extension_command",
        "_build_package_windows_bundle_command",
        "_build_real_voice_demo_command",
    ),
    "scripts/check_extension.py": (
        "verify_manifest_policy",
        "verify_extension_privacy_boundaries",
        "LOCAL_SERVICE_HOST_PERMISSIONS",
        "verify_extension_install_assets",
        "--require-js-syntax",
        "TTS_PLATFORM_NODE",
        "resolve_node_executable",
        '"tts-extension:continue-page"',
        "maybeAutoContinuePage",
        "origin-command",
        "buildOriginCliCommand",
    ),
    "scripts/check_extension_reader_flow.py": (
        '"tts-extension:continue-page"',
        "maybeAutoContinuePage",
        "page-auto-continue",
        "resolveContinueTextCharStart",
        "resolveContinueStartSectionIndex",
        "nextTextCharStart",
        '"automatic_truncated_text_continuation"',
        '"truncated_text_continuation"',
    ),
    "scripts/check_chrome_extension_smoke.py": (
        "--require-browser",
        "--browser-executable",
        "chrome-extension://",
        "EXTENSION_POPUP_PATH",
        "_wait_for_loaded_extension_id",
        "_create_extension_page_target",
        "_browser_extension_load_hint",
        "extension-allow-origin",
        "tts-extension:speak-page",
        "playbackState",
    ),
    "scripts/check_extension_onboarding.py": (
        "extension-allow-origin",
        "_verify_allow_list_cli_helper",
        "copy-command",
        "originCliCommand",
    ),
    "scripts/smoke_service.py": (
        "--stream-text-repeat",
        "--min-stream-text-chunks",
    ),
    "scripts/windows/install_local.ps1": (
        "InstallRealRuntime",
        "NoDependencies",
        "$RepoRoot[real]",
        "dependencies_installed",
        "real_runtime_installed",
    ),
    "scripts/demo_real_voice.py": (
        "dist",
        "real-demo",
        "--install-real-runtime",
        "_install_real_runtime_dependencies",
        "model-install",
        "model-check",
        "smoke_service.py",
        "--token-file",
        "lessac-demo.wav",
        "_stop_process_tree",
    ),
    "scripts/check_local_service_bootstrap.py": (
        "models/catalog.json",
        "_assert_setup_guidance",
        "catalog_single_installable_model",
        "setup-local did not put the default catalog install step first",
    ),
    "scripts/package_windows_bundle.py": (
        "docs/v1_readiness.md",
        "models/catalog.json",
        "apps\\\\chrome_extension\\\\INSTALL.md",
        "TROUBLESHOOTING.md",
        "scripts/check_v1_readiness.py",
        "scripts/check_chrome_extension_smoke.py",
        "scripts/check_extension_onboarding.py",
        "scripts/check_extension_reader_flow.py",
        "scripts/check_local_service_bootstrap.py",
        "scripts/check_model_management_flow.py",
        "scripts/check_windows_bundle_bootstrap.py",
        "scripts/check_windows_bundle_install.py",
        "scripts/check_windows_launchers.py",
        "scripts/demo_real_voice.py",
        "scripts/windows/install_local.ps1",
        "scripts/windows/install_local.cmd",
        "-InstallRealRuntime",
        "-NoDependencies",
        "--node-executable",
        "--require-js-syntax",
        "js_syntax_required",
        'pip install -e ".[real]"',
        "should put the `model-install` command above first",
        ".\\\\.venv\\\\Scripts\\\\python.exe -m pip install -e \".[real]\"",
        "demo_real_voice.py",
        "--install-real-runtime",
        "extension-allow-origin",
    ),
    "scripts/package_extension.py": (
        "--node-executable",
        "--require-js-syntax",
        "js_syntax_required",
        "TROUBLESHOOTING.md",
    ),
    "scripts/check_windows_bundle_install.py": (
        "_run_windows_install_script",
        '"installer_script"',
        "--install-real-runtime",
        "-InstallRealRuntime",
        "--no-dependencies",
        "-NoDependencies",
        '"dependencies_installed"',
        '"real_runtime_installed"',
        "catalog_single_installable_model",
        "Installed setup-local did not put the default catalog install step first",
    ),
    "scripts/check_windows_bundle_bootstrap.py": (
        "catalog_single_installable_model",
        "setup-local did not put the default catalog install step first",
        "TROUBLESHOOTING.md",
    ),
    "apps/tts_service/src/tts_service/cli.py": (
        "tarfile",
        "--allow-missing-checksum",
        "Catalog model",
        "missing artifact_sha256",
        "installable_model_ids",
        "_model_check_catalog_model_ref",
        "model-list",
        "_list_models",
        "_model_list_default_model",
        "_append_sherpa_onnx_install_step",
        "REAL_RUNTIME_INSTALL_STEP",
        "SHERPA_ONNX_INSTALL_STEP",
        "NUMPY_INSTALL_STEP",
        "numpy_installed",
        "_setup_local_model_install_step",
        "default_voice_has_backend_config",
        "extension-allow-origin",
        "_allow_extension_origin",
    ),
    "scripts/check_windows_launchers.py": (
        "_check_launcher_service",
        '"service_smoke"',
        '"foreground_service"',
        "catalog_single_installable_model",
    ),
    "scripts/check_model_management_flow.py": (
        '"model-list"',
        '"model_list"',
        "_summarize_model_list",
        "sherpa_onnx_installed",
    ),
    "TESTING.md": (
        "v1-readiness",
        "manual",
        "INSTALL.md",
        "TROUBLESHOOTING.md",
        "icon",
        "Continue Page",
        "truncated text-offset continuation",
        "check_chrome_extension_smoke.py",
        "Chrome for Testing",
        "extension-allow-origin",
        "copy-command",
        "catalog-aware `setup-local`",
        "`sherpa_onnx` runtime install",
        "numpy",
        "demo_real_voice.py",
        "--install-real-runtime",
        ".[real]",
        "-InstallRealRuntime",
        "--install-real-runtime",
        "-NoDependencies",
        "--no-dependencies",
    ),
    "apps/chrome_extension/README.md": (
        "INSTALL.md",
        "TROUBLESHOOTING.md",
        "icons",
        "Continue Page",
        "next known text character offset",
        "check_chrome_extension_smoke.py",
        "extension-allow-origin",
        "allow-list command",
    ),
    "docs/backend_model_setup.md": (
        "vits-piper-en_US-lessac-medium",
        "tar.bz2",
        "demo_real_voice.py",
        "numpy",
        ".[real]",
        "model-list",
        "Continue Page",
        "non-textual character offset",
        "check_chrome_extension_smoke.py",
        "extension-allow-origin",
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
