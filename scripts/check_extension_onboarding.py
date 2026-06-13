from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
EXTENSION_ROOT = REPO_ROOT / "apps" / "chrome_extension"
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"
SAMPLE_EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"

for path in (SCRIPT_DIR, SERVICE_SRC, CORE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import check_local_service_bootstrap as service_bootstrap  # noqa: E402
from tts_service.config import load_config  # noqa: E402


class ExtensionOnboardingError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_extension_onboarding")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--startup-timeout-s", type=float, default=30.0)
    parser.add_argument("--command-timeout-s", type=float, default=60.0)
    args = parser.parse_args(argv)

    try:
        summary = check_extension_onboarding(
            python_executable=args.python_executable,
            startup_timeout_s=args.startup_timeout_s,
            command_timeout_s=args.command_timeout_s,
        )
    except ExtensionOnboardingError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_extension_onboarding(
    *,
    python_executable: str,
    startup_timeout_s: float = 30.0,
    command_timeout_s: float = 60.0,
) -> dict[str, object]:
    popup_summary = _verify_popup_onboarding_surface()
    allow_list_summary = _verify_allow_list_snippet(SAMPLE_EXTENSION_ORIGIN)

    with tempfile.TemporaryDirectory(prefix="tts-platform-extension-onboarding-") as temp_dir:
        temp_repo_root = Path(temp_dir) / "repo"
        service_bootstrap._seed_temp_repo(temp_repo_root)
        env = service_bootstrap._source_env()
        setup_payload = service_bootstrap._run_json_command(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "setup-local",
                "--repo-root",
                str(temp_repo_root),
            ],
            env=env,
            timeout_s=command_timeout_s,
        )
        token_file = Path(str(setup_payload.get("token_file", "")))
        if not token_file.is_file():
            raise ExtensionOnboardingError("setup-local did not create a token file.")

        port = service_bootstrap._reserve_loopback_port()
        base_url = f"http://127.0.0.1:{port}"
        service_process = subprocess.Popen(
            [
                python_executable,
                "-m",
                "tts_service.cli",
                "serve",
                "--repo-root",
                str(temp_repo_root),
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
        try:
            service_bootstrap._wait_for_health(
                base_url=base_url,
                process=service_process,
                timeout_s=startup_timeout_s,
            )
            service_summary = _verify_service_snapshot_contract(base_url)
        finally:
            service_bootstrap._stop_process(service_process)

    return {
        "popup": popup_summary,
        "allow_list": allow_list_summary,
        "service_snapshot": service_summary,
    }


def _verify_popup_onboarding_surface() -> dict[str, object]:
    popup_html_path = EXTENSION_ROOT / "src" / "popup.html"
    popup_js_path = EXTENSION_ROOT / "src" / "popup.js"
    popup_html = popup_html_path.read_text(encoding="utf-8")
    popup_js = popup_js_path.read_text(encoding="utf-8")
    if "\u00e2\u20ac\u00a6" in popup_html or "\u2026" in popup_html:
        raise ExtensionOnboardingError("popup.html contains non-ASCII loading ellipsis text.")

    parser = _ElementCollector()
    parser.feed(popup_html)
    required_elements = {
        "base-url": {"tag": "input", "type": "url"},
        "token": {"tag": "input", "type": "password"},
        "voice": {"tag": "select"},
        "save-config": {"tag": "button"},
        "refresh-service": {"tag": "button"},
        "copy-origin": {"tag": "button"},
        "copy-snippet": {"tag": "button"},
        "service-status": {"tag": "pre"},
        "onboarding-status": {"tag": "pre"},
        "extension-origin": {"tag": "p"},
        "origin-snippet": {"tag": "pre"},
    }
    errors: list[str] = []
    for element_id, expected in required_elements.items():
        element = parser.elements_by_id.get(element_id)
        if element is None:
            errors.append(f"popup.html is missing #{element_id}")
            continue
        if element["tag"] != expected["tag"]:
            errors.append(f"#{element_id} must be a <{expected['tag']}>")
        if "type" in expected and element["attrs"].get("type") != expected["type"]:
            errors.append(f"#{element_id} must use type={expected['type']!r}")

    required_fragments = [
        '"tts-extension:get-service-snapshot"',
        "snapshot.originConfigSnippet",
        "snapshot.extensionOrigin",
        "formatOnboardingStatus",
        'checklistLine("Service reachable"',
        'checklistLine("Token saved"',
        '"Origin snippet ready"',
        '"Voice available"',
        '"Health ok"',
        "populateVoiceOptions({",
    ]
    for fragment in required_fragments:
        if fragment not in popup_js:
            errors.append(f"popup.js must contain {fragment!r}")
    if errors:
        raise ExtensionOnboardingError(
            "Extension onboarding surface check failed:\n" + "\n".join(errors)
        )

    return {
        "required_element_count": len(required_elements),
        "checklist_items": 5,
        "voice_selector": True,
        "copy_snippet": True,
    }


def _verify_allow_list_snippet(extension_origin: str) -> dict[str, object]:
    background_js = (EXTENSION_ROOT / "src" / "background.js").read_text(encoding="utf-8")
    required_fragments = [
        "function buildOriginConfigSnippet(extensionOrigin)",
        '"[security]"',
        '`allowed_origins = ["${extensionOrigin}"]`',
    ]
    missing = [fragment for fragment in required_fragments if fragment not in background_js]
    if missing:
        raise ExtensionOnboardingError(
            "Background allow-list snippet wiring is incomplete:\n" + "\n".join(missing)
        )

    with tempfile.TemporaryDirectory(prefix="tts-platform-origin-snippet-") as temp_dir:
        config_path = Path(temp_dir) / "config.toml"
        config_path.write_text(
            "[security]\n"
            f'allowed_origins = ["{extension_origin}"]\n',
            encoding="utf-8",
        )
        config = load_config(config_path, env={})
    if config.security.allowed_origins != (extension_origin,):
        raise ExtensionOnboardingError("Generated extension origin is not config-loadable.")
    return {
        "sample_origin": extension_origin,
        "config_loadable": True,
    }


def _verify_service_snapshot_contract(base_url: str) -> dict[str, object]:
    with httpx.Client(timeout=30.0) as client:
        health = _get_json(client, f"{base_url}/v1/health")
        voices = _get_json(client, f"{base_url}/v1/voices")

    health_checks = health.get("checks")
    voice_list = voices.get("voices")
    default_voice = voices.get("default_voice")
    errors: list[str] = []
    if health.get("status") != "ok":
        errors.append(f"health status must be ok, got {health.get('status')!r}")
    if health.get("auth_enabled") is not True:
        errors.append("health must expose auth_enabled=true for popup onboarding")
    if not isinstance(health_checks, dict) or health_checks.get("backend_ready") is not True:
        errors.append("health checks must expose backend_ready=true")
    if not isinstance(voice_list, list) or not voice_list:
        errors.append("voices payload must include at least one voice")
    voice_ids = [
        voice.get("id")
        for voice in voice_list or []
        if isinstance(voice, dict)
    ]
    if not isinstance(default_voice, str) or default_voice not in voice_ids:
        errors.append("voices.default_voice must match a listed voice")
    if errors:
        raise ExtensionOnboardingError(
            "Extension service snapshot contract failed:\n" + "\n".join(errors)
        )

    return {
        "base_url": base_url,
        "health_status": health["status"],
        "auth_enabled": health["auth_enabled"],
        "default_voice": default_voice,
        "voice_count": len(voice_ids),
    }


def _get_json(client: httpx.Client, url: str) -> dict[str, object]:
    response = client.get(url)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ExtensionOnboardingError(f"Expected JSON object from {url}.")
    return payload


class _ElementCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements_by_id: dict[str, dict[str, object]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {
            key: value or ""
            for key, value in attrs
        }
        element_id = attr_map.get("id")
        if element_id:
            self.elements_by_id[element_id] = {
                "tag": tag,
                "attrs": attr_map,
            }


if __name__ == "__main__":
    main()
