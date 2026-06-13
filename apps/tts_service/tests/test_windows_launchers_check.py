from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_windows_launchers.py"


def test_windows_launchers_check_orchestrates_available_launchers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_text("placeholder", encoding="utf-8")
    calls: list[tuple[str, list[str]]] = []
    service_calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(check_module.os, "name", "nt")
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
            "catalog_single_installable_model": "vits-piper-en_US-lessac-medium",
            "next_steps": [
                "tts model-install vits-piper-en_US-lessac-medium --activate",
                "tts model-check",
                "tts serve",
            ],
        }

    def fake_check_launcher_service(
        *,
        bundle_path: Path,
        launcher_name: str,
        command_builder,
        python_executable: str,
        startup_timeout_s: float,
        command_timeout_s: float,
        stream_text_repeat: int,
        min_stream_text_chunks: int,
    ) -> dict[str, object]:
        command = command_builder(Path("C:/bundle/tts-platform"))
        service_calls.append((launcher_name, command))
        assert python_executable == "python-test"
        assert startup_timeout_s == 4.5
        assert command_timeout_s == 12.5
        assert stream_text_repeat == 7
        assert min_stream_text_chunks == 3
        return {
            "name": launcher_name,
            "foreground_service": True,
            "base_url": "http://127.0.0.1:7778",
            "smoke": {"health": {"status": "ok"}},
        }

    monkeypatch.setattr(
        check_module,
        "_check_launcher_setup_only",
        fake_check_launcher_setup_only,
    )
    monkeypatch.setattr(
        check_module,
        "_check_launcher_service",
        fake_check_launcher_service,
    )

    summary = check_module.check_windows_launchers(
        bundle_path=bundle_path,
        python_executable="python-test",
        startup_timeout_s=4.5,
        command_timeout_s=12.5,
        stream_text_repeat=7,
        min_stream_text_chunks=3,
    )

    fake_bundle_root = Path("C:/bundle/tts-platform")
    assert [result["name"] for result in summary["launchers"]] == ["powershell", "cmd"]
    assert [result["name"] for result in summary["service_smoke"]] == ["powershell", "cmd"]
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
    assert service_calls == [
        (
            "powershell",
            [
                "powershell-test",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(fake_bundle_root / "scripts" / "windows" / "run_service.ps1"),
            ],
        ),
        (
            "cmd",
            [
                "cmd-test",
                "/c",
                str(fake_bundle_root / "scripts" / "windows" / "run_service.cmd"),
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


def test_check_launcher_setup_only_exposes_setup_next_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_text("placeholder", encoding="utf-8")

    def fake_extract_bundle(*, bundle_path: Path, extract_root: Path) -> None:
        (extract_root / check_module.BUNDLE_ROOT).mkdir()

    setup_payload = {
        "config_created": True,
        "token_created": True,
        "service": {"base_url": "http://127.0.0.1:7777"},
        "default_voice": "sherpa-en-debug",
        "manifest": {"default_voice_in_manifest": True},
        "catalog": {
            "single_installable_model_id": "vits-piper-en_US-lessac-medium",
        },
        "next_steps": [
            "tts model-install vits-piper-en_US-lessac-medium --activate",
            "tts model-check",
            "tts serve",
        ],
    }

    monkeypatch.setattr(check_module, "_extract_bundle", fake_extract_bundle)
    monkeypatch.setattr(check_module, "_run_launcher_command", lambda **kwargs: setup_payload)
    monkeypatch.setattr(
        check_module.check_windows_bundle_bootstrap,
        "_assert_setup_payload",
        lambda **kwargs: None,
    )

    summary = check_module._check_launcher_setup_only(
        bundle_path=bundle_path,
        launcher_name="powershell",
        command_builder=lambda bundle_root: ["launcher", str(bundle_root), "-SetupOnly"],
        python_executable="python-test",
        timeout_s=3.0,
    )

    assert (
        summary["catalog_single_installable_model"]
        == "vits-piper-en_US-lessac-medium"
    )
    assert summary["next_steps"] == [
        "tts model-install vits-piper-en_US-lessac-medium --activate",
        "tts model-check",
        "tts serve",
    ]


def test_check_launcher_service_runs_smoke_and_stops_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_text("placeholder", encoding="utf-8")
    calls: list[str] = []

    class FakeProcess:
        pass

    def fake_extract_bundle(*, bundle_path: Path, extract_root: Path) -> None:
        calls.append("extract")
        bundle_root = extract_root / check_module.BUNDLE_ROOT
        (bundle_root / "config").mkdir(parents=True)
        (bundle_root / "config" / "token.txt").write_text("token", encoding="utf-8")

    def fake_start_launcher_process(
        *,
        command: list[str],
        bundle_root: Path,
        env: dict[str, str],
    ) -> FakeProcess:
        calls.append("start")
        assert command[-4:] == ["-HostOverride", "127.0.0.1", "-Port", "43210"]
        assert env["TTS_PLATFORM_PYTHON"] == "python-test"
        return FakeProcess()

    def fake_wait_for_health(
        *,
        base_url: str,
        process: FakeProcess,
        timeout_s: float,
    ) -> None:
        calls.append("health")
        assert base_url == "http://127.0.0.1:43210"
        assert timeout_s == 5.0

    def fake_run_json_command(
        command: list[str],
        *,
        env: dict[str, str],
        timeout_s: float,
    ) -> dict[str, object]:
        calls.append("smoke")
        assert command[:4] == [
            "python-test",
            "scripts/smoke_service.py",
            "--base-url",
            "http://127.0.0.1:43210",
        ]
        assert "--token-file" in command
        assert command[-4:] == [
            "--stream-text-repeat",
            "9",
            "--min-stream-text-chunks",
            "4",
        ]
        assert timeout_s == 6.0
        assert Path(command[command.index("--token-file") + 1]).is_file()
        return {
            "health": {"status": "ok"},
            "voices": {"count": 1},
            "input": {"stream_text_chars": 100},
            "stream": {"frames": 2, "marks": 2, "text_chunk_count": 4},
            "job": {"status": "completed"},
        }

    monkeypatch.setattr(check_module, "_extract_bundle", fake_extract_bundle)
    monkeypatch.setattr(
        check_module.check_local_service_bootstrap,
        "_reserve_loopback_port",
        lambda: 43210,
    )
    monkeypatch.setattr(check_module, "_start_launcher_process", fake_start_launcher_process)
    monkeypatch.setattr(
        check_module.check_local_service_bootstrap,
        "_wait_for_health",
        fake_wait_for_health,
    )
    monkeypatch.setattr(
        check_module.check_local_service_bootstrap,
        "_run_json_command",
        fake_run_json_command,
    )
    monkeypatch.setattr(
        check_module.check_local_service_bootstrap,
        "_source_env",
        lambda: {},
    )
    monkeypatch.setattr(
        check_module,
        "_stop_launcher_process",
        lambda process: calls.append("stop"),
    )

    summary = check_module._check_launcher_service(
        bundle_path=bundle_path,
        launcher_name="powershell",
        command_builder=lambda bundle_root: ["launcher", str(bundle_root)],
        python_executable="python-test",
        startup_timeout_s=5.0,
        command_timeout_s=6.0,
        stream_text_repeat=9,
        min_stream_text_chunks=4,
    )

    assert calls == ["extract", "start", "health", "smoke", "stop"]
    assert summary["name"] == "powershell"
    assert summary["foreground_service"] is True
    assert summary["base_url"] == "http://127.0.0.1:43210"
    assert summary["smoke"]["stream"]["text_chunk_count"] == 4


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

    with pytest.raises(check_module.WindowsLauncherCheckError, match="startup-timeout-s"):
        check_module.check_windows_launchers(
            bundle_path=bundle_path,
            python_executable="python-test",
            startup_timeout_s=0,
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
