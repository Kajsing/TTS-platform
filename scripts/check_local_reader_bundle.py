from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_local_reader_bundle")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--node-executable", default=None)
    parser.add_argument(
        "--require-js-syntax",
        action="store_true",
        help="Fail extension validation when JavaScript syntax checks cannot run.",
    )
    parser.add_argument("--browser-executable", default=None)
    parser.add_argument("--require-browser", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--real-voice-demo",
        action="store_true",
        help="Also run scripts/demo_real_voice.py as an explicit acoustic-output gate.",
    )
    parser.add_argument(
        "--install-real-runtime",
        action="store_true",
        help="With --real-voice-demo, install .[real] before demo setup/model checks.",
    )
    parser.add_argument("--real-voice-demo-root", default=None)
    parser.add_argument("--real-voice-demo-out", default=None)
    args = parser.parse_args(argv)

    try:
        summary = check_local_reader_bundle(
            python_executable=args.python_executable,
            node_executable=args.node_executable,
            require_js_syntax=args.require_js_syntax,
            browser_executable=args.browser_executable,
            require_browser=args.require_browser,
            headed=args.headed,
            real_voice_demo=args.real_voice_demo,
            install_real_runtime=args.install_real_runtime,
            real_voice_demo_root=(
                Path(args.real_voice_demo_root) if args.real_voice_demo_root else None
            ),
            real_voice_demo_out=(
                Path(args.real_voice_demo_out) if args.real_voice_demo_out else None
            ),
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_local_reader_bundle(
    *,
    python_executable: str,
    node_executable: str | None = None,
    require_js_syntax: bool = False,
    browser_executable: str | None = None,
    require_browser: bool = False,
    headed: bool = False,
    real_voice_demo: bool = False,
    install_real_runtime: bool = False,
    real_voice_demo_root: Path | None = None,
    real_voice_demo_out: Path | None = None,
) -> dict[str, object]:
    checks = [
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
            _build_chrome_extension_smoke_command(
                python_executable=python_executable,
                browser_executable=browser_executable,
                require_browser=require_browser,
                headed=headed,
            ),
        ),
    ]
    if real_voice_demo:
        checks.append(
            (
                "real_voice_demo",
                _build_real_voice_demo_command(
                    python_executable=python_executable,
                    install_real_runtime=install_real_runtime,
                    demo_root=real_voice_demo_root,
                    out_path=real_voice_demo_out,
                ),
            )
        )

    env = _build_env(node_executable=node_executable)
    completed: list[dict[str, object]] = []
    for name, command in checks:
        print(f"[local-reader-bundle-check] {name}", file=sys.stderr)
        subprocess.run(command, cwd=REPO_ROOT, check=True, env=env)
        completed.append({"name": name, "command": command})

    return {"checks": completed}


def _build_env(*, node_executable: str | None) -> dict[str, str] | None:
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
        command.extend(
            ["--node-executable", str(Path(node_executable).expanduser().resolve())]
        )
    if require_js_syntax:
        command.append("--require-js-syntax")
    return command


def _build_chrome_extension_smoke_command(
    *,
    python_executable: str,
    browser_executable: str | None,
    require_browser: bool,
    headed: bool,
) -> list[str]:
    command = [python_executable, "scripts/check_chrome_extension_smoke.py"]
    if browser_executable:
        command.extend(
            [
                "--browser-executable",
                str(Path(browser_executable).expanduser().resolve()),
            ]
        )
    if require_browser:
        command.append("--require-browser")
    if headed:
        command.append("--headed")
    return command


def _build_real_voice_demo_command(
    *,
    python_executable: str,
    install_real_runtime: bool,
    demo_root: Path | None,
    out_path: Path | None,
) -> list[str]:
    command = [
        python_executable,
        "scripts/demo_real_voice.py",
        "--python-executable",
        python_executable,
    ]
    if install_real_runtime:
        command.append("--install-real-runtime")
    if demo_root is not None:
        command.extend(["--demo-root", str(demo_root.expanduser().resolve())])
    if out_path is not None:
        command.extend(["--out", str(out_path.expanduser().resolve())])
    return command


if __name__ == "__main__":
    main()
