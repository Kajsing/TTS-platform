from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from websockets.sync.client import connect as websocket_connect
except ImportError:  # pragma: no cover - exercised only in under-installed envs.
    websocket_connect = None

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
EXTENSION_ROOT = REPO_ROOT / "apps" / "chrome_extension"
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"
DEFAULT_MAX_CAPTURE_CHARS = 1600
DEFAULT_SERVICE_MAX_CHARS_PER_REQUEST = 800
DEFAULT_SERVICE_MAX_CHARS_PER_STREAM = 1200
EXTENSION_POPUP_PATH = "src/popup.html"

for path in (SCRIPT_DIR, SERVICE_SRC, CORE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import check_local_service_bootstrap as service_bootstrap  # noqa: E402
from check_extension_reader_flow import _build_long_article_fixture  # noqa: E402


class ChromeExtensionSmokeError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_chrome_extension_smoke")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--browser-executable", default=None)
    parser.add_argument("--require-browser", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--startup-timeout-s", type=float, default=30.0)
    parser.add_argument("--command-timeout-s", type=float, default=90.0)
    parser.add_argument("--max-capture-chars", type=int, default=DEFAULT_MAX_CAPTURE_CHARS)
    parser.add_argument(
        "--service-stream-limit-chars",
        type=int,
        default=DEFAULT_SERVICE_MAX_CHARS_PER_STREAM,
        help=(
            "Temporary service tts.max_chars_per_stream used by the browser smoke. "
            "It must be lower than --max-capture-chars so the smoke proves the "
            "extension follows the service cap."
        ),
    )
    args = parser.parse_args(argv)

    try:
        summary = check_chrome_extension_smoke(
            python_executable=args.python_executable,
            browser_executable=args.browser_executable,
            require_browser=args.require_browser,
            headed=args.headed,
            startup_timeout_s=args.startup_timeout_s,
            command_timeout_s=args.command_timeout_s,
            max_capture_chars=args.max_capture_chars,
            service_stream_limit_chars=args.service_stream_limit_chars,
        )
    except ChromeExtensionSmokeError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_chrome_extension_smoke(
    *,
    python_executable: str,
    browser_executable: str | None = None,
    require_browser: bool = False,
    headed: bool = False,
    startup_timeout_s: float = 30.0,
    command_timeout_s: float = 90.0,
    max_capture_chars: int = DEFAULT_MAX_CAPTURE_CHARS,
    service_stream_limit_chars: int = DEFAULT_SERVICE_MAX_CHARS_PER_STREAM,
) -> dict[str, object]:
    if max_capture_chars <= 0:
        raise ChromeExtensionSmokeError("--max-capture-chars must be positive.")
    if service_stream_limit_chars <= 1000:
        raise ChromeExtensionSmokeError("--service-stream-limit-chars must be above 1000.")
    if max_capture_chars <= service_stream_limit_chars:
        raise ChromeExtensionSmokeError(
            "--max-capture-chars must be greater than --service-stream-limit-chars."
        )
    browser_path = _resolve_browser_executable(browser_executable)
    if browser_path is None:
        if require_browser:
            raise ChromeExtensionSmokeError("Chrome or Edge executable was not found.")
        return _skipped_summary("Chrome or Edge executable was not found.")
    if websocket_connect is None:
        if require_browser:
            raise ChromeExtensionSmokeError("Python package 'websockets' is not installed.")
        return _skipped_summary("Python package 'websockets' is not installed.")

    _validate_extension_static_contract(
        python_executable=python_executable,
        timeout_s=command_timeout_s,
    )

    try:
        smoke_result = _run_browser_smoke(
            python_executable=python_executable,
            browser_path=browser_path,
            headed=headed,
            startup_timeout_s=startup_timeout_s,
            command_timeout_s=command_timeout_s,
            max_capture_chars=max_capture_chars,
            service_stream_limit_chars=service_stream_limit_chars,
        )
    except ChromeExtensionSmokeError as exc:
        if require_browser:
            raise
        return _skipped_summary(f"Chrome/MV3 smoke could not run in this environment: {exc}")

    return smoke_result


def _run_browser_smoke(
    *,
    python_executable: str,
    browser_path: Path,
    headed: bool,
    startup_timeout_s: float,
    command_timeout_s: float,
    max_capture_chars: int,
    service_stream_limit_chars: int,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="tts-platform-chrome-smoke-") as temp_dir:
        temp_root = Path(temp_dir)
        cdp_port = service_bootstrap._reserve_loopback_port()
        profile_dir = temp_root / "chrome-profile"
        browser_process = _start_browser(
            browser_path=browser_path,
            cdp_port=cdp_port,
            profile_dir=profile_dir,
            headed=headed,
        )
        try:
            _wait_for_cdp(cdp_port=cdp_port, timeout_s=startup_timeout_s)
            try:
                extension_id = _wait_for_loaded_extension_id(
                    profile_dir=profile_dir,
                    timeout_s=startup_timeout_s,
                )
            except ChromeExtensionSmokeError as exc:
                raise ChromeExtensionSmokeError(
                    f"{exc} {_browser_extension_load_hint(browser_path)}"
                ) from exc
            extension_origin = f"chrome-extension://{extension_id}"

            repo_root = temp_root / "repo"
            service_bootstrap._seed_temp_repo(repo_root)
            env = service_bootstrap._source_env()
            setup_payload = service_bootstrap._run_json_command(
                [
                    python_executable,
                    "-m",
                    "tts_service.cli",
                    "setup-local",
                    "--repo-root",
                    str(repo_root),
                ],
                env=env,
                timeout_s=command_timeout_s,
            )
            token_file = Path(str(setup_payload.get("token_file", "")))
            if not token_file.is_file():
                raise ChromeExtensionSmokeError("setup-local did not create a token file.")
            _run_extension_allow_origin(
                python_executable=python_executable,
                repo_root=repo_root,
                extension_origin=extension_origin,
                env=env,
                timeout_s=command_timeout_s,
            )
            _set_tts_text_limits(
                repo_root=repo_root,
                max_chars_per_request=DEFAULT_SERVICE_MAX_CHARS_PER_REQUEST,
                max_chars_per_stream=service_stream_limit_chars,
            )

            service_port = service_bootstrap._reserve_loopback_port()
            base_url = f"http://127.0.0.1:{service_port}"
            service_process = _start_service(
                python_executable=python_executable,
                repo_root=repo_root,
                port=service_port,
                env=env,
            )
            try:
                service_bootstrap._wait_for_health(
                    base_url=base_url,
                    process=service_process,
                    timeout_s=startup_timeout_s,
                )
                article_dir = temp_root / "article"
                article_url = _write_and_serve_article(article_dir)
                with _static_server(article_dir) as static_base_url:
                    page_url = f"{static_base_url}/{article_url}"
                    target_id = _create_page_target(cdp_port=cdp_port, url=page_url)
                    _wait_for_page_target(cdp_port=cdp_port, target_id=target_id)
                    extension_target = _create_extension_page_target(
                        cdp_port=cdp_port,
                        extension_id=extension_id,
                    )
                    smoke = _run_extension_smoke(
                        extension_target=extension_target,
                        base_url=base_url,
                        page_url=page_url,
                        token=token_file.read_text(encoding="utf-8").strip(),
                        max_capture_chars=max_capture_chars,
                        service_stream_limit_chars=service_stream_limit_chars,
                        command_timeout_s=command_timeout_s,
                    )
            finally:
                service_bootstrap._stop_process(service_process)
        finally:
            _stop_process(browser_process)

    return {
        "skipped": False,
        "browser": str(browser_path),
        "headless": not headed,
        "extension": {
            "id": extension_id,
            "origin": extension_origin,
        },
        "service": {
            "base_url": base_url,
        },
        "page": {
            "url": page_url,
        },
        "smoke": smoke,
    }


def _skipped_summary(reason: str) -> dict[str, object]:
    return {
        "skipped": True,
        "reason": reason,
        "browser": None,
    }


def _resolve_browser_executable(browser_executable: str | None) -> Path | None:
    if browser_executable:
        path = Path(browser_executable).expanduser()
        return path.resolve() if path.is_file() else None

    for command in ("chrome.exe", "msedge.exe", "chromium.exe", "chrome", "chromium"):
        resolved = shutil.which(command)
        if resolved:
            return Path(resolved).resolve()

    candidate_paths = [
        os.environ.get("TTS_PLATFORM_CHROME"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for candidate in candidate_paths:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def _start_browser(
    *,
    browser_path: Path,
    cdp_port: int,
    profile_dir: Path,
    headed: bool,
) -> subprocess.Popen[str]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(browser_path),
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile_dir}",
        f"--disable-extensions-except={EXTENSION_ROOT}",
        f"--load-extension={EXTENSION_ROOT}",
        "--no-first-run",
        "--no-default-browser-check",
        "--autoplay-policy=no-user-gesture-required",
        "--mute-audio",
        "about:blank",
    ]
    if not headed:
        command.extend(["--headless=new", "--disable-gpu"])
    return subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _validate_extension_static_contract(*, python_executable: str, timeout_s: float) -> None:
    result = subprocess.run(
        [python_executable, "scripts/check_extension.py"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_s,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        raise ChromeExtensionSmokeError(
            "Extension static validation failed before Chrome smoke."
            + (f" Output: {output}" if output else "")
        )


def _start_service(
    *,
    python_executable: str,
    repo_root: Path,
    port: int,
    env: dict[str, str],
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            python_executable,
            "-m",
            "tts_service.cli",
            "serve",
            "--repo-root",
            str(repo_root),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_cdp(*, cdp_port: int, timeout_s: float) -> None:
    deadline = time.perf_counter() + timeout_s
    last_error = "CDP did not answer yet"
    while time.perf_counter() < deadline:
        try:
            _json_get(f"http://127.0.0.1:{cdp_port}/json/version")
            return
        except (OSError, ValueError) as exc:
            last_error = str(exc)
            time.sleep(0.2)
    raise ChromeExtensionSmokeError(f"Timed out waiting for Chrome CDP: {last_error}")


def _wait_for_extension_target(*, cdp_port: int, timeout_s: float) -> dict[str, object]:
    deadline = time.perf_counter() + timeout_s
    observed_targets: list[dict[str, str]] = []
    while time.perf_counter() < deadline:
        targets = _json_get(f"http://127.0.0.1:{cdp_port}/json")
        if isinstance(targets, list):
            observed_targets = _summarize_browser_targets(targets)
            for target in targets:
                if _is_extension_service_worker(target):
                    return target
        time.sleep(0.2)
    observed_text = json.dumps(observed_targets, sort_keys=True)
    raise ChromeExtensionSmokeError(
        "Timed out waiting for extension service worker target. "
        f"Observed browser targets: {observed_text}"
    )


def _wait_for_loaded_extension_id(*, profile_dir: Path, timeout_s: float) -> str:
    deadline = time.perf_counter() + timeout_s
    preferences_path = profile_dir / "Default" / "Preferences"
    observed_ids: list[str] = []
    while time.perf_counter() < deadline:
        try:
            extension_id = _extension_id_from_preferences(preferences_path)
            if extension_id:
                return extension_id
            observed_ids = _extension_setting_ids(preferences_path)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.2)
    observed_text = json.dumps(observed_ids[:10], sort_keys=True)
    raise ChromeExtensionSmokeError(
        "Timed out waiting for unpacked extension registration in Chrome profile. "
        f"Observed extension setting ids: {observed_text}"
    )


def _extension_id_from_preferences(preferences_path: Path) -> str | None:
    preferences = json.loads(preferences_path.read_text(encoding="utf-8"))
    settings = preferences.get("extensions", {}).get("settings", {})
    if not isinstance(settings, dict):
        return None
    for extension_id, setting in settings.items():
        if not isinstance(setting, dict):
            continue
        path = setting.get("path")
        if isinstance(extension_id, str) and isinstance(path, str) and _same_path(
            path,
            EXTENSION_ROOT,
        ):
            return extension_id
    return None


def _extension_setting_ids(preferences_path: Path) -> list[str]:
    preferences = json.loads(preferences_path.read_text(encoding="utf-8"))
    settings = preferences.get("extensions", {}).get("settings", {})
    if not isinstance(settings, dict):
        return []
    return [str(extension_id) for extension_id in settings]


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        left_path = Path(left).expanduser().resolve()
        right_path = Path(right).expanduser().resolve()
    except OSError:
        return False
    return os.path.normcase(str(left_path)) == os.path.normcase(str(right_path))


def _browser_extension_load_hint(browser_path: Path) -> str:
    executable_name = browser_path.name.lower()
    browser_text = str(browser_path).lower()
    if (
        executable_name in {"chrome.exe", "google chrome"}
        and "chrome for testing" not in browser_text
        and "chromium" not in browser_text
    ):
        return (
            "Branded Chrome 137+ may ignore --load-extension for unpacked "
            "extensions; pass a Chrome for Testing or Chromium executable with "
            "--browser-executable for strict automated MV3 evidence."
        )
    return (
        "Ensure this browser build supports command-line unpacked extension "
        "loading, or pass a Chrome for Testing or Chromium executable with "
        "--browser-executable."
    )


def _summarize_browser_targets(targets: list[object]) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for target in targets[:10]:
        if not isinstance(target, dict):
            continue
        summaries.append(
            {
                "type": str(target.get("type", "")),
                "url": str(target.get("url", ""))[:160],
            }
        )
    return summaries


def _wait_for_page_target(*, cdp_port: int, target_id: str) -> dict[str, object]:
    deadline = time.perf_counter() + 10
    while time.perf_counter() < deadline:
        targets = _json_get(f"http://127.0.0.1:{cdp_port}/json")
        if isinstance(targets, list):
            for target in targets:
                if target.get("id") == target_id:
                    return target
        time.sleep(0.1)
    raise ChromeExtensionSmokeError("Timed out waiting for article page target.")


def _is_extension_service_worker(target: object) -> bool:
    if not isinstance(target, dict):
        return False
    url = str(target.get("url", ""))
    return (
        target.get("type") == "service_worker"
        and url.startswith("chrome-extension://")
        and url.endswith("/src/background.js")
    )


def _extension_id_from_target(target: dict[str, object]) -> str:
    url = str(target.get("url", ""))
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "chrome-extension" or not parsed.netloc:
        raise ChromeExtensionSmokeError(f"Unexpected extension target URL: {url}")
    return parsed.netloc


def _run_extension_allow_origin(
    *,
    python_executable: str,
    repo_root: Path,
    extension_origin: str,
    env: dict[str, str],
    timeout_s: float,
) -> None:
    payload = service_bootstrap._run_json_command(
        [
            python_executable,
            "-m",
            "tts_service.cli",
            "extension-allow-origin",
            extension_origin,
            "--repo-root",
            str(repo_root),
        ],
        env=env,
        timeout_s=timeout_s,
    )
    allowed_origins = payload.get("allowed_origins")
    if not isinstance(allowed_origins, list) or extension_origin not in allowed_origins:
        raise ChromeExtensionSmokeError("extension-allow-origin did not allow-list Chrome.")


def _set_tts_text_limits(
    *,
    repo_root: Path,
    max_chars_per_request: int,
    max_chars_per_stream: int,
) -> None:
    config_path = repo_root / "config" / "config.toml"
    config_text = config_path.read_text(encoding="utf-8")
    replacements = {
        "max_chars_per_request = 4000": f"max_chars_per_request = {max_chars_per_request}",
        "max_chars_per_stream = 48000": f"max_chars_per_stream = {max_chars_per_stream}",
    }
    for source, replacement in replacements.items():
        if source not in config_text:
            raise ChromeExtensionSmokeError(
                f"Temporary service config is missing expected line: {source}"
            )
        config_text = config_text.replace(source, replacement, 1)
    config_path.write_text(config_text, encoding="utf-8")


def _write_and_serve_article(article_dir: Path) -> str:
    article_dir.mkdir(parents=True, exist_ok=True)
    article = _build_long_article_fixture(section_count=8, paragraphs_per_section=3)
    (article_dir / "article.html").write_text(
        "<!doctype html><html><body><main><article>"
        + "".join(f"<p>{paragraph}</p>" for paragraph in article.split("\n\n"))
        + "</article></main></body></html>",
        encoding="utf-8",
    )
    return "article.html"


@contextmanager
def _static_server(root: Path):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

    port = service_bootstrap._reserve_loopback_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _create_page_target(*, cdp_port: int, url: str) -> str:
    version = _json_get(f"http://127.0.0.1:{cdp_port}/json/version")
    websocket_url = str(version.get("webSocketDebuggerUrl", ""))
    with _CdpClient(websocket_url) as cdp:
        result = cdp.send("Target.createTarget", {"url": url})
    target_id = result.get("targetId")
    if not isinstance(target_id, str):
        raise ChromeExtensionSmokeError("Chrome did not return a target id for article page.")
    return target_id


def _create_extension_page_target(*, cdp_port: int, extension_id: str) -> dict[str, object]:
    target_id = _create_page_target(
        cdp_port=cdp_port,
        url=f"chrome-extension://{extension_id}/{EXTENSION_POPUP_PATH}",
    )
    return _wait_for_page_target(cdp_port=cdp_port, target_id=target_id)


def _run_extension_smoke(
    *,
    extension_target: dict[str, object],
    base_url: str,
    page_url: str,
    token: str,
    max_capture_chars: int,
    service_stream_limit_chars: int,
    command_timeout_s: float,
) -> dict[str, object]:
    websocket_url = str(extension_target.get("webSocketDebuggerUrl", ""))
    if not websocket_url:
        raise ChromeExtensionSmokeError("Extension service worker target has no CDP URL.")
    with _CdpClient(websocket_url) as cdp:
        start_payload = _runtime_evaluate(
            cdp,
            _start_expression(
                base_url=base_url,
                page_url=page_url,
                token=token,
                max_capture_chars=max_capture_chars,
            ),
        )
        _assert_start_payload(
            start_payload,
            max_capture_chars=max_capture_chars,
            service_stream_limit_chars=service_stream_limit_chars,
        )
        final_state = _wait_for_playback_state(
            cdp=cdp,
            timeout_s=command_timeout_s,
        )
        _runtime_evaluate(cdp, _stop_expression(int(start_payload["tabId"])))

    return {
        "capture": {
            "text_chars": start_payload["captureTextChars"],
            "truncated": start_payload["captureMeta"]["truncated"],
            "source": start_payload["captureMeta"]["source"],
            "configured_max_chars": max_capture_chars,
            "playback_max_chars": start_payload["playbackCaptureMeta"]["maxChars"],
        },
        "text_limits": {
            "service_max_chars_per_stream": service_stream_limit_chars,
            "snapshot_max_page_chars": start_payload["serviceTextLimits"]["maxPageChars"],
        },
        "service_health_status": start_payload["healthStatus"],
        "start_result": start_payload["startResult"],
        "final_state": {
            "status": final_state.get("status"),
            "last_event": final_state.get("lastEvent"),
            "source": final_state.get("source"),
            "reader_progress": final_state.get("readerProgress"),
        },
    }


def _start_expression(
    *,
    base_url: str,
    page_url: str,
    token: str,
    max_capture_chars: int,
) -> str:
    return f"""
(async () => {{
  await chrome.storage.local.set({{
    baseUrl: {json.dumps(base_url)},
    token: {json.dumps(token)},
    voice: "",
    prebufferMs: 50,
    lowWatermarkMs: 20,
    highWatermarkMs: 100,
    maxChars: {max_capture_chars}
  }});
  const serviceSnapshot = await chrome.runtime.sendMessage({{
    type: "tts-extension:get-service-snapshot"
  }});
  const tabs = await chrome.tabs.query({{}});
  const tab = tabs.find((candidate) => candidate.url === {json.dumps(page_url)});
  if (!tab || typeof tab.id !== "number") {{
    throw new Error("Article tab not found for smoke URL: " + {json.dumps(page_url)});
  }}
  const capture = await chrome.tabs.sendMessage(tab.id, {{
    type: "tts-extension:get-page-text",
    maxChars: {max_capture_chars}
  }});
  const healthResponse = await fetch({json.dumps(base_url + "/v1/health")});
  const health = await healthResponse.json();
  const startResults = await chrome.scripting.executeScript({{
    target: {{tabId: tab.id}},
    func: () => chrome.runtime.sendMessage({{type: "tts-extension:speak-page"}})
  }});
  const stored = await chrome.storage.session.get("playbackState");
  const playbackState = stored.playbackState || {{}};
  return {{
    tabId: tab.id,
    captureTextChars: capture.text.length,
    captureMeta: capture.meta,
    healthStatus: health.status,
    healthTts: health.tts,
    serviceTextLimits: serviceSnapshot.textLimits,
    playbackCaptureMeta: playbackState.pageCapture,
    startResult: startResults[0].result
  }};
}})()
""".strip()


def _stop_expression(tab_id: int) -> str:
    return f"""
(async () => {{
  const results = await chrome.scripting.executeScript({{
    target: {{tabId: {tab_id}}},
    func: () => chrome.runtime.sendMessage({{type: "tts-extension:stop"}})
  }});
  return results[0].result;
}})()
""".strip()


def _wait_for_playback_state(*, cdp: "_CdpClient", timeout_s: float) -> dict[str, object]:
    deadline = time.perf_counter() + timeout_s
    last_state: dict[str, object] = {}
    while time.perf_counter() < deadline:
        expression = (
            '(async () => '
            '(await chrome.storage.session.get("playbackState")).playbackState || {})()'
        )
        state = _runtime_evaluate(
            cdp,
            expression,
        )
        if isinstance(state, dict):
            last_state = state
            if state.get("status") in {"streaming", "draining", "done"} and state.get(
                "readerProgress"
            ):
                return state
            if state.get("status") in {"error", "interrupted", "cancelled"}:
                raise ChromeExtensionSmokeError(f"Extension playback failed: {state!r}")
        time.sleep(0.3)
    raise ChromeExtensionSmokeError(f"Timed out waiting for extension playback: {last_state!r}")


def _assert_start_payload(
    payload: dict[str, object],
    *,
    max_capture_chars: int,
    service_stream_limit_chars: int,
) -> None:
    capture_meta = payload.get("captureMeta")
    playback_capture_meta = payload.get("playbackCaptureMeta")
    health_tts = payload.get("healthTts")
    service_text_limits = payload.get("serviceTextLimits")
    start_result = payload.get("startResult")
    if not isinstance(capture_meta, dict):
        raise ChromeExtensionSmokeError("Extension capture did not return metadata.")
    if not isinstance(playback_capture_meta, dict):
        raise ChromeExtensionSmokeError("Extension playback did not store page-capture metadata.")
    if not isinstance(health_tts, dict):
        raise ChromeExtensionSmokeError("Service health did not return TTS text limits.")
    if not isinstance(service_text_limits, dict):
        raise ChromeExtensionSmokeError("Extension service snapshot did not return text limits.")
    if payload.get("healthStatus") != "ok":
        raise ChromeExtensionSmokeError("Extension background could not fetch service health.")
    if health_tts.get("max_chars_per_stream") != service_stream_limit_chars:
        raise ChromeExtensionSmokeError(
            f"Service stream limit mismatch: {health_tts!r}"
        )
    if service_text_limits.get("maxPageChars") != service_stream_limit_chars:
        raise ChromeExtensionSmokeError(
            "Extension service snapshot did not expose the service page cap: "
            f"{service_text_limits!r}"
        )
    if capture_meta.get("maxChars") != max_capture_chars:
        raise ChromeExtensionSmokeError(
            f"Direct page capture did not use configured max chars: {capture_meta!r}"
        )
    if playback_capture_meta.get("maxChars") != service_stream_limit_chars:
        raise ChromeExtensionSmokeError(
            "Speak Page did not clamp page capture to the service stream limit: "
            f"{playback_capture_meta!r}"
        )
    if int(payload.get("captureTextChars", 0)) < 1000:
        raise ChromeExtensionSmokeError("Extension did not capture long-page text.")
    if capture_meta.get("truncated") is not True:
        raise ChromeExtensionSmokeError("Extension long-page capture was not truncated.")
    if playback_capture_meta.get("truncated") is not True:
        raise ChromeExtensionSmokeError("Extension playback capture was not truncated.")
    if not isinstance(start_result, dict) or start_result.get("ok") is not True:
        raise ChromeExtensionSmokeError(f"Speak Page did not start successfully: {start_result!r}")


def _runtime_evaluate(cdp: "_CdpClient", expression: str) -> object:
    result = cdp.send(
        "Runtime.evaluate",
        {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        },
    )
    if "exceptionDetails" in result:
        raise ChromeExtensionSmokeError(f"Chrome Runtime.evaluate failed: {result!r}")
    remote_object = result.get("result")
    if not isinstance(remote_object, dict):
        raise ChromeExtensionSmokeError(f"Unexpected Runtime.evaluate result: {result!r}")
    return remote_object.get("value")


def _json_get(url: str) -> object:
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


class _CdpClient:
    def __init__(self, websocket_url: str) -> None:
        if not websocket_url:
            raise ChromeExtensionSmokeError("Missing CDP WebSocket URL.")
        self.websocket_url = websocket_url
        self._next_id = 0
        self._socket = None

    def __enter__(self) -> "_CdpClient":
        if websocket_connect is None:
            raise ChromeExtensionSmokeError("Python package 'websockets' is not installed.")
        self._socket = websocket_connect(self.websocket_url, open_timeout=5)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._socket is not None:
            self._socket.close()

    def send(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        if self._socket is None:
            raise ChromeExtensionSmokeError("CDP socket is not connected.")
        self._next_id += 1
        message_id = self._next_id
        self._socket.send(
            json.dumps(
                {
                    "id": message_id,
                    "method": method,
                    "params": params or {},
                }
            )
        )
        while True:
            raw_message = self._socket.recv(timeout=10)
            payload = json.loads(raw_message)
            if payload.get("id") != message_id:
                continue
            if "error" in payload:
                raise ChromeExtensionSmokeError(f"CDP command failed: {payload['error']!r}")
            result = payload.get("result", {})
            if not isinstance(result, dict):
                raise ChromeExtensionSmokeError(f"Unexpected CDP result: {payload!r}")
            return result


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        process.communicate(timeout=1)
        return
    process.terminate()
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)


if __name__ == "__main__":
    main()
