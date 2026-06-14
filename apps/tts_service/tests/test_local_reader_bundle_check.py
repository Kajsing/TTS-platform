import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_local_reader_bundle.py"


def test_local_reader_bundle_check_runs_bundle_compatible_commands(
    monkeypatch,
) -> None:
    check_module = _load_check_module()
    calls: list[tuple[list[str], dict[str, str] | None]] = []

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

    monkeypatch.setattr(check_module.subprocess, "run", fake_run)

    summary = check_module.check_local_reader_bundle(python_executable="python-test")

    assert [check["name"] for check in summary["checks"]] == [
        "local_service_bootstrap",
        "model_management_flow",
        "extension",
        "extension_onboarding",
        "extension_reader_flow",
        "chrome_extension_smoke",
    ]
    assert [call[0] for call in calls] == [
        ["python-test", "scripts/check_local_service_bootstrap.py"],
        ["python-test", "scripts/check_model_management_flow.py"],
        ["python-test", "scripts/check_extension.py"],
        ["python-test", "scripts/check_extension_onboarding.py"],
        ["python-test", "scripts/check_extension_reader_flow.py"],
        ["python-test", "scripts/check_chrome_extension_smoke.py"],
    ]
    assert all(env is None for _, env in calls)


def test_local_reader_bundle_check_forwards_strict_extension_flags(
    tmp_path: Path,
    monkeypatch,
) -> None:
    check_module = _load_check_module()
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
        calls.append((command, env))

    monkeypatch.setattr(check_module.subprocess, "run", fake_run)

    check_module.check_local_reader_bundle(
        python_executable="python-test",
        node_executable=str(node_path),
        require_js_syntax=True,
        browser_executable=str(browser_path),
        require_browser=True,
        headed=True,
    )

    assert calls[2][0] == [
        "python-test",
        "scripts/check_extension.py",
        "--node-executable",
        str(node_path.resolve()),
        "--require-js-syntax",
    ]
    assert calls[2][1] is not None
    assert calls[2][1]["TTS_PLATFORM_NODE"] == str(node_path.resolve())
    assert calls[5][0] == [
        "python-test",
        "scripts/check_chrome_extension_smoke.py",
        "--browser-executable",
        str(browser_path.resolve()),
        "--require-browser",
        "--headed",
    ]
    assert calls[5][1] is not None
    assert calls[5][1]["TTS_PLATFORM_NODE"] == str(node_path.resolve())


def test_local_reader_bundle_check_can_include_real_voice_demo(
    tmp_path: Path,
    monkeypatch,
) -> None:
    check_module = _load_check_module()
    calls: list[list[str]] = []
    demo_root = tmp_path / "real-demo"
    demo_out = tmp_path / "lessac-demo.wav"

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        check: bool,
        env: dict[str, str] | None = None,
    ) -> None:
        calls.append(command)

    monkeypatch.setattr(check_module.subprocess, "run", fake_run)

    summary = check_module.check_local_reader_bundle(
        python_executable="python-test",
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


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_local_reader_bundle",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
