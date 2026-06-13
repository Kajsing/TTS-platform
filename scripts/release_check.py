from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="release_check")
    parser.add_argument("--package-out", default=None)
    parser.add_argument("--windows-bundle-out", default=None)
    parser.add_argument(
        "--live-smoke",
        action="store_true",
        help="Also run scripts/smoke_service.py against an already running local service.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:7777")
    parser.add_argument("--token", default=None)
    parser.add_argument("--token-file", default=None)
    parser.add_argument("--voice", default=None)
    parser.add_argument("--smoke-text", default=None)
    parser.add_argument("--stream-text", default=None)
    parser.add_argument("--stream-text-file", default=None)
    parser.add_argument("--stream-text-repeat", type=int, default=1)
    parser.add_argument("--min-stream-text-chunks", type=int, default=1)
    parser.add_argument("--node-executable", default=None)
    parser.add_argument(
        "--require-js-syntax",
        action="store_true",
        help="Fail extension validation when JavaScript syntax checks cannot run.",
    )
    args = parser.parse_args(argv)

    try:
        summary = run_release_checks(
            python_executable=sys.executable,
            package_out_path=Path(args.package_out) if args.package_out else None,
            windows_bundle_out_path=(
                Path(args.windows_bundle_out) if args.windows_bundle_out else None
            ),
            live_smoke=args.live_smoke,
            base_url=args.base_url,
            token=args.token,
            token_file=args.token_file,
            voice=args.voice,
            smoke_text=args.smoke_text,
            stream_text=args.stream_text,
            stream_text_file=args.stream_text_file,
            stream_text_repeat=args.stream_text_repeat,
            min_stream_text_chunks=args.min_stream_text_chunks,
            node_executable=args.node_executable,
            require_js_syntax=args.require_js_syntax,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def run_release_checks(
    *,
    python_executable: str,
    package_out_path: Path | None = None,
    windows_bundle_out_path: Path | None = None,
    live_smoke: bool = False,
    base_url: str = "http://127.0.0.1:7777",
    token: str | None = None,
    token_file: str | None = None,
    voice: str | None = None,
    smoke_text: str | None = None,
    stream_text: str | None = None,
    stream_text_file: str | None = None,
    stream_text_repeat: int = 1,
    min_stream_text_chunks: int = 1,
    node_executable: str | None = None,
    require_js_syntax: bool = False,
) -> dict[str, object]:
    if package_out_path is not None and windows_bundle_out_path is not None:
        return _run_release_checks_with_package_path(
            python_executable=python_executable,
            package_out_path=package_out_path.expanduser().resolve(),
            windows_bundle_out_path=windows_bundle_out_path.expanduser().resolve(),
            live_smoke=live_smoke,
            base_url=base_url,
            token=token,
            token_file=token_file,
            voice=voice,
            smoke_text=smoke_text,
            stream_text=stream_text,
            stream_text_file=stream_text_file,
            stream_text_repeat=stream_text_repeat,
            min_stream_text_chunks=min_stream_text_chunks,
            node_executable=node_executable,
            require_js_syntax=require_js_syntax,
        )

    with tempfile.TemporaryDirectory(prefix="tts-platform-release-") as temp_dir:
        resolved_package_out_path = (
            package_out_path.expanduser().resolve()
            if package_out_path is not None
            else Path(temp_dir) / "tts-platform-prototype.zip"
        )
        resolved_windows_bundle_out_path = (
            windows_bundle_out_path.expanduser().resolve()
            if windows_bundle_out_path is not None
            else Path(temp_dir) / "tts-platform-local-reader.zip"
        )
        return _run_release_checks_with_package_path(
            python_executable=python_executable,
            package_out_path=resolved_package_out_path,
            windows_bundle_out_path=resolved_windows_bundle_out_path,
            live_smoke=live_smoke,
            base_url=base_url,
            token=token,
            token_file=token_file,
            voice=voice,
            smoke_text=smoke_text,
            stream_text=stream_text,
            stream_text_file=stream_text_file,
            stream_text_repeat=stream_text_repeat,
            min_stream_text_chunks=min_stream_text_chunks,
            node_executable=node_executable,
            require_js_syntax=require_js_syntax,
        )


def _run_release_checks_with_package_path(
    *,
    python_executable: str,
    package_out_path: Path,
    windows_bundle_out_path: Path,
    live_smoke: bool,
    base_url: str,
    token: str | None,
    token_file: str | None,
    voice: str | None,
    smoke_text: str | None,
    stream_text: str | None,
    stream_text_file: str | None,
    stream_text_repeat: int,
    min_stream_text_chunks: int,
    node_executable: str | None,
    require_js_syntax: bool,
) -> dict[str, object]:
    child_env = _build_release_env(node_executable=node_executable)
    checks = [
        ("ruff", [python_executable, "-m", "ruff", "check", "."]),
        ("pytest", [python_executable, "-m", "pytest", "-q"]),
        (
            "security_defaults",
            [python_executable, "scripts/check_security_defaults.py"],
        ),
        (
            "v1_readiness",
            [python_executable, "scripts/check_v1_readiness.py"],
        ),
        (
            "local_service_bootstrap",
            [python_executable, "scripts/check_local_service_bootstrap.py"],
        ),
        (
            "model_management_flow",
            [python_executable, "scripts/check_model_management_flow.py"],
        ),
        (
            "extension",
            _build_extension_check_command(
                python_executable=python_executable,
                node_executable=node_executable,
                require_js_syntax=require_js_syntax,
            ),
        ),
        (
            "extension_onboarding",
            [python_executable, "scripts/check_extension_onboarding.py"],
        ),
        (
            "extension_reader_flow",
            [python_executable, "scripts/check_extension_reader_flow.py"],
        ),
        (
            "chrome_extension_smoke",
            [python_executable, "scripts/check_chrome_extension_smoke.py"],
        ),
        (
            "extension_package",
            [
                python_executable,
                "scripts/package_extension.py",
                "--out",
                str(package_out_path),
            ],
        ),
        (
            "windows_bundle",
            [
                python_executable,
                "scripts/package_windows_bundle.py",
                "--out",
                str(windows_bundle_out_path),
            ],
        ),
        (
            "windows_bundle_bootstrap",
            [
                python_executable,
                "scripts/check_windows_bundle_bootstrap.py",
                "--bundle",
                str(windows_bundle_out_path),
            ],
        ),
        (
            "windows_launchers",
            [
                python_executable,
                "scripts/check_windows_launchers.py",
                "--bundle",
                str(windows_bundle_out_path),
            ],
        ),
        (
            "windows_bundle_install",
            [
                python_executable,
                "scripts/check_windows_bundle_install.py",
                "--bundle",
                str(windows_bundle_out_path),
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
                    smoke_text=smoke_text,
                    stream_text=stream_text,
                    stream_text_file=stream_text_file,
                    stream_text_repeat=stream_text_repeat,
                    min_stream_text_chunks=min_stream_text_chunks,
                ),
            )
        )
    completed: list[dict[str, object]] = []
    for name, command in checks:
        print(f"[release-check] {name}", file=sys.stderr)
        if child_env is None:
            subprocess.run(command, cwd=REPO_ROOT, check=True)
        else:
            subprocess.run(command, cwd=REPO_ROOT, check=True, env=child_env)
        completed.append({"name": name, "command": _redact_command(command)})

    return {
        "checks": completed,
        "package_path": str(package_out_path),
        "windows_bundle_path": str(windows_bundle_out_path),
    }


def _build_release_env(*, node_executable: str | None) -> dict[str, str] | None:
    if not node_executable:
        return None
    env = os.environ.copy()
    env["TTS_PLATFORM_NODE"] = str(Path(node_executable).expanduser().resolve())
    return env


def _build_extension_check_command(
    *,
    python_executable: str,
    node_executable: str | None,
    require_js_syntax: bool,
) -> list[str]:
    command = [python_executable, "scripts/check_extension.py"]
    if node_executable:
        command.extend(["--node-executable", str(Path(node_executable).expanduser().resolve())])
    if require_js_syntax:
        command.append("--require-js-syntax")
    return command


def _build_live_smoke_command(
    *,
    python_executable: str,
    base_url: str,
    token: str | None,
    token_file: str | None,
    voice: str | None,
    smoke_text: str | None,
    stream_text: str | None,
    stream_text_file: str | None,
    stream_text_repeat: int,
    min_stream_text_chunks: int,
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
    if smoke_text:
        command.extend(["--text", smoke_text])
    if stream_text:
        command.extend(["--stream-text", stream_text])
    if stream_text_file:
        command.extend(["--stream-text-file", stream_text_file])
    if stream_text_repeat != 1:
        command.extend(["--stream-text-repeat", str(stream_text_repeat)])
    if min_stream_text_chunks != 1:
        command.extend(["--min-stream-text-chunks", str(min_stream_text_chunks)])
    return command


def _redact_command(command: list[str]) -> list[str]:
    redacted = list(command)
    for index, value in enumerate(redacted[:-1]):
        if value == "--token":
            redacted[index + 1] = "<redacted>"
        if value in {"--text", "--stream-text"}:
            redacted[index + 1] = "<text-redacted>"
    return redacted


if __name__ == "__main__":
    main()
