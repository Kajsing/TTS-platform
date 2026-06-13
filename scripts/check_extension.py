from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = REPO_ROOT / "apps" / "chrome_extension"
MANIFEST_PATH = EXTENSION_ROOT / "manifest.json"
LOCAL_SERVICE_HOST_PERMISSIONS = {"http://127.0.0.1/*", "http://localhost/*"}
ALLOWED_EXTENSION_PERMISSIONS = {
    "activeTab",
    "contextMenus",
    "offscreen",
    "scripting",
    "storage",
    "tabs",
}


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    verify_manifest_policy(manifest)
    referenced_paths = collect_manifest_paths(manifest)

    missing_paths = [path for path in referenced_paths if not path.exists()]
    if missing_paths:
        missing_summary = "\n".join(
            str(path.relative_to(REPO_ROOT)) for path in missing_paths
        )
        raise SystemExit(f"Missing extension files:\n{missing_summary}")

    print("Manifest references resolved.")
    for path in sorted(referenced_paths):
        print(path.relative_to(REPO_ROOT))

    popup_assets = collect_html_assets(EXTENSION_ROOT / "src" / "popup.html")
    offscreen_assets = collect_html_assets(EXTENSION_ROOT / "offscreen" / "offscreen.html")
    for asset in popup_assets | offscreen_assets:
        if not asset.exists():
            raise SystemExit(f"Missing HTML-linked asset: {asset.relative_to(REPO_ROOT)}")

    print("HTML asset references resolved.")
    verify_extension_wiring()
    print("Extension wiring resolved.")
    verify_extension_install_assets(manifest)
    print("Extension install assets resolved.")
    verify_extension_privacy_boundaries()
    print("Extension policy resolved.")

    node_binary = shutil.which("node")
    if node_binary is None:
        print("Skipped JavaScript syntax checks because node is not installed.")
        return

    js_paths = sorted(
        path
        for path in referenced_paths | popup_assets | offscreen_assets
        if path.suffix == ".js"
    )
    for path in js_paths:
        subprocess.run([node_binary, "--check", str(path)], check=True)
    print("JavaScript syntax checks passed.")


def collect_manifest_paths(manifest: dict[str, object]) -> set[Path]:
    paths: set[Path] = set()

    background = manifest.get("background", {})
    if isinstance(background, dict):
        service_worker = background.get("service_worker")
        if isinstance(service_worker, str):
            paths.add(EXTENSION_ROOT / service_worker)

    action = manifest.get("action", {})
    if isinstance(action, dict):
        popup = action.get("default_popup")
        if isinstance(popup, str):
            paths.add(EXTENSION_ROOT / popup)
        paths.update(_collect_icon_paths(action.get("default_icon")))

    paths.update(_collect_icon_paths(manifest.get("icons")))

    for content_script in manifest.get("content_scripts", []):
        if not isinstance(content_script, dict):
            continue
        for script_path in content_script.get("js", []):
            if isinstance(script_path, str):
                paths.add(EXTENSION_ROOT / script_path)

    for resource_group in manifest.get("web_accessible_resources", []):
        if not isinstance(resource_group, dict):
            continue
        for resource_path in resource_group.get("resources", []):
            if isinstance(resource_path, str):
                paths.add(EXTENSION_ROOT / resource_path)

    return paths


def collect_html_assets(path: Path) -> set[Path]:
    contents = path.read_text(encoding="utf-8")
    assets: set[Path] = {path}
    for marker in ('src="', 'href="'):
        start = 0
        while True:
            index = contents.find(marker, start)
            if index == -1:
                break
            value_start = index + len(marker)
            value_end = contents.find('"', value_start)
            if value_end == -1:
                break
            relative_path = contents[value_start:value_end]
            if relative_path and not relative_path.startswith(("http://", "https://")):
                assets.add(path.parent / relative_path)
            start = value_end + 1
    return assets


