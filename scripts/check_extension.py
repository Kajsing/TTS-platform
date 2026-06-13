from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = REPO_ROOT / "apps" / "chrome_extension"
MANIFEST_PATH = EXTENSION_ROOT / "manifest.json"


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
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


def verify_extension_wiring() -> None:
    required_fragments = {
        EXTENSION_ROOT / "src" / "popup.html": ['id="resume-page"', 'id="onboarding-status"'],
        EXTENSION_ROOT / "src" / "popup.js": [
            '"tts-extension:resume-page"',
            "formatOnboardingStatus",
            "formatPageCapture",
            "checklistLine",
        ],
        EXTENSION_ROOT / "src" / "background.js": [
            '"tts-extension:resume-page"',
            "pageCapture",
            "sanitizePageCaptureMeta",
            "resolveResumeTextChunkIndex",
            "startTextChunkIndex",
        ],
        EXTENSION_ROOT / "src" / "content-script.js": [
            "getPageCapture",
            "extractReadableText(anchorElement, 1000).text",
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


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
