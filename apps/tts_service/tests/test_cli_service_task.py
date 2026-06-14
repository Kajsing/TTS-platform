from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from tts_service import cli


def _write_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "[server]",
                'host = "127.0.0.1"',
                "port = 7777",
                "",
                "[auth]",
                "enabled = true",
                'token_file = "./config/token.txt"',
                "",
                "[tts]",
                'default_voice = "sherpa-en-debug"',
                "max_chars_per_request = 4000",
                "max_chars_per_stream = 48000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"version": 1, "voices": []}', encoding="utf-8")


def _write_scheduled_launcher(repo_root: Path) -> None:
    launcher = repo_root / "scripts" / "windows" / "run_scheduled_service.ps1"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("run_service.ps1\n", encoding="utf-8")


def test_service_install_creates_user_logon_task_and_runs_setup(tmp_path: Path) -> None:
    _write_config(tmp_path / "config" / "config.example.toml")
    _write_manifest(tmp_path / "models" / "MANIFEST.json")
    _write_scheduled_launcher(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="SUCCESS: The scheduled task was created.",
            stderr="",
        )

    payload = cli._install_service_task(
        repo_root=tmp_path,
        task_name=" TTS Platform Local Reader ",
        log_path=Path("logs/tts-service.log"),
        host="127.0.0.1",
        port=7788,
        allow_non_local_host=False,
        runner=fake_runner,
        scheduler_executable="schtasks.exe",
        powershell_executable=(
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        ),
    )

    assert payload["scope"] == "user"
    assert payload["task_name"] == "TTS Platform Local Reader"
    assert payload["installed"] is True
    assert payload["setup"]["config_created"] is True
    assert payload["setup"]["token_created"] is True
    assert Path(payload["log_path"]) == (tmp_path / "logs" / "tts-service.log")
    assert calls == [
        [
            "schtasks.exe",
            "/Create",
            "/TN",
            "TTS Platform Local Reader",
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/TR",
            payload["action"],
            "/F",
        ]
    ]
    action = str(payload["action"])
    assert "powershell.exe" in action
    assert "-WindowStyle Hidden" in action
    assert "run_scheduled_service.ps1" in action
    assert "-LogPath" in action
    assert "tts-service.log" in action
    assert "-HostOverride 127.0.0.1" in action
    assert "-Port 7788" in action


def test_service_task_action_defaults_to_trusted_system_powershell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SystemRoot", r"C:\Windows")

    action = cli._build_service_task_action(
        repo_root=tmp_path,
        script_path=tmp_path / "scripts" / "windows" / "run_scheduled_service.ps1",
        log_path=tmp_path / "logs" / "tts-service.log",
        host=None,
        port=None,
        allow_non_local_host=False,
        runner=lambda command: subprocess.CompletedProcess(command, 0),
    )

    assert r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" in action


def test_service_status_parses_existing_task() -> None:
    def fake_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    "TaskName: \\TTS Platform Local Reader",
                    "Status: Ready",
                    "Last Run Time: 6/14/2026 8:00:00 PM",
                    "Last Result: 0",
                    "Next Run Time: N/A",
                    "Task To Run: powershell.exe -File run_scheduled_service.ps1",
                ]
            ),
            stderr="",
        )

    payload = cli._service_task_status(
        task_name="TTS Platform Local Reader",
        runner=fake_runner,
        scheduler_executable="schtasks.exe",
    )

    assert payload["installed"] is True
    assert payload["status"] == "Ready"
    assert payload["last_result"] == "0"
    assert payload["task_to_run"] == "powershell.exe -File run_scheduled_service.ps1"


def test_service_status_and_remove_are_idempotent_when_task_is_missing() -> None:
    def fake_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="ERROR: The system cannot find the file specified.",
        )

    status = cli._service_task_status(
        task_name="TTS Platform Local Reader",
        runner=fake_runner,
        scheduler_executable="schtasks.exe",
    )
    removed = cli._remove_service_task(
        task_name="TTS Platform Local Reader",
        runner=fake_runner,
        scheduler_executable="schtasks.exe",
    )

    assert status == {
        "scope": "user",
        "task_name": "TTS Platform Local Reader",
        "installed": False,
        "status": "not_installed",
        "next_steps": ["tts service-install --user"],
    }
    assert removed["removed"] is False
    assert removed["installed"] is False
    assert removed["status"] == "not_installed"


def test_service_start_and_stop_call_task_scheduler() -> None:
    calls: list[list[str]] = []

    def fake_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="SUCCESS", stderr="")

    started = cli._run_service_task(
        task_name="TTS Platform Local Reader",
        runner=fake_runner,
        scheduler_executable="schtasks.exe",
    )
    stopped = cli._stop_service_task(
        task_name="TTS Platform Local Reader",
        runner=fake_runner,
        scheduler_executable="schtasks.exe",
    )

    assert started["action"] == "start"
    assert stopped["action"] == "stop"
    assert calls == [
        ["schtasks.exe", "/Run", "/TN", "TTS Platform Local Reader"],
        ["schtasks.exe", "/End", "/TN", "TTS Platform Local Reader"],
    ]


def test_service_task_rejects_invalid_name_and_port(tmp_path: Path) -> None:
    _write_scheduled_launcher(tmp_path)
    with pytest.raises(SystemExit, match="Task name"):
        cli._service_task_status(task_name="\n", runner=lambda command: None)
    with pytest.raises(SystemExit, match="port must be positive"):
        cli._build_service_task_action(
            repo_root=tmp_path,
            script_path=tmp_path / "scripts" / "windows" / "run_scheduled_service.ps1",
            log_path=tmp_path / "logs" / "tts-service.log",
            host=None,
            port=0,
            allow_non_local_host=False,
            powershell_executable="powershell.exe",
            runner=lambda command: None,
        )