def verify_manifest_policy(manifest: dict[str, object]) -> None:
    errors: list[str] = []
    _expect(errors, manifest.get("manifest_version") == 3, "manifest_version must be 3")

    permissions = _string_set(manifest.get("permissions"))
    _expect(
        errors,
        permissions == ALLOWED_EXTENSION_PERMISSIONS,
        "permissions must stay explicit and reviewable: "
        f"{sorted(ALLOWED_EXTENSION_PERMISSIONS)}",
    )

    host_permissions = _string_set(manifest.get("host_permissions"))
    _expect(
        errors,
        host_permissions == LOCAL_SERVICE_HOST_PERMISSIONS,
        "host_permissions must be limited to the localhost service origins",
    )
    _expect(
        errors,
        "<all_urls>" not in host_permissions,
        "host_permissions must not include <all_urls>; page access belongs to content_scripts",
    )

    background = manifest.get("background")
    _expect(
        errors,
        isinstance(background, dict)
        and background.get("service_worker") == "src/background.js"
        and background.get("type") == "module",
        "background must use src/background.js as an MV3 module service worker",
    )

    action = manifest.get("action")
    _expect(
        errors,
        isinstance(action, dict) and action.get("default_popup") == "src/popup.html",
        "action.default_popup must be src/popup.html",
    )
    expected_icons = {
        "16": "icons/icon-16.png",
        "32": "icons/icon-32.png",
        "48": "icons/icon-48.png",
        "128": "icons/icon-128.png",
    }
    _expect(errors, manifest.get("icons") == expected_icons, "manifest icons must be declared")
    _expect(
        errors,
        isinstance(action, dict) and action.get("default_icon") == expected_icons,
        "action.default_icon must use the packaged icon set",
    )

    content_scripts = manifest.get("content_scripts")
    content_script = (
        content_scripts[0]
        if isinstance(content_scripts, list)
        and len(content_scripts) == 1
        and isinstance(content_scripts[0], dict)
        else {}
    )
    _expect(
        errors,
        content_script.get("matches") == ["<all_urls>"]
        and content_script.get("js") == ["src/content-script.js"]
        and content_script.get("run_at") == "document_idle",
        "content_scripts must inject only src/content-script.js at document_idle",
    )

    web_accessible_resources = manifest.get("web_accessible_resources")
    web_resource = (
        web_accessible_resources[0]
        if isinstance(web_accessible_resources, list)
        and len(web_accessible_resources) == 1
        and isinstance(web_accessible_resources[0], dict)
        else {}
    )
    _expect(
        errors,
        web_resource.get("resources") == ["offscreen/offscreen.html"],
        "web_accessible_resources must expose only offscreen/offscreen.html",
    )

    _raise_if_errors("Extension manifest policy failed", errors)


def verify_extension_wiring() -> None:
    required_fragments = {
        EXTENSION_ROOT / "src" / "popup.html": [
            'id="resume-page"',
            'id="continue-page"',
            'id="previous-section"',
            'id="next-section"',
            'id="onboarding-status"',
            'id="copy-command"',
            'id="origin-command"',
        ],
        EXTENSION_ROOT / "src" / "popup.js": [
            '"tts-extension:resume-page"',
            '"tts-extension:continue-page"',
            '"tts-extension:previous-section"',
            '"tts-extension:next-section"',
            "formatOnboardingStatus",
            "formatReadinessCheck",
            '"Backend ready"',
            '"Default voice loaded"',
            "formatPageCapture",
            "formatPageStructure",
            "checklistLine",
            "snapshot.originCliCommand",
        ],
        EXTENSION_ROOT / "src" / "background.js": [
            '"tts-extension:resume-page"',
            '"tts-extension:continue-page"',
            '"tts-extension:previous-section"',
            '"tts-extension:next-section"',
            "maybeAutoContinuePage",
            "shouldAutoContinuePage",
            "isPagePlaybackSource",
            "page-auto-continue",
            "pageCapture",
            "resolveContinueTextCharStart",
            "resolveContinueStartSectionIndex",
            "resolvePreviousSectionIndex",
            "resolveNextSectionIndex",
            "resolveNextUncapturedSectionIndex",
            "sanitizePageCaptureMeta",
            "sanitizePageStructureMeta",
            "resolveResumeTextChunkIndex",
            "startTextChunkIndex",
            "buildOriginCliCommand",
        ],
        EXTENSION_ROOT / "src" / "content-script.js": [
            "getPageCapture",
            "extractReadableText(anchorElement, 1000).text",
            "minimumBlockLength(blockKind)",
            "createStructureSummary",
            "capturedHeadingCount",
            "startSectionIndex",
            "startTextChar",
            "nextTextCharStart",
            "nextSectionIndex",
            "buildCapturedSections",
            "truncated",
            "readableBlocks",
        ],
        EXTENSION_ROOT / "offscreen" / "offscreen.js": ["start_text_chunk_index"],
    }
    missing: list[str] = []
    for path, fragments in required_fragments.items():
        contents = path.read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment not in contents:
                missing.append(f"{path.relative_to(REPO_ROOT)}: {fragment}")
    if missing:
        raise SystemExit("Missing extension wiring:\n" + "\n".join(missing))


