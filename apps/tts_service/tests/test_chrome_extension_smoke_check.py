import importlib.util
import json
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


def test_chrome_extension_smoke_reads_extension_id_from_preferences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_chrome_smoke_module()
    extension_root = tmp_path / "apps" / "chrome_extension"
    extension_root.mkdir(parents=True)
    monkeypatch.setattr(check_module, "EXTENSION_ROOT", extension_root)
    preferences_path = tmp_path / "Default" / "Preferences"
    preferences_path.parent.mkdir()
    preferences_path.write_text(
        json.dumps(
            {
                "extensions": {
                    "settings": {
                        "abcdefghijklmnopabcdefghijklmnop": {
                            "path": str(extension_root),
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    extension_id = check_module._extension_id_from_preferences(preferences_path)

    assert extension_id == "abcdefghijklmnopabcdefghijklmnop"


def test_chrome_extension_smoke_opens_popup_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_chrome_smoke_module()
    created_urls: list[str] = []

    def fake_create_page_target(*, cdp_port: int, url: str) -> str:
        assert cdp_port == 7777
        created_urls.append(url)
        return "target-1"

    def fake_wait_for_page_target(*, cdp_port: int, target_id: str):
        assert cdp_port == 7777
        assert target_id == "target-1"
        return {"id": target_id, "url": created_urls[0]}

    monkeypatch.setattr(check_module, "_create_page_target", fake_create_page_target)
    monkeypatch.setattr(check_module, "_wait_for_page_target", fake_wait_for_page_target)

    target = check_module._create_extension_page_target(
        cdp_port=7777,
        extension_id="abcdefghijklmnopabcdefghijklmnop",
    )

    assert created_urls == [
        "chrome-extension://abcdefghijklmnopabcdefghijklmnop/src/popup.html",
    ]
    assert target["url"] == created_urls[0]


def test_chrome_extension_smoke_start_expression_targets_article_url() -> None:
    check_module = _load_chrome_smoke_module()

    expression = check_module._start_expression(
        base_url="http://127.0.0.1:5000",
        page_url="http://127.0.0.1:5001/article.html",
        token="secret-token",
        max_capture_chars=1600,
    )

    assert "chrome.tabs.query({})" in expression
    assert 'candidate.url === "http://127.0.0.1:5001/article.html"' in expression
    assert "active: true" not in expression


def test_chrome_extension_smoke_chrome_registration_hint() -> None:
    check_module = _load_chrome_smoke_module()

    hint = check_module._browser_extension_load_hint(
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    )

    assert "Chrome 137+" in hint
    assert "Chrome for Testing" in hint
    assert "--browser-executable" in hint

    compatible_hint = check_module._browser_extension_load_hint(
        Path(r"C:\Tools\Chrome for Testing\chrome.exe")
    )
    assert "Chrome 137+" not in compatible_hint
    assert "supports command-line unpacked extension loading" in compatible_hint


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
