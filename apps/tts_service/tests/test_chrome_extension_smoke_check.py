import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_chrome_extension_smoke.py"


def test_chrome_extension_smoke_skips_when_browser_is_missing(tmp_path: Path) -> None:
    check_module = _load_chrome_smoke_module()

    summary = check_module.check_chrome_extension_smoke(
        python_executable="python-test",
        browser_executable=str(tmp_path / "missing-chrome.exe"),
    )

    assert summary == {
        "skipped": True,
        "reason": "Chrome or Edge executable was not found.",
        "browser": None,
    }


def test_chrome_extension_smoke_can_require_browser(tmp_path: Path) -> None:
    check_module = _load_chrome_smoke_module()

    with pytest.raises(
        check_module.ChromeExtensionSmokeError,
        match="Chrome or Edge executable was not found",
    ):
        check_module.check_chrome_extension_smoke(
            python_executable="python-test",
            browser_executable=str(tmp_path / "missing-chrome.exe"),
            require_browser=True,
        )


def test_chrome_extension_smoke_skips_environment_failure_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_chrome_smoke_module()
    browser_path = tmp_path / "chrome.exe"
    browser_path.write_text("", encoding="utf-8")

    def fake_run_browser_smoke(**_kwargs):
        raise check_module.ChromeExtensionSmokeError("service worker did not start")

    monkeypatch.setattr(
        check_module,
        "_validate_extension_static_contract",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(check_module, "_run_browser_smoke", fake_run_browser_smoke)

    summary = check_module.check_chrome_extension_smoke(
        python_executable="python-test",
        browser_executable=str(browser_path),
    )

    assert summary["skipped"] is True
    assert "service worker did not start" in summary["reason"]


def test_chrome_extension_smoke_requires_success_when_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_chrome_smoke_module()
    browser_path = tmp_path / "chrome.exe"
    browser_path.write_text("", encoding="utf-8")

    def fake_run_browser_smoke(**_kwargs):
        raise check_module.ChromeExtensionSmokeError("service worker did not start")

    monkeypatch.setattr(
        check_module,
        "_validate_extension_static_contract",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(check_module, "_run_browser_smoke", fake_run_browser_smoke)

    with pytest.raises(
        check_module.ChromeExtensionSmokeError,
        match="service worker did not start",
    ):
        check_module.check_chrome_extension_smoke(
            python_executable="python-test",
            browser_executable=str(browser_path),
            require_browser=True,
        )


def test_chrome_extension_smoke_extracts_extension_id() -> None:
    check_module = _load_chrome_smoke_module()

    extension_id = check_module._extension_id_from_target(
        {
            "url": (
                "chrome-extension://abcdefghijklmnopabcdefghijklmnop/"
                "src/background.js"
            ),
        },
    )

    assert extension_id == "abcdefghijklmnopabcdefghijklmnop"


def test_chrome_extension_smoke_reports_observed_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_chrome_smoke_module()
    times = iter([0.0, 0.1, 1.0])
    monkeypatch.setattr(check_module.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(check_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        check_module,
        "_json_get",
        lambda _url: [
            {"type": "page", "url": "about:blank"},
            {
                "type": "background_page",
                "url": "chrome-extension://component/background.html",
            },
        ],
    )

    with pytest.raises(
        check_module.ChromeExtensionSmokeError,
        match="Observed browser targets",
    ) as exc_info:
        check_module._wait_for_extension_target(cdp_port=7777, timeout_s=0.5)

    message = str(exc_info.value)
    assert "about:blank" in message
    assert "background_page" in message


def _load_chrome_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_chrome_extension_smoke",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