def verify_extension_install_assets(manifest: dict[str, object]) -> None:
    errors: list[str] = []
    install_guide = EXTENSION_ROOT / "INSTALL.md"
    if not install_guide.is_file():
        errors.append("INSTALL.md must be present for local handoff installs")
    else:
        install_text = install_guide.read_text(encoding="utf-8")
        _require_fragments(
            errors,
            "INSTALL.md",
            install_text,
            [
                "Load unpacked",
                "chrome://extensions",
                "scripts\\windows\\install_local.ps1",
                "scripts\\windows\\run_service.ps1",
                "tts setup-local",
                "tts extension-allow-origin <copied-origin>",
                "security.allowed_origins",
                "config\\token.txt",
            ],
        )

    icon_entries = manifest.get("icons") if isinstance(manifest.get("icons"), dict) else {}
    for size_label, icon_value in icon_entries.items():
        if not isinstance(size_label, str) or not isinstance(icon_value, str):
            errors.append("Icon manifest entries must map string sizes to paths")
            continue
        expected_size = int(size_label) if size_label.isdecimal() else None
        icon_path = EXTENSION_ROOT / icon_value
        if not icon_path.is_file():
            errors.append(f"Missing icon asset: {icon_path.relative_to(REPO_ROOT)}")
            continue
        if icon_path.suffix.lower() != ".png":
            errors.append(f"Icon asset must be PNG: {icon_path.relative_to(REPO_ROOT)}")
            continue
        dimensions = _png_dimensions(icon_path)
        if dimensions is None:
            errors.append(f"Icon asset must be a valid PNG: {icon_path.relative_to(REPO_ROOT)}")
            continue
        if expected_size is not None and dimensions != (expected_size, expected_size):
            errors.append(
                f"Icon asset dimensions must be {expected_size}x{expected_size}: "
                f"{icon_path.relative_to(REPO_ROOT)}"
            )

    _raise_if_errors("Extension install asset check failed", errors)


def verify_extension_privacy_boundaries(extension_root: Path = EXTENSION_ROOT) -> None:
    paths = {
        "content script": extension_root / "src" / "content-script.js",
        "popup": extension_root / "src" / "popup.js",
        "background": extension_root / "src" / "background.js",
        "offscreen": extension_root / "offscreen" / "offscreen.js",
    }
    contents = {
        label: path.read_text(encoding="utf-8").replace("\r\n", "\n")
        for label, path in paths.items()
    }
    errors: list[str] = []

    for label, text in contents.items():
        _reject_fragments(
            errors,
            label,
            text,
            [
                "localStorage",
                "sessionStorage",
                "indexedDB",
                "XMLHttpRequest",
                "eval(",
                "new Function(",
                "chrome.storage.sync",
            ],
        )

    _reject_fragments(
        errors,
        "content script",
        contents["content script"],
        ["fetch(", "new WebSocket", "chrome.storage", "chrome.runtime.sendMessage"],
    )
    _reject_fragments(
        errors,
        "popup",
        contents["popup"],
        ["fetch(", "new WebSocket", "chrome.storage", "chrome.tabs", "chrome.offscreen"],
    )
    _reject_fragments(
        errors,
        "background",
        contents["background"],
        ["new WebSocket"],
    )
    _reject_fragments(
        errors,
        "offscreen",
        contents["offscreen"],
        ["fetch(", "chrome.storage", "chrome.tabs", "chrome.scripting"],
    )

    _require_fragments(
        errors,
        "background",
        contents["background"],
        [
            "chrome.storage.local.get(DEFAULT_CONFIG)",
            "chrome.storage.local.set(sanitizeConfig(",
            "chrome.storage.session.set({\n    playbackState: nextState,",
            "pageCapture: capture.meta",
            "sanitizePageCaptureMeta",
            'fetchJson(config.baseUrl + "/v1/health")',
            'fetchJson(config.baseUrl + "/v1/voices")',
            "sendOffscreenMessage({",
        ],
    )
    _require_fragments(
        errors,
        "offscreen",
        contents["offscreen"],
        [
            "new WebSocket(wsUrl)",
            "auth_token: config.token",
            "payload: {\n          text: config.text,",
            'type: "tts-extension:playback-state"',
        ],
    )

    _raise_if_errors("Extension privacy boundary check failed", errors)


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def _collect_icon_paths(value: object) -> set[Path]:
    if not isinstance(value, dict):
        return set()
    return {
        EXTENSION_ROOT / icon_path
        for icon_path in value.values()
        if isinstance(icon_path, str)
    }


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or not header.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def _reject_fragments(
    errors: list[str],
    label: str,
    text: str,
    fragments: list[str],
) -> None:
    for fragment in fragments:
        if fragment in text:
            errors.append(f"{label} must not contain {fragment!r}")


def _require_fragments(
    errors: list[str],
    label: str,
    text: str,
    fragments: list[str],
) -> None:
    for fragment in fragments:
        if fragment not in text:
            errors.append(f"{label} must contain {fragment!r}")


def _expect(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _raise_if_errors(title: str, errors: list[str]) -> None:
    if errors:
        raise SystemExit(title + ":\n" + "\n".join(f"- {error}" for error in errors))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
