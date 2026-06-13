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
    parser.add_argument(
        "--live-smoke",
        action="store_true",
        help="Also run scripts/smoke_service.py against an already running local service.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:7777")
    parser.add_argument("--token", default=None)
    parser.add_argument("--token-file", default=None)
    parser.add_argument("--voice", default=None)
    args = parser.parse_args(argv)

    try:
        summary = run_release_checks(
            python_executable=sys.executable,
            package_out_path=Path(args.package_out) if args.package_out else None,
            live_smoke=args.live_smoke,
            base_url=args.base_url,
            token=args.token,
            token_file=args.token_file,
            voice=args.voice,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def run_release_checks(
    *,
    python_executable: str,
    package_out_path: Path | None = None,
    live_smoke: bool = False,
    base_url: str = "http://127.0.0.1:7777",
    token: str | None = None,
    token_file: str | None = None,
    voice: str | None = None,
) -> dict[str, object]:
    if package_out_path is not None:
        return _run_release_checks_with_package_path(
            python_executable=python_executable,
            package_out_path=package_out_path.expanduser().resolve(),
            live_smoke=live_smoke,
            base_url=base_url,
            token=token,
            token_file=token_file,
            voice=voice,
        )

    with tempfile.TemporaryDirectory(prefix="tts-platform-release-") as temp_dir:
        return _run_release_checks_with_package_path(
            python_executable=python_executable,
            package_out_path=Path(temp_dir) / "tts-platform-prototype.zip",
            live_smoke=live_smoke,
            base_url=base_url,
            token=token,
            token_file=token_file,
            voice=voice,
        )


def _run_release_checks_with_package_path(
    *,
    python_executable: str,
    package_out_path: Path,
    live_smoke: bool,
    base_url: str,
    token: str | None,
    token_file: str | None,
    voice: str | None,
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
    if live_smoke:
        checks.append(
            (
                "live_smoke",
                _build_live_smoke_command(
                    python_executable=python_executable,
                    base_url=base_url,
                    token=token,
                    token_file=token_file,
                    voice=voice,
                ),
            )
        )
    completed: list[dict[str, object]] = []
    for name, command in checks:
        print(f"[release-check] {name}", file=sys.stderr)
        subprocess.run(command, cwd=REPO_ROOT, check=True)
        completed.append({"name": name, "command": _redact_command(command)})

    return {
        "checks": completed,
        "package_path": str(package_out_path),
    }


def _build_live_smoke_command(
    *,
    python_executable: str,
    base_url: str,
    token: str | None,
    token_file: str | None,
    voice: str | None,
) -> list[str]:
    command = [
        python_executable,
        "scripts/smoke_service.py",
        "--base-url",
        base_url.rstrip("/"),
    ]
    if token:
        command.extend(["--token", token])
    if token_file:
        command.extend(["--token-file", token_file])
    if voice:
        command.extend(["--voice", voice])
    return command


def _redact_command(command: list[str]) -> list[str]:
    redacted = list(command)
    for index, value in enumerate(redacted[:-1]):
        if value == "--token":
            redacted[index + 1] = "<redacted>"
    return redacted


if __name__ == "__main__":
    main()
