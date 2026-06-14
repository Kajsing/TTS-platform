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


def test_windows_install_launcher_bootstraps_venv_package_and_setup() -> None:
    launcher = REPO_ROOT / "scripts" / "windows" / "install_local.ps1"
    script = launcher.read_text(encoding="utf-8")

    assert "TTS_PLATFORM_PYTHON" in script
    assert "InstallRealRuntime" in script
    assert "NoDependencies" in script
    assert '"venv", "--system-site-packages"' in script
    assert '"pip", "install"' in script
    assert '("-m", "pip", "install", "--no-build-isolation")' in script
    assert '$PackageInstallArgs += "--no-deps"' in script
    assert '$PackageInstallArgs += @("-e", $RepoRoot)' in script
    assert '"--no-build-isolation", "-e", "$RepoRoot[real]"' in script
    assert "dependencies_installed" in script
    assert "real_runtime_installed" in script
    assert "tts_service.cli setup-local" in script
    assert "ConvertTo-Json" in script


def test_windows_cmd_launcher_delegates_to_powershell_launcher() -> None:
    launcher = REPO_ROOT / "scripts" / "windows" / "run_service.cmd"
    script = launcher.read_text(encoding="utf-8")
    trusted_powershell = (
        "POWERSHELL_EXE=%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    )

    assert trusted_powershell in script
    assert '"%POWERSHELL_EXE%" -NoProfile' in script
    assert "Trusted Windows PowerShell executable not found" in script
    assert "powershell.exe -NoProfile" not in script
    assert "-ExecutionPolicy Bypass" in script
    assert "run_service.ps1" in script
    assert "%*" in script


def test_windows_scheduled_service_launcher_wraps_foreground_launcher_with_logging() -> None:
    launcher = REPO_ROOT / "scripts" / "windows" / "run_scheduled_service.ps1"
    script = launcher.read_text(encoding="utf-8")

    assert "logs\\tts-service.log" in script
    assert "run_service.ps1" in script
    assert "*>> $LogPath" in script
    assert "Starting TTS Platform local reader service." in script
    assert "-HostOverride" in script
    assert "-AllowNonLocalHost" in script


def test_windows_install_cmd_launcher_delegates_to_powershell_installer() -> None:
    launcher = REPO_ROOT / "scripts" / "windows" / "install_local.cmd"
    script = launcher.read_text(encoding="utf-8")
    trusted_powershell = (
        "POWERSHELL_EXE=%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    )

    assert trusted_powershell in script
    assert '"%POWERSHELL_EXE%" -NoProfile' in script
    assert "Trusted Windows PowerShell executable not found" in script
    assert "powershell.exe -NoProfile" not in script
    assert "-ExecutionPolicy Bypass" in script
    assert "install_local.ps1" in script
    assert "%*" in script
