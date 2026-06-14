import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "release_check.py"


def test_release_check_runs_local_release_gate_commands(tmp_path: Path, monkeypatch) -> None:
    release_module = _load_release_check_module()
    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        calls.append((command, cwd, check))

    monkeypatch.setattr(release_module.subprocess, "run", fake_run)
    package_out_path = tmp_path / "extension.zip"
    windows_bundle_out_path = tmp_path / "windows.zip"

    summary = release_module.run_release_checks(
        python_executable="python-test",
        package_out_path=package_out_path,
        windows_bundle_out_path=windows_bundle_out_path,
    )

    assert [check["name"] for check in summary["checks"]] == [
        "ruff",
        "pytest",
        "security_defaults",
        "v1_readiness",
        "local_service_bootstrap",
        "model_management_flow",
        "extension",
        "extension_onboarding",
        "extension_reader_flow",
        "chrome_extension_smoke",
        "extension_package",
        "windows_bundle",
        "windows_bundle_bootstrap",
        "windows_launchers",
        "windows_service_task",
        "windows_bundle_install",
    ]
    assert summary["package_path"] == str(package_out_path.resolve())
    assert summary["windows_bundle_path"] == str(windows_bundle_out_path.resolve())
    assert calls == [
        (["python-test", "-m", "ruff", "check", "."], REPO_ROOT, True),
        (["python-test", "-m", "pytest", "-q"], REPO_ROOT, True),
        (["python-test", "scripts/check_security_defaults.py"], REPO_ROOT, True),
        (["python-test", "scripts/check_v1_readiness.py"], REPO_ROOT, True),
        (["python-test", "scripts/check_local_service_bootstrap.py"], REPO_ROOT, True),
        (["python-test", "scripts/check_model_management_flow.py"], REPO_ROOT, True),
        (["python-test", "scripts/check_extension.py"], REPO_ROOT, True),
        (["python-test", "scripts/check_extension_onboarding.py"], REPO_ROOT, True),
        (["python-test", "scripts/check_extension_reader_flow.py"], REPO_ROOT, True),
        (["python-test", "scripts/check_chrome_extension_smoke.py"], REPO_ROOT, True),
        (
            [
                "python-test",
                "scripts/package_extension.py",
                "--out",
                str(package_out_path.resolve()),
            ],
            REPO_ROOT,
            True,
        ),
        (
            [
                "python-test",
                "scripts/package_windows_bundle.py",
                "--out",
                str(windows_bundle_out_path.resolve()),
            ],
            REPO_ROOT,
            True,
        ),
        (
            [
                "python-test",
                "scripts/check_windows_bundle_bootstrap.py",
                "--bundle",
                str(windows_bundle_out_path.resolve()),
            ],
            REPO_ROOT,
            True,
        ),
        (
            [
                "python-test",
                "scripts/check_windows_launchers.py",
                "--bundle",
                str(windows_bundle_out_path.resolve()),
            ],
            REPO_ROOT,
            True,
        ),
        (
            ["python-test", "scripts/check_windows_service_task.py"],
            REPO_ROOT,
            True,
        ),
        (
            [
                "python-test",
                "scripts/check_windows_bundle_install.py",
                "--bundle",
                str(windows_bundle_out_path.resolve()),
            ],
            REPO_ROOT,
            True,
        ),
    ]


