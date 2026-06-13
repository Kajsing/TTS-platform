from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
BUNDLE_ROOT = "tts-platform"
EXTENSION_PACKAGE_ARCNAME = (
    f"{BUNDLE_ROOT}/dist/chrome_extension/tts-platform-prototype.zip"
)
README_ARCNAME = f"{BUNDLE_ROOT}/WINDOWS_BUNDLE_README.md"

README_MARKERS = (
    "py -3 -m venv .venv",
    'python -m pip install -e ".[dev]"',
    "python -m tts_service.cli setup-local --repo-root .",
    ".\\.venv\\Scripts\\tts.exe model-check",
    ".\\.venv\\Scripts\\tts.exe catalog-list",
    "tts.exe model-install vits-piper-en_US-lessac-medium --activate",
    "tts.exe model-install <model-id> --catalog <catalog> --activate",
    ".\\scripts\\windows\\run_service.ps1 -SetupOnly",
    ".\\scripts\\windows\\run_service.ps1",
    "config\\token.txt",
    "security.allowed_origins",
    "persistent Windows service",
    "apps\\chrome_extension\\INSTALL.md",
)

EXTENSION_PACKAGE_MARKERS = (
    "manifest.json",
    "INSTALL.md",
    "icons/icon-16.png",
    "icons/icon-32.png",
    "icons/icon-48.png",
    "icons/icon-128.png",
)


class WindowsBundleBootstrapError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_windows_bundle_bootstrap")
    parser.add_argument("--bundle", default=None)
    parser.add_argument("--python-executable", default=sys.executable)
    args = parser.parse_args(argv)

    if args.bundle:
        summary = check_windows_bundle_bootstrap(
            bundle_path=Path(args.bundle),
            python_executable=args.python_executable,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="tts-platform-bundle-check-") as temp_dir:
            bundle_path = Path(temp_dir) / "tts-platform-local-reader.zip"
            package_windows_bundle.package_windows_bundle(out_path=bundle_path)
            summary = check_windows_bundle_bootstrap(
                bundle_path=bundle_path,
                python_executable=args.python_executable,
            )

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_windows_bundle_bootstrap(
    *,
    bundle_path: Path,
    python_executable: str,
) -> dict[str, object]:
    resolved_bundle_path = bundle_path.expanduser().resolve()
    if not resolved_bundle_path.is_file():
        raise WindowsBundleBootstrapError(f"Bundle does not exist: {resolved_bundle_path}")

    with tempfile.TemporaryDirectory(prefix="tts-platform-bundle-extract-") as temp_dir:
        extract_root = Path(temp_dir)
        with zipfile.ZipFile(resolved_bundle_path) as archive:
            names = set(archive.namelist())
            _assert_safe_archive_members(archive=archive, out_dir=extract_root)
            _assert_bundle_contents(names=names)
            readme_text = archive.read(README_ARCNAME).decode("utf-8")
            _assert_readme_markers(readme_text)
            extension_file_count = _inspect_extension_zip(archive)
            archive.extractall(extract_root)

        bundle_root = extract_root / BUNDLE_ROOT
        setup_payload = _run_setup_local(
            bundle_root=bundle_root,
            python_executable=python_executable,
        )
        _assert_setup_payload(setup_payload=setup_payload, bundle_root=bundle_root)

    return {
        "bundle_path": str(resolved_bundle_path),
        "bundle_root": BUNDLE_ROOT,
        "extension_package": {
            "archive_path": EXTENSION_PACKAGE_ARCNAME.removeprefix(f"{BUNDLE_ROOT}/"),
            "file_count": extension_file_count,
            "manifest_path": "manifest.json",
        },
        "setup": {
            "config_created": setup_payload["config_created"],
            "token_created": setup_payload["token_created"],
            "base_url": setup_payload["service"]["base_url"],
            "default_voice": setup_payload["default_voice"],
            "manifest_default_voice": setup_payload["manifest"][
                "default_voice_in_manifest"
            ],
            "next_steps": _string_list(setup_payload.get("next_steps")),
        },
    }


def _assert_bundle_contents(*, names: set[str]) -> None:
    required_names = {
        f"{BUNDLE_ROOT}/pyproject.toml",
        f"{BUNDLE_ROOT}/config/config.example.toml",
        f"{BUNDLE_ROOT}/models/catalog.json",
        f"{BUNDLE_ROOT}/models/MANIFEST.json",
        f"{BUNDLE_ROOT}/docs/v1_readiness.md",
        f"{BUNDLE_ROOT}/scripts/windows/run_service.ps1",
        f"{BUNDLE_ROOT}/scripts/windows/run_service.cmd",
        README_ARCNAME,
        EXTENSION_PACKAGE_ARCNAME,
    }
    missing = sorted(required_names - names)
    if missing:
        raise WindowsBundleBootstrapError(
            "Bundle is missing required entries:\n" + "\n".join(missing)
        )
    if f"{BUNDLE_ROOT}/config/token.txt" in names:
        raise WindowsBundleBootstrapError("Bundle must not include config/token.txt")
    if f"{BUNDLE_ROOT}/config/config.toml" in names:
        raise WindowsBundleBootstrapError("Bundle must not include config/config.toml")
    if any(name.startswith(f"{BUNDLE_ROOT}/models/voices/") for name in names):
        raise WindowsBundleBootstrapError("Bundle must not include installed model files")


