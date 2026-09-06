"""Bounded local JSON-lines bridge for Service Center model management.

This is not a network server. It exposes the repository's catalog,
non-overwriting installation and deferred service-default selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TextIO
from urllib.parse import urlparse

from . import cli
from .model_defaults import config_bytes, save_default
from .model_installation import ModelInstallCancelled, ModelInstallControl, manifest_lock

CONTRACT_VERSION = 1
MAX_METADATA_BYTES = 2 * 1024 * 1024


def fingerprint(data: bytes | None) -> str:
    return hashlib.sha256(data if data is not None else b"<missing>").hexdigest()


def metadata(path: Path, *, missing: object = None) -> tuple[object, str]:
    try:
        with path.open("rb") as source:
            data = source.read(MAX_METADATA_BYTES + 1)
    except FileNotFoundError:
        return missing, fingerprint(None)
    if len(data) > MAX_METADATA_BYTES:
        raise ValueError("Model metadata exceeds the supported size limit.")
    return json.loads(data), fingerprint(data)


def _web_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None
    return value


def inventory(repo_root: Path) -> dict[str, object]:
    root = repo_root.resolve()
    manifest, manifest_digest = metadata(
        root / "models" / "MANIFEST.json", missing={"version": 1, "voices": []}
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != 1
        or not isinstance(manifest.get("voices"), list)
    ):
        raise ValueError("The installed voice manifest is invalid. It was not changed.")
    voices = manifest["voices"]
    if len(voices) > 2048 or any(not isinstance(voice, dict) for voice in voices):
        raise ValueError("The installed voice manifest contains unsupported entries.")
    catalog, catalog_digest = metadata(
        root / cli.DEFAULT_MODEL_CATALOG_PATH, missing={"version": 1, "models": []}
    )
    if not isinstance(catalog, dict):
        raise ValueError("The model catalog is invalid.")
    models = cli._catalog_models(catalog)
    if len(models) > 512:
        raise ValueError("The model catalog contains too many packages.")
    config_path = root / "config" / "config.toml"
    config_snapshot = config_bytes(config_path)
    config = cli._inspect_config_for_model_check(config_path)
    if config_bytes(config_path) != config_snapshot:
        raise ValueError("The local configuration changed while reading it. Refresh the library.")
    default = config.get("default_voice")
    installed: list[dict[str, object]] = []
    for voice in voices:
        voice_id = str(voice.get("id", ""))
        checks = cli._inspect_backend_for_model_check(
            repo_root=root, model_id=voice_id, voice=voice
        )
        installed.append(
            {
                "id": voice_id,
                "name": str(voice.get("name", voice_id)),
                "language": str(voice.get("language", "unknown")),
                "family": checks.get("model_type") or "unknown",
                "license": str(voice.get("license", "unknown")),
                "package_source": str(voice.get("source", "")),
                "assets_present": checks.get("assets_ready") is True,
                "is_configured_default": voice_id == default,
            }
        )
    installed_ids = {str(voice.get("id", "")) for voice in voices}
    packages: list[dict[str, object]] = []
    seen: set[str] = set()
    for model in models:
        model_id = str(model.get("id", ""))
        reason: str | None = None
        try:
            entries = cli._build_manifest_voice_entries(model_id=model_id, model=model)
        except (SystemExit, ValueError, TypeError):
            entries = []
            reason = "Invalid package/voice definition."
        if model_id in seen:
            raise ValueError(
                "Duplicate package IDs in the local catalog; review it before installing."
            )
        seen.add(model_id)
        summary = cli._catalog_model_summary(model)
        family = (
            model.get("backend", {}).get("model_type")
            if isinstance(model.get("backend"), dict)
            else None
        )
        if model.get("engine", "sherpa_onnx") != "sherpa_onnx" or family not in {"vits", "kokoro"}:
            reason = "This package is outside the supported Piper/Kokoro library."
        if not re.fullmatch(r"[a-fA-F0-9]{64}", str(model.get("artifact_sha256", ""))):
            reason = "A verified SHA-256 checksum is required."
        if (
            not _web_url(model.get("license_url"))
            or not _web_url(model.get("source_url"))
            or str(model.get("license", "unknown")).lower() in {"unknown", "", "none"}
        ):
            reason = "Voice-specific license and source details are required."
        if not _web_url(model.get("artifact_url")):
            reason = "This catalog entry has no supported download URL."
        present = any(str(entry["id"]) in installed_ids for entry in entries)
        directory_present = False
        if cli._is_safe_model_id(model_id):
            directory_present = (root / "models" / "voices" / model_id).exists()
        if present or directory_present:
            reason = (
                "Already installed or an existing package directory needs review. "
                "Nothing will be overwritten."
            )
        packages.append(
            {
                "id": model_id,
                "name": summary["name"],
                "language": summary["language"],
                "family": family or "unknown",
                "size_bytes": summary["artifact_size_bytes"],
                "license": summary["license"],
                "license_url": _web_url(model.get("license_url")),
                "source_url": _web_url(model.get("source_url")),
                "voices": [
                    {"id": entry["id"], "name": entry["name"], "language": entry["language"]}
                    for entry in entries
                ],
                "installed": present,
                "can_install": reason is None,
                "unavailable_reason": reason,
                "install_note": str(model.get("install_note", ""))[:2048],
            }
        )
    return {
        "catalog_fingerprint": catalog_digest,
        "manifest_fingerprint": manifest_digest,
        "configured_default": default,
        "config_valid": config.get("valid") is True,
        "config_fingerprint": fingerprint(config_snapshot),
        "installed_voices": installed,
        "packages": packages,
    }


def install_package(
    repo_root: Path,
    package_id: str,
    catalog_fingerprint: str,
    accepted_license: bool,
    control: ModelInstallControl,
) -> dict[str, object]:
    if not accepted_license:
        raise ValueError("Review and accept this package's voice license before installing.")
    current = inventory(repo_root)
    if catalog_fingerprint != current["catalog_fingerprint"]:
        raise ValueError("The catalog changed. Refresh and review the package/license again.")
    package = next(
        (package for package in current["packages"] if package["id"] == package_id), None
    )
    if package is None or package["can_install"] is not True:
        raise ValueError(
            "The selected package cannot be installed without replacing existing data."
        )
    root = repo_root.resolve()
    catalog, digest = metadata(root / cli.DEFAULT_MODEL_CATALOG_PATH)
    if digest != catalog_fingerprint or not isinstance(catalog, dict):
        raise ValueError("The catalog changed before installation. Review the package again.")
    control.require_assets = True
    result = cli._install_model_from_catalog(
        catalog_source=str(root / cli.DEFAULT_MODEL_CATALOG_PATH),
        model_id=package_id,
        models_root=root / "models" / "voices",
        manifest_path=root / "models" / "MANIFEST.json",
        overwrite=False,
        activate=False,
        control=control,
        catalog_snapshot=(catalog, root / cli.DEFAULT_MODEL_CATALOG_PATH),
    )
    return {
        "package_id": package_id,
        "voice_ids": result["installed_voice_ids"],
        "checksum_verified": result["checksum_verified"],
        "activation": "restart_required",
    }


def set_default_voice(
    repo_root: Path,
    voice_id: str,
    manifest_fingerprint: str,
    config_fingerprint: str,
    control: ModelInstallControl,
) -> dict[str, object]:
    root = repo_root.resolve()
    with manifest_lock(root / "models" / "MANIFEST.json"):
        current = inventory(root)
        if (
            not current["config_valid"]
            or current["manifest_fingerprint"] != manifest_fingerprint
            or current["config_fingerprint"] != config_fingerprint
        ):
            raise ValueError("The reviewed configuration or voice list changed. Refresh first.")
        selected = [voice for voice in current["installed_voices"] if voice["id"] == voice_id]
        if (
            not cli._is_safe_model_id(voice_id)
            or len(selected) != 1
            or selected[0]["assets_present"] is not True
        ):
            raise ValueError("Select one installed voice whose files are present.")
        path = root / "config" / "config.toml"
        original = config_bytes(path)
        if original is None or fingerprint(original) != config_fingerprint:
            raise ValueError("The configuration changed before saving. Refresh first.")
        control.check()  # The short atomic commit is non-cancellable after this point.
        save_default(path, original, voice_id)
    return {"voice_id": voice_id, "activation": "restart_required"}


def watch_cancel(stream: TextIO, cancelled: threading.Event) -> None:
    # Pipe closure also cancels staging if the desktop disappears. Never kill a
    # helper during its non-cancellable commit; it owns cleanup and final outcome.
    while True:
        line = stream.readline(4097)
        if not line or len(line) > 4096:
            cancelled.set()
            return
        try:
            request = json.loads(line)
        except ValueError:
            cancelled.set()
            return
        if request == {"cancel": True}:
            cancelled.set()
            return


def run(
    args: argparse.Namespace, send: Callable[[dict[str, object]], None], cancelled: threading.Event
) -> None:
    root = Path(args.repo_root).resolve()
    if args.command == "list":
        send({"event": "result", "data": inventory(root)})
    elif args.command == "set-default":
        result = set_default_voice(
            root,
            args.voice_id,
            args.manifest_fingerprint,
            args.config_fingerprint,
            ModelInstallControl(cancelled=cancelled.is_set),
        )
        send({"event": "result", "data": result})
    else:
        control = ModelInstallControl(
            cancelled=cancelled.is_set, progress=lambda event: send({"event": "progress", **event})
        )
        result = install_package(
            root, args.package_id, args.catalog_fingerprint, args.accept_license, control
        )
        send({"event": "result", "data": result})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "install", "set-default"])
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--package-id", default="")
    parser.add_argument("--catalog-fingerprint", default="")
    parser.add_argument("--accept-license", action="store_true")
    parser.add_argument("--voice-id", default="")
    parser.add_argument("--manifest-fingerprint", default="")
    parser.add_argument("--config-fingerprint", default="")
    args = parser.parse_args(argv)
    cancelled = threading.Event()
    phase = "default" if args.command == "set-default" else "metadata"

    def send(event: dict[str, object]) -> None:
        nonlocal phase
        if event.get("event") == "progress":
            phase = str(event["phase"])
        print(json.dumps({"contract_version": CONTRACT_VERSION, **event}), flush=True)

    if args.command != "list":
        threading.Thread(target=watch_cancel, args=(sys.stdin, cancelled), daemon=True).start()
    try:
        run(args, send, cancelled)
        return 0
    except ModelInstallCancelled:
        send(
            {
                "event": "cancelled",
                "message": (
                    "Voice operation cancelled before commit. "
                    "Existing settings and voices are unchanged."
                ),
            }
        )
        return 2
    except BrokenPipeError:
        return 1  # The owner disappeared. It must refresh actual state on next open.
    except (Exception, SystemExit):
        # No raw config, command lines, signed URLs or credentials in UI/logs.
        messages = {
            "default": (
                "The service default could not be confirmed. Refresh before retrying. "
                "Check the installed voice, config permissions and conventional [tts] layout. "
                "Any private .config.toml.*.recovery file is kept for recovery."
            ),
            "metadata": (
                "Package or license review is no longer valid. "
                "Refresh the library before trying again."
            ),
            "resolving": "The selected package conflicts with existing files or registry entries.",
            "downloading": "The download failed. Check availability, connection and disk space.",
            "verifying": (
                "The downloaded package failed its SHA-256 verification. It was not installed."
            ),
            "extracting": (
                "The package could not be safely unpacked or required voice assets are missing."
            ),
            "committing": (
                "Installation could not be confirmed. Refresh the library before retrying; "
                "check disk space and permissions."
            ),
        }
        send(
            {
                "event": "failed",
                "phase": phase,
                "message": messages.get(
                    phase, "Model operation failed. Refresh to inspect the actual state."
                ),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
