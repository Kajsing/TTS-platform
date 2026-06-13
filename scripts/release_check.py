from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="release_check")
    parser.add_argument("--package-out", default=None)
    args = parser.parse_args(argv)

    try:
        summary = run_release_checks(
            python_executable=sys.executable,
            package_out_path=Path(args.package_out) if args.package_out else None,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def run_release_checks(
    *,
    python_executable: str,
    package_out_path: Path | None = None,
) -> dict[str, object]:
    if package_out_path is not None:
        return _run_release_checks_with_package_path(
            python_executable=python_executable,
            package_out_path=package_out_path.expanduser().resolve(),
        )

    with tempfile.TemporaryDirectory(prefix="tts-platform-release-") as temp_dir:
        return _run_release_checks_with_package_path(
            python_executable=python_executable,
            package_out_path=Path(temp_dir) / "tts-platform-prototype.zip",
        )


def _run_release_checks_with_package_path(
    *,
    python_executable: str,
    package_out_path: Path,
) -> dict[str, object]:
    checks = [
        ("ruff", [python_executable, "-m", "ruff", "check", "."]),
        ("pytest", [python_executable, "-m", "pytest", "-q"]),
        ("extension", [python_executable, "scripts/check_extension.py"]),
        (
            "extension_package",
            [
                python_executable,
                "scripts/package_extension.py",
                "--out",
                str(package_out_path),
            ],
        ),
    ]
    completed: list[dict[str, object]] = []
    for name, command in checks:
        print(f"[release-check] {name}", file=sys.stderr)
        subprocess.run(command, cwd=REPO_ROOT, check=True)
        completed.append({"name": name, "command": command})

    return {
        "checks": completed,
        "package_path": str(package_out_path),
    }


if __name__ == "__main__":
    main()
