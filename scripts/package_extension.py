from __future__ import annotations

import argparse
import json
import sys
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
EXTENSION_ROOT = REPO_ROOT / "apps" / "chrome_extension"
DEFAULT_OUT_PATH = REPO_ROOT / "dist" / "chrome_extension" / "tts-platform-prototype.zip"
ICON_ARCNAMES = (
    "icons/icon-16.png",
    "icons/icon-32.png",
    "icons/icon-48.png",
    "icons/icon-128.png",
)

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import check_extension  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="package_extension")
    parser.add_argument("--out", default=str(DEFAULT_OUT_PATH))
    args = parser.parse_args(argv)

    payload = package_extension(out_path=Path(args.out))
    print(json.dumps(payload, indent=2, sort_keys=True))


def package_extension(*, out_path: Path) -> dict[str, object]:
    with redirect_stdout(sys.stderr):
        check_extension.main()
    resolved_out_path = out_path.expanduser().resolve()
    files = _collect_extension_files()
    resolved_out_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(resolved_out_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative_path = path.relative_to(EXTENSION_ROOT).as_posix()
            archive.write(path, relative_path)

    return {
        "package_path": str(resolved_out_path),
        "file_count": len(files),
        "manifest_path": "manifest.json",
        "install_guide_path": "INSTALL.md",
        "icon_count": sum(
            1
            for path in files
            if path.relative_to(EXTENSION_ROOT).as_posix() in ICON_ARCNAMES
        ),
    }


def _collect_extension_files() -> list[Path]:
    excluded_parts = {"__pycache__"}
    files: list[Path] = []
    for path in EXTENSION_ROOT.rglob("*"):
        relative_parts = set(path.relative_to(EXTENSION_ROOT).parts)
        if relative_parts & excluded_parts:
            continue
        if path.is_file():
            files.append(path)
    return sorted(files)


if __name__ == "__main__":
    main()
