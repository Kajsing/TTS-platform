from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_windows_bundle_install.py"


def test_windows_bundle_install_check_orchestrates_installed_cli_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    calls: list[str] = []
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_text("placeholder", encoding="utf-8")

    def fake_extract_bundle(*, bundle_path: Path, extract_root: Path) -> None:
        calls.append("extract")
        bundle_root = extract_root / "tts-platform"
        (bundle_root / ".venv" / "Scripts").mkdir(parents=True)
        (bundle_root / ".venv" / "Scripts" / "tts.exe").write_text("", encoding="utf-8")
        (bundle_root / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
        (bundle_root / "config").mkdir()
        (bundle_root / "config" / "token.txt").write_text("token", encoding="utf-8")

    def fake_create_venv(*, python_executable: str, venv_dir: Path, timeout_s: float) -> None:
        calls.append("venv")

    def fake_install_build_tooling(
        *,
        venv_python: Path,
        bundle_root: Path,
        timeout_s: float,
    ) -> None:
        calls.append("build-tooling")

    def fake_install_bundle_package(
        *,
        venv_python: Path,
        bundle_root: Path,
        timeout_s: float,
        install_dependencies: bool,
    ) -> None:
        assert install_dependencies is True
        calls.append("install")

    def fake_run_json_command(
        command: list[str],
        *,
        cwd: Path,
        timeout_s: float,
        env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        if command[1] == "setup-local":
            calls.append("setup")
            return {
                "config_created": True,
                "token_created": True,
                "token_file": str(cwd / "config" / "token.txt"),
                "default_voice": "sherpa-en-debug",
                "manifest": {"default_voice_in_manifest": True},
                "catalog": {
                    "exists": True,
                    "single_installable_model_id": "vits-piper-en_US-lessac-medium",
                },
                "next_steps": [
                    "tts model-install vits-piper-en_US-lessac-medium --activate",
                    "tts model-check",
                    "tts serve",
                ],
            }
        calls.append("smoke")
        return {
            "health": {"status": "ok"},
            "voice": "sherpa-en-debug",
            "voices": {"count": 1},
            "http": {"bytes": 10},
            "stream": {"frames": 2},
            "job": {"status": "completed"},
        }

    class FakeProcess:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            calls.append("terminate")

        def communicate(self, timeout: float) -> tuple[str, str]:
            return "", ""

    monkeypatch.setattr(check_module, "_extract_bundle", fake_extract_bundle)
    monkeypatch.setattr(check_module, "_create_venv", fake_create_venv)
    monkeypatch.setattr(check_module, "_install_build_tooling", fake_install_build_tooling)
    monkeypatch.setattr(check_module, "_install_bundle_package", fake_install_bundle_package)
    monkeypatch.setattr(check_module, "_run_json_command", fake_run_json_command)
    monkeypatch.setattr(check_module, "_wait_for_health", lambda **kwargs: calls.append("health"))
    monkeypatch.setattr(check_module, "_reserve_loopback_port", lambda: 7778)
    monkeypatch.setattr(check_module.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    summary = check_module.check_windows_bundle_install(
        bundle_path=bundle_path,
        python_executable="python-test",
    )

    assert calls == [
        "extract",
        "venv",
        "build-tooling",
        "install",
        "setup",
        "health",
        "smoke",
        "terminate",
    ]
    assert summary["venv"] == {
        "created": True,
        "system_site_packages": True,
        "build_tooling_installed": True,
        "dependencies_installed": True,
        "editable_install": True,
        "real_runtime_installed": False,
        "installer_script": False,
        "entrypoint": ".venv\\Scripts\\tts.exe",
    }
    assert summary["setup"]["config_created"] is True
    assert (
        summary["setup"]["catalog_single_installable_model"]
        == "vits-piper-en_US-lessac-medium"
    )
    assert summary["setup"]["next_steps"][0] == (
        "tts model-install vits-piper-en_US-lessac-medium --activate"
    )
    assert "tts model-check" in summary["setup"]["next_steps"]
    assert "tts serve" in summary["setup"]["next_steps"]
    assert summary["service"]["job_status"] == "completed"


def test_windows_bundle_install_check_uses_installer_script_when_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    calls: list[str] = []
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_text("placeholder", encoding="utf-8")

    def fake_extract_bundle(*, bundle_path: Path, extract_root: Path) -> None:
        calls.append("extract")
        bundle_root = extract_root / "tts-platform"
        (bundle_root / ".venv" / "Scripts").mkdir(parents=True)
        (bundle_root / ".venv" / "Scripts" / "tts.exe").write_text("", encoding="utf-8")
        (bundle_root / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
        (bundle_root / "config").mkdir()
        (bundle_root / "config" / "token.txt").write_text("token", encoding="utf-8")

    def fake_run_windows_install_script(
        *,
        python_executable: str,
        bundle_root: Path,
        timeout_s: float,
        install_real_runtime: bool,
        install_dependencies: bool,
    ) -> dict[str, object]:
        calls.append("installer")
        assert python_executable == "python-test"
        assert timeout_s == 180.0
        assert install_real_runtime is False
        assert install_dependencies is True
        return {
            "venv_created": True,
            "build_tooling_installed": True,
            "dependencies_installed": True,
            "editable_install": True,
            "real_runtime_installed": False,
            "setup": {
                "config_created": True,
                "token_created": True,
                "token_file": str(bundle_root / "config" / "token.txt"),
                "default_voice": "sherpa-en-debug",
                "manifest": {"default_voice_in_manifest": True},
                "catalog": {
                    "exists": True,
                    "single_installable_model_id": "vits-piper-en_US-lessac-medium",
                },
                "next_steps": [
                    "tts model-install vits-piper-en_US-lessac-medium --activate",
                    "tts model-check",
                    "tts serve",
                ],
            },
        }

    def fake_run_json_command(
        command: list[str],
        *,
        cwd: Path,
        timeout_s: float,
        env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        calls.append("smoke")
        assert "scripts/smoke_service.py" in command
        return {
            "health": {"status": "ok"},
            "voice": "sherpa-en-debug",
            "voices": {"count": 1},
            "http": {"bytes": 10},
            "stream": {"frames": 2},
            "job": {"status": "completed"},
        }

    class FakeProcess:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            calls.append("terminate")

        def communicate(self, timeout: float) -> tuple[str, str]:
            return "", ""

    monkeypatch.setattr(check_module, "_extract_bundle", fake_extract_bundle)
    monkeypatch.setattr(
        check_module,
        "_run_windows_install_script",
        fake_run_windows_install_script,
    )
    monkeypatch.setattr(check_module, "_run_json_command", fake_run_json_command)
    monkeypatch.setattr(check_module, "_wait_for_health", lambda **kwargs: calls.append("health"))
    monkeypatch.setattr(check_module, "_reserve_loopback_port", lambda: 7778)
    monkeypatch.setattr(check_module.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    summary = check_module.check_windows_bundle_install(
        bundle_path=bundle_path,
        python_executable="python-test",
    )

    assert calls == ["extract", "installer", "health", "smoke", "terminate"]
    assert summary["venv"]["installer_script"] is True
    assert summary["venv"]["dependencies_installed"] is True
    assert summary["venv"]["real_runtime_installed"] is False
    assert summary["setup"]["token_created"] is True
    assert (
        summary["setup"]["catalog_single_installable_model"]
        == "vits-piper-en_US-lessac-medium"
    )
    assert summary["setup"]["next_steps"][0] == (
        "tts model-install vits-piper-en_US-lessac-medium --activate"
    )
    assert "tts model-check" in summary["setup"]["next_steps"]
    assert summary["service"]["job_status"] == "completed"


def test_windows_bundle_install_check_can_run_local_reader_bundle_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    calls: list[str] = []
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_text("placeholder", encoding="utf-8")

    def fake_extract_bundle(*, bundle_path: Path, extract_root: Path) -> None:
        calls.append("extract")
        bundle_root = extract_root / "tts-platform"
        (bundle_root / ".venv" / "Scripts").mkdir(parents=True)
        (bundle_root / ".venv" / "Scripts" / "tts.exe").write_text("", encoding="utf-8")
        (bundle_root / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
        (bundle_root / "config").mkdir()
        (bundle_root / "config" / "token.txt").write_text("token", encoding="utf-8")

    def fake_run_windows_install_script(
        *,
        python_executable: str,
        bundle_root: Path,
        timeout_s: float,
        install_real_runtime: bool,
        install_dependencies: bool,
    ) -> dict[str, object]:
        calls.append("installer")
        return {
            "venv_created": True,
            "build_tooling_installed": True,
            "dependencies_installed": True,
            "editable_install": True,
            "real_runtime_installed": False,
            "setup": {
                "config_created": True,
                "token_created": True,
                "token_file": str(bundle_root / "config" / "token.txt"),
                "default_voice": "sherpa-en-debug",
                "manifest": {"default_voice_in_manifest": True},
                "catalog": {
                    "exists": True,
                    "single_installable_model_id": "vits-piper-en_US-lessac-medium",
                },
                "next_steps": [
                    "tts model-install vits-piper-en_US-lessac-medium --activate",
                    "tts model-check",
                    "tts serve",
                ],
            },
        }

    def fake_run_json_command(
        command: list[str],
        *,
        cwd: Path,
        timeout_s: float,
        env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        calls.append("smoke")
        assert "scripts/smoke_service.py" in command
        return {
            "health": {"status": "ok"},
            "voice": "sherpa-en-debug",
            "voices": {"count": 1},
            "http": {"bytes": 10},
            "stream": {"frames": 2},
            "job": {"status": "completed"},
        }

    def fake_run_local_reader_check(
        *,
        venv_python: Path,
        bundle_root: Path,
        timeout_s: float,
    ) -> dict[str, object]:
        calls.append("local-reader")
        assert venv_python == bundle_root / ".venv" / "Scripts" / "python.exe"
        assert timeout_s == 123.0
        return {
            "checks": [
                {"name": "local_service_bootstrap"},
                {"name": "chrome_extension_smoke"},
            ]
        }

    class FakeProcess:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            calls.append("terminate")

        def communicate(self, timeout: float) -> tuple[str, str]:
            return "", ""

    monkeypatch.setattr(check_module, "_extract_bundle", fake_extract_bundle)
    monkeypatch.setattr(
        check_module,
        "_run_windows_install_script",
        fake_run_windows_install_script,
    )
    monkeypatch.setattr(check_module, "_run_json_command", fake_run_json_command)
    monkeypatch.setattr(
        check_module,
        "_run_local_reader_check",
        fake_run_local_reader_check,
    )
    monkeypatch.setattr(check_module, "_wait_for_health", lambda **kwargs: calls.append("health"))
    monkeypatch.setattr(check_module, "_reserve_loopback_port", lambda: 7778)
    monkeypatch.setattr(check_module.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    summary = check_module.check_windows_bundle_install(
        bundle_path=bundle_path,
        python_executable="python-test",
        local_reader_timeout_s=123.0,
        run_local_reader_check=True,
    )

    assert calls == ["extract", "installer", "health", "smoke", "terminate", "local-reader"]
    assert summary["local_reader_check"] == {
        "performed": True,
        "checks": ["local_service_bootstrap", "chrome_extension_smoke"],
    }


def test_windows_bundle_install_check_rejects_invalid_stream_repeat(tmp_path: Path) -> None:
    check_module = _load_check_module()
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_text("placeholder", encoding="utf-8")

    with pytest.raises(check_module.WindowsBundleInstallError, match="stream-text-repeat"):
        check_module.check_windows_bundle_install(
            bundle_path=bundle_path,
            python_executable="python-test",
            stream_text_repeat=0,
        )


def test_windows_bundle_install_check_rejects_invalid_local_reader_timeout(
    tmp_path: Path,
) -> None:
    check_module = _load_check_module()
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_text("placeholder", encoding="utf-8")

    with pytest.raises(check_module.WindowsBundleInstallError, match="local-reader-timeout"):
        check_module.check_windows_bundle_install(
            bundle_path=bundle_path,
            python_executable="python-test",
            local_reader_timeout_s=0,
        )


def test_windows_bundle_install_check_passes_real_runtime_request_to_installer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    bundle_root = tmp_path / "tts-platform"
    installer_path = bundle_root / "scripts" / "windows" / "install_local.ps1"
    installer_path.parent.mkdir(parents=True)
    installer_path.write_text("", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run_json_command(
        command: list[str],
        *,
        cwd: Path,
        timeout_s: float,
        env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        commands.append(command)
        assert cwd == bundle_root
        assert timeout_s == 42.0
        assert env is not None
        assert env["TTS_PLATFORM_PYTHON"] == "python-test"
        return {"ok": True}

    monkeypatch.setattr(check_module, "_find_powershell_executable", lambda: "powershell-test")
    monkeypatch.setattr(check_module, "_run_json_command", fake_run_json_command)

    payload = check_module._run_windows_install_script(
        python_executable="python-test",
        bundle_root=bundle_root,
        timeout_s=42.0,
        install_real_runtime=True,
        install_dependencies=True,
    )

    assert payload == {"ok": True}
    assert commands == [
        [
            "powershell-test",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(installer_path),
            "-InstallRealRuntime",
        ]
    ]


def test_windows_bundle_install_check_can_skip_dependency_install_for_provisioned_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    bundle_root = tmp_path / "tts-platform"
    installer_path = bundle_root / "scripts" / "windows" / "install_local.ps1"
    installer_path.parent.mkdir(parents=True)
    installer_path.write_text("", encoding="utf-8")
    commands: list[list[str]] = []

    monkeypatch.setattr(check_module, "_find_powershell_executable", lambda: "powershell-test")
    monkeypatch.setattr(
        check_module,
        "_run_json_command",
        lambda command, **_kwargs: commands.append(command) or {"ok": True},
    )

    payload = check_module._run_windows_install_script(
        python_executable="python-test",
        bundle_root=bundle_root,
        timeout_s=42.0,
        install_real_runtime=False,
        install_dependencies=False,
    )

    assert payload == {"ok": True}
    assert commands == [
        [
            "powershell-test",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(installer_path),
            "-NoDependencies",
        ]
    ]


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_windows_bundle_install",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
