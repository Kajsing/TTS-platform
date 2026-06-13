from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_windows_service_launcher_uses_module_cli_setup_and_serve() -> None:
    launcher = REPO_ROOT / "scripts" / "windows" / "run_service.ps1"
    script = launcher.read_text(encoding="utf-8")

    assert '"apps\\tts_service\\src"' in script
    assert '"packages\\tts_core\\src"' in script
    assert '"-m", "tts_service.cli"' in script
    assert '"setup-local"' in script
    assert '"serve"' in script
    assert '"--repo-root", $RepoRoot' in script
    assert '"--allow-non-local-host"' in script


def test_windows_cmd_launcher_delegates_to_powershell_launcher() -> None:
    launcher = REPO_ROOT / "scripts" / "windows" / "run_service.cmd"
    script = launcher.read_text(encoding="utf-8")

    assert "powershell.exe" in script
    assert "-ExecutionPolicy Bypass" in script
    assert "run_service.ps1" in script
    assert "%*" in script
