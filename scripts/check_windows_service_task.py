from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"

for source_path in (SERVICE_SRC, CORE_SRC):
    sys.path.insert(0, str(source_path))

from tts_service import cli  # noqa: E402


class WindowsServiceTaskCheckError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_windows_service_task")
    parser.parse_args(argv)

    try:
        summary = check_windows_service_task(repo_root=REPO_ROOT)
    except WindowsServiceTaskCheckError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_windows_service_task(*, repo_root: Path) -> dict[str, object]:
    resolved_repo_root = repo_root.expanduser().resolve()
    launcher_summary = _verify_scheduled_launcher(resolved_repo_root)
    cli_summary = _verify_cli_contract(resolved_repo_root)
    return {
        "repo_root": str(resolved_repo_root),
        "scheduled_launcher": launcher_summary,
        "cli_contract": cli_summary,
    }


def _verify_scheduled_launcher(repo_root: Path) -> dict[str, object]:
    launcher = repo_root / "scripts" / "windows" / "run_scheduled_service.ps1"
    if not launcher.is_file():
        raise WindowsServiceTaskCheckError(f"Missing scheduled launcher: {launcher}")
    script = launcher.read_text(encoding="utf-8")
    required_fragments = [
        "logs\\tts-service.log",
        "run_service.ps1",
        "*>> $LogPath",
        "-HostOverride",
        "-AllowNonLocalHost",
        "Starting TTS Platform local reader service.",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in script]
    if missing:
        raise WindowsServiceTaskCheckError(
            "Scheduled launcher is missing required fragments: " + ", ".join(missing)
        )
    return {
        "path": str(launcher),
        "log_default": "logs\\tts-service.log",
        "forwards_run_service": True,
        "captures_all_streams": True,
    }


def _verify_cli_contract(repo_root: Path) -> dict[str, object]:
    calls: list[list[str]] = []

    def fake_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="SUCCESS: synthetic scheduler check",
            stderr="",
        )

    payload = cli._install_service_task(
        repo_root=repo_root,
        task_name=cli.DEFAULT_SERVICE_TASK_NAME,
        log_path=Path(cli.DEFAULT_SERVICE_LOG_PATH),
        host="127.0.0.1",
        port=7777,
        allow_non_local_host=False,
        skip_setup=True,
        runner=fake_runner,
        scheduler_executable="schtasks.exe",
        powershell_executable=(
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        ),
    )
    action = str(payload["action"])
    _require_action_fragment(action, "-WindowStyle Hidden")
    _require_action_fragment(action, "run_scheduled_service.ps1")
    _require_action_fragment(action, "-LogPath")
    _require_action_fragment(action, "logs\\tts-service.log")
    _require_action_fragment(action, "-HostOverride 127.0.0.1")
    _require_action_fragment(action, "-Port 7777")

    status = cli._service_task_status(
        task_name=cli.DEFAULT_SERVICE_TASK_NAME,
        runner=lambda command: subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    "TaskName: \\TTS Platform Local Reader",
                    "Status: Ready",
                    "Last Result: 0",
                    f"Task To Run: {action}",
                ]
            ),
            stderr="",
        ),
        scheduler_executable="schtasks.exe",
    )
    if status.get("installed") is not True or status.get("status") != "Ready":
        raise WindowsServiceTaskCheckError("Synthetic service-status parsing failed.")

    expected_create = [
        "schtasks.exe",
        "/Create",
        "/TN",
        cli.DEFAULT_SERVICE_TASK_NAME,
        "/SC",
        "ONLOGON",
        "/RL",
        "LIMITED",
        "/TR",
        action,
        "/F",
    ]
    if calls != [expected_create]:
        raise WindowsServiceTaskCheckError("service-install did not build expected task command.")

    return {
        "task_name": payload["task_name"],
        "scope": payload["scope"],
        "run_at": payload["run_at"],
        "create_command": calls[0],
        "status_parser": status["status"],
    }


def _require_action_fragment(action: str, fragment: str) -> None:
    if fragment not in action:
        raise WindowsServiceTaskCheckError(
            f"Task action is missing required fragment {fragment!r}: {action}"
        )


if __name__ == "__main__":
    main()