def _assert_readme_markers(readme_text: str) -> None:
    missing = [marker for marker in README_MARKERS if marker not in readme_text]
    if missing:
        raise WindowsBundleBootstrapError(
            "Windows bundle README is missing markers:\n" + "\n".join(missing)
        )


def _inspect_extension_zip(archive: zipfile.ZipFile) -> int:
    try:
        payload = archive.read(EXTENSION_PACKAGE_ARCNAME)
    except KeyError as exc:
        raise WindowsBundleBootstrapError("Bundle is missing extension package") from exc

    with zipfile.ZipFile(io.BytesIO(payload)) as extension_archive:
        extension_names = set(extension_archive.namelist())
        missing = sorted(set(EXTENSION_PACKAGE_MARKERS) - extension_names)
        if missing:
            raise WindowsBundleBootstrapError(
                "Embedded extension package is missing entries:\n" + "\n".join(missing)
            )
        return len(extension_names)


def _run_setup_local(*, bundle_root: Path, python_executable: str) -> dict[str, object]:
    env = dict(os.environ)
    python_paths = [
        str(bundle_root / "apps" / "tts_service" / "src"),
        str(bundle_root / "packages" / "tts_core" / "src"),
    ]
    existing_python_path = env.get("PYTHONPATH")
    if existing_python_path:
        python_paths.append(existing_python_path)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)

    completed = subprocess.run(
        [
            python_executable,
            "-m",
            "tts_service.cli",
            "setup-local",
            "--repo-root",
            str(bundle_root),
        ],
        cwd=bundle_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WindowsBundleBootstrapError(
            "setup-local did not return a JSON object"
        ) from exc


def _assert_setup_payload(*, setup_payload: dict[str, object], bundle_root: Path) -> None:
    config_path = Path(str(setup_payload.get("config_path", "")))
    token_path = Path(str(setup_payload.get("token_file", "")))
    service = setup_payload.get("service")
    manifest = setup_payload.get("manifest")
    next_steps = setup_payload.get("next_steps")

    if setup_payload.get("config_created") is not True:
        raise WindowsBundleBootstrapError("setup-local did not create config/config.toml")
    if setup_payload.get("token_created") is not True:
        raise WindowsBundleBootstrapError("setup-local did not create config/token.txt")
    if not config_path.is_file() or bundle_root not in config_path.resolve().parents:
        raise WindowsBundleBootstrapError("setup-local config path is not inside the bundle")
    if not token_path.is_file() or bundle_root not in token_path.resolve().parents:
        raise WindowsBundleBootstrapError("setup-local token path is not inside the bundle")
    token_value = token_path.read_text(encoding="utf-8").strip()
    if not token_value:
        raise WindowsBundleBootstrapError("setup-local created an empty token file")
    if not isinstance(service, dict) or service.get("base_url") != "http://127.0.0.1:7777":
        raise WindowsBundleBootstrapError("setup-local service base URL is not loopback default")
    if not isinstance(manifest, dict) or manifest.get("exists") is not True:
        raise WindowsBundleBootstrapError("setup-local did not find models/MANIFEST.json")
    if not isinstance(next_steps, list) or "tts serve" not in next_steps:
        raise WindowsBundleBootstrapError("setup-local next steps do not include tts serve")
    if "tts model-check" not in next_steps:
        raise WindowsBundleBootstrapError("setup-local next steps do not include tts model-check")


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _assert_safe_archive_members(*, archive: zipfile.ZipFile, out_dir: Path) -> None:
    out_dir_resolved = out_dir.resolve()
    for member in archive.infolist():
        posix_member_path = PurePosixPath(member.filename)
        windows_member_path = PureWindowsPath(member.filename)
        if (
            posix_member_path.is_absolute()
            or windows_member_path.is_absolute()
            or windows_member_path.drive
        ):
            raise WindowsBundleBootstrapError(
                f"Bundle contains absolute path entry: {member.filename!r}"
            )
        if ".." in posix_member_path.parts or ".." in windows_member_path.parts:
            raise WindowsBundleBootstrapError(
                f"Bundle contains unsafe path traversal entry: {member.filename!r}"
            )
        member_path = Path(*posix_member_path.parts)
        destination = (out_dir_resolved / member_path).resolve()
        if destination != out_dir_resolved and out_dir_resolved not in destination.parents:
            raise WindowsBundleBootstrapError(
                f"Bundle contains unsafe path traversal entry: {member.filename!r}"
            )


def _load_script_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package_windows_bundle = _load_script_module(
    "tts_platform_package_windows_bundle",
    SCRIPT_DIR / "package_windows_bundle.py",
)


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, WindowsBundleBootstrapError) as exc:
        raise SystemExit(str(exc)) from exc
