from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_windows_launchers.py"


def test_windows_launchers_check_orchestrates_available_setup_only_launchers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_text("placeholder", encoding="utf-8")
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(check_module, "_find_powershell_executable", lambda: "powershell-test")
    monkeypatch.setattr(check_module, "_find_cmd_executable", lambda: "cmd-test")

    def fake_check_launcher_setup_only(
        *,
        bundle_path: Path,
        launcher_name: str,
        command_builder,
        python_executable: str,
        timeout_s: float,
    ) -> dict[str, object]:
        command = command_builder(Path("C:/bundle/tts-platform"))
        calls.append((launcher_name, command))
        assert python_executable == "python-test"
        assert timeout_s == 12.5
        return {
            "name": launcher_name,
            "setup_only": True,
            "config_created": True,
            "token_created": True,
            "base_url": "http://127.0.0.1:7777",
            "default_voice": "sherpa-en-debug",
            "manifest_default_voice": True,
        }

    monkeypatch.setattr(
        check_module,
        "_check_launcher_setup_only",
        fake_check_launcher_setup_only,
    )

    summary = check_module.check_windows_launchers(
        bundle_path=bundle_path,
        python_executable="python-test",
        command_timeout_s=12.5,
    )

    fake_bundle_root = Path("C:/bundle/tts-platform")
    assert [result["name"] for result in summary["launchers"]] == ["powershell", "cmd"]
    assert summary["skipped"] == []
    assert calls == [
        (
            "powershell",
            [
                "powershell-test",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(fake_bundle_root / "scripts" / "windows" / "run_service.ps1"),
                "-SetupOnly",
            ],
        ),
        (
            "cmd",
            [
                "cmd-test",
                "/c",
                str(fake_bundle_root / "scripts" / "windows" / "run_service.cmd"),
                "-SetupOnly",
            ],
        ),
    ]


def test_run_launcher_command_uses_python_override_and_parses_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    payload = {
        "config_created": True,
        "token_created": True,
    }

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["launcher-test", "-SetupOnly"]
        assert cwd == tmp_path
        assert env["TTS_PLATFORM_PYTHON"] == "python-test"
        assert check is True
        assert capture_output is True
        assert text is True
        assert timeout == 3.0
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(check_module.subprocess, "run", fake_run)

    assert check_module._run_launcher_command(
        command=["launcher-test", "-SetupOnly"],
        bundle_root=tmp_path,
        python_executable="python-test",
        timeout_s=3.0,
    ) == payload


def test_windows_launchers_check_rejects_invalid_timeout(tmp_path: Path) -> None:
    check_module = _load_check_module()
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_text("placeholder", encoding="utf-8")

    with pytest.raises(check_module.WindowsLauncherCheckError, match="command-timeout-s"):
        check_module.check_windows_launchers(
            bundle_path=bundle_path,
            python_executable="python-test",
            command_timeout_s=0,
        )


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_windows_launchers",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
