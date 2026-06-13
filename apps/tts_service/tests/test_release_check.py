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

    summary = release_module.run_release_checks(
        python_executable="python-test",
        package_out_path=package_out_path,
    )

    assert [check["name"] for check in summary["checks"]] == [
        "ruff",
        "pytest",
        "extension",
        "extension_package",
    ]
    assert summary["package_path"] == str(package_out_path.resolve())
    assert calls == [
        (["python-test", "-m", "ruff", "check", "."], REPO_ROOT, True),
        (["python-test", "-m", "pytest", "-q"], REPO_ROOT, True),
        (["python-test", "scripts/check_extension.py"], REPO_ROOT, True),
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