def test_release_check_can_include_optional_live_smoke(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release_module = _load_release_check_module()
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == REPO_ROOT
        assert check is True
        calls.append(command)

    monkeypatch.setattr(release_module.subprocess, "run", fake_run)

    summary = release_module.run_release_checks(
        python_executable="python-test",
        package_out_path=tmp_path / "extension.zip",
        windows_bundle_out_path=tmp_path / "windows.zip",
        live_smoke=True,
        base_url="http://localhost:8888/",
        token_file="config/token.txt",
        voice="voice-a",
        smoke_text="Short contract smoke.",
        stream_text="Long stream text.",
        stream_text_repeat=5,
        min_stream_text_chunks=2,
    )

    assert summary["checks"][-1]["name"] == "live_smoke"
    assert calls[-1] == [
        "python-test",
        "scripts/smoke_service.py",
        "--base-url",
        "http://localhost:8888",
        "--token-file",
        "config/token.txt",
        "--voice",
        "voice-a",
        "--text",
        "Short contract smoke.",
        "--stream-text",
        "Long stream text.",
        "--stream-text-repeat",
        "5",
        "--min-stream-text-chunks",
        "2",
    ]


def test_release_check_can_include_optional_real_voice_demo(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release_module = _load_release_check_module()
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == REPO_ROOT
        assert check is True
        calls.append(command)

    monkeypatch.setattr(release_module.subprocess, "run", fake_run)
    demo_root = tmp_path / "real-demo"
    demo_out = tmp_path / "lessac-demo.wav"

    summary = release_module.run_release_checks(
        python_executable="python-test",
        package_out_path=tmp_path / "extension.zip",
        windows_bundle_out_path=tmp_path / "windows.zip",
        real_voice_demo=True,
        install_real_runtime=True,
        real_voice_demo_root=demo_root,
        real_voice_demo_out=demo_out,
    )

    assert summary["checks"][-1]["name"] == "real_voice_demo"
    assert calls[-1] == [
        "python-test",
        "scripts/demo_real_voice.py",
        "--python-executable",
        "python-test",
        "--install-real-runtime",
        "--demo-root",
        str(demo_root.resolve()),
        "--out",
        str(demo_out.resolve()),
    ]
    assert summary["checks"][-1]["command"] == calls[-1]


def test_release_check_can_require_chrome_browser_smoke(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release_module = _load_release_check_module()
    calls: list[list[str]] = []
    browser_path = tmp_path / "chrome.exe"

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == REPO_ROOT
        assert check is True
        calls.append(command)

    browser_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(release_module.subprocess, "run", fake_run)

    summary = release_module.run_release_checks(
        python_executable="python-test",
        package_out_path=tmp_path / "extension.zip",
        windows_bundle_out_path=tmp_path / "windows.zip",
        browser_executable=str(browser_path),
        require_browser=True,
        headed=True,
    )

    assert calls[9] == [
        "python-test",
        "scripts/check_chrome_extension_smoke.py",
        "--browser-executable",
        str(browser_path.resolve()),
        "--require-browser",
        "--headed",
    ]
    assert summary["checks"][9]["command"] == calls[9]


def test_release_check_can_require_extension_js_syntax(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release_module = _load_release_check_module()
    calls: list[tuple[list[str], dict[str, str] | None]] = []
    node_path = tmp_path / "node.exe"

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        check: bool,
        env: dict[str, str] | None = None,
    ) -> None:
        assert cwd == REPO_ROOT
        assert check is True
        calls.append((command, env))

    monkeypatch.setattr(release_module.subprocess, "run", fake_run)

    summary = release_module.run_release_checks(
        python_executable="python-test",
        package_out_path=tmp_path / "extension.zip",
        windows_bundle_out_path=tmp_path / "windows.zip",
        node_executable=str(node_path),
        require_js_syntax=True,
    )

    extension_call = calls[6]
    assert extension_call[0] == [
        "python-test",
        "scripts/check_extension.py",
        "--node-executable",
        str(node_path.resolve()),
        "--require-js-syntax",
    ]
    assert extension_call[1] is not None
    assert extension_call[1]["TTS_PLATFORM_NODE"] == str(node_path.resolve())
    assert calls[10][0] == [
        "python-test",
        "scripts/package_extension.py",
        "--out",
        str((tmp_path / "extension.zip").resolve()),
        "--node-executable",
        str(node_path.resolve()),
        "--require-js-syntax",
    ]
    assert calls[10][1] is not None
    assert calls[10][1]["TTS_PLATFORM_NODE"] == str(node_path.resolve())
    assert calls[11][0] == [
        "python-test",
        "scripts/package_windows_bundle.py",
        "--out",
        str((tmp_path / "windows.zip").resolve()),
        "--node-executable",
        str(node_path.resolve()),
        "--require-js-syntax",
    ]
    assert calls[11][1] is not None
    assert calls[11][1]["TTS_PLATFORM_NODE"] == str(node_path.resolve())
    assert summary["checks"][6]["command"] == extension_call[0]
    assert summary["checks"][10]["command"] == calls[10][0]
    assert summary["checks"][11]["command"] == calls[11][0]


def test_release_check_can_include_installed_bundle_local_reader_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release_module = _load_release_check_module()
    calls: list[tuple[list[str], dict[str, str] | None]] = []
    node_path = tmp_path / "node.exe"
    browser_path = tmp_path / "chrome.exe"
    node_path.write_text("", encoding="utf-8")
    browser_path.write_text("", encoding="utf-8")

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        check: bool,
        env: dict[str, str] | None = None,
    ) -> None:
        assert cwd == REPO_ROOT
        assert check is True
        calls.append((command, env))

    monkeypatch.setattr(release_module.subprocess, "run", fake_run)
    windows_bundle_out_path = tmp_path / "windows.zip"

    summary = release_module.run_release_checks(
        python_executable="python-test",
        package_out_path=tmp_path / "extension.zip",
        windows_bundle_out_path=windows_bundle_out_path,
        node_executable=str(node_path),
        require_js_syntax=True,
        browser_executable=str(browser_path),
        require_browser=True,
        headed=True,
        windows_bundle_local_reader_check=True,
        windows_bundle_local_reader_timeout_s=321.0,
    )

    expected_command = [
        "python-test",
        "scripts/check_windows_bundle_install.py",
        "--bundle",
        str(windows_bundle_out_path.resolve()),
        "--run-local-reader-check",
        "--local-reader-timeout-s",
        "321.0",
        "--local-reader-node-executable",
        str(node_path.resolve()),
        "--local-reader-require-js-syntax",
        "--local-reader-browser-executable",
        str(browser_path.resolve()),
        "--local-reader-require-browser",
        "--local-reader-headed",
    ]
    assert calls[15][0] == expected_command
    assert calls[15][1] is not None
    assert calls[15][1]["TTS_PLATFORM_NODE"] == str(node_path.resolve())
    assert summary["checks"][15]["name"] == "windows_bundle_install"
    assert summary["checks"][15]["command"] == expected_command


def test_release_check_redacts_inline_live_smoke_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release_module = _load_release_check_module()
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        calls.append(command)

    monkeypatch.setattr(release_module.subprocess, "run", fake_run)

    summary = release_module.run_release_checks(
        python_executable="python-test",
        package_out_path=tmp_path / "extension.zip",
        windows_bundle_out_path=tmp_path / "windows.zip",
        live_smoke=True,
        token="secret-token",
        smoke_text="private smoke text",
        stream_text="private long page text",
    )

    assert "--token" in calls[-1]
    assert "secret-token" in calls[-1]
    assert summary["checks"][-1]["command"] == [
        "python-test",
        "scripts/smoke_service.py",
        "--base-url",
        "http://127.0.0.1:7777",
        "--token",
        "<redacted>",
        "--text",
        "<text-redacted>",
        "--stream-text",
        "<text-redacted>",
    ]


def _load_release_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_release_check",
        RELEASE_CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
