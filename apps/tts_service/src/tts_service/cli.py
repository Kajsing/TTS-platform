from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlparse

import httpx
import websockets
from tts_core.audio import encode_wav_pcm16


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    token = args.token or os.environ.get("TTS_PLATFORM_TOKEN")
    base_url = args.base_url.rstrip("/")

    try:
        if args.command == "health":
            _print_json(_get_json(f"{base_url}/v1/health"))
            return

        if args.command == "list-voices":
            _print_json(_get_json(f"{base_url}/v1/voices"))
            return

        if args.command == "save":
            _require_token(token, command="save")
            _save_audio(
                base_url=base_url,
                token=token,
                text=args.text,
                voice=args.voice,
                out_path=Path(args.out),
            )
            return

        if args.command == "say":
            _require_token(token, command="say")
            output_path = (
                Path(args.out)
                if args.out
                else Path(tempfile.gettempdir()) / "tts-platform-say.wav"
            )
            _save_audio(
                base_url=base_url,
                token=token,
                text=args.text,
                voice=args.voice,
                out_path=output_path,
            )
            _play_or_report(output_path)
            return

        if args.command == "stream":
            _require_token(token, command="stream")
            asyncio.run(
                _stream_to_wav(
                    base_url=base_url,
                    token=token,
                    text=args.text,
                    voice=args.voice,
                    out_path=Path(args.out),
                )
            )
            return

        if args.command == "rotate-token":
            _require_token(token, command="rotate-token")
            _print_json(
                _post_json(
                    f"{base_url}/v1/auth/rotate",
                    token=token,
                    payload=None,
                )
            )
            return

        if args.command == "job-status":
            _require_token(token, command="job-status")
            _print_json(
                _get_json(
                    f"{base_url}/v1/tts/jobs/{args.job_id}",
                    token=token,
                )
            )
            return

        if args.command == "job-result":
            _require_token(token, command="job-result")
            out_path = Path(args.out)
            _download_audio(
                f"{base_url}/v1/tts/jobs/{args.job_id}/result",
                token=token,
                out_path=out_path,
            )
            return

        if args.command == "job-cancel":
            _require_token(token, command="job-cancel")
            _print_json(
                _delete_json(
                    f"{base_url}/v1/tts/jobs/{args.job_id}",
                    token=token,
                )
            )
            return

        if args.command == "catalog-list":
            catalog, _ = _load_model_catalog(args.catalog)
            models = _catalog_models(catalog)
            _print_json({"models": models})
            return

        if args.command == "model-install":
            installed = _install_model_from_catalog(
                catalog_source=args.catalog,
                model_id=args.model_id,
                models_root=Path(args.models_root),
                manifest_path=Path(args.manifest_path),
                overwrite=args.overwrite,
                activate=args.activate,
                config_path=Path(args.config_path),
            )
            _print_json(installed)
            return

        if args.command == "model-activate":
            activated = _activate_model(
                model_id=args.model_id,
                manifest_path=Path(args.manifest_path),
                config_path=Path(args.config_path),
            )
            _print_json(activated)
            return

        if args.command == "model-remove":
            removed = _remove_model(
                model_id=args.model_id,
                models_root=Path(args.models_root),
                manifest_path=Path(args.manifest_path),
            )
            _print_json(removed)
            return

        raise SystemExit(f"Unknown command: {args.command}")
    except httpx.HTTPStatusError as exc:
        _handle_http_error(exc)
    except websockets.WebSocketException as exc:
        raise SystemExit(f"WebSocket error: {exc}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tts")
    parser.add_argument("--base-url", default="http://127.0.0.1:7777")
    parser.add_argument("--token", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health")
    subparsers.add_parser("list-voices")
    subparsers.add_parser("rotate-token")

    save_parser = subparsers.add_parser("save")
    save_parser.add_argument("text")
    save_parser.add_argument("--voice", default=None)
    save_parser.add_argument("--out", required=True)

    say_parser = subparsers.add_parser("say")
    say_parser.add_argument("text")
    say_parser.add_argument("--voice", default=None)
    say_parser.add_argument("--out", default=None)

    stream_parser = subparsers.add_parser("stream")
    stream_parser.add_argument("text")
    stream_parser.add_argument("--voice", default=None)
    stream_parser.add_argument("--out", required=True)

    job_status_parser = subparsers.add_parser("job-status")
    job_status_parser.add_argument("job_id")

    job_result_parser = subparsers.add_parser("job-result")
    job_result_parser.add_argument("job_id")
    job_result_parser.add_argument("--out", required=True)

    job_cancel_parser = subparsers.add_parser("job-cancel")
    job_cancel_parser.add_argument("job_id")

    catalog_list_parser = subparsers.add_parser("catalog-list")
    catalog_list_parser.add_argument("--catalog", required=True)

    model_install_parser = subparsers.add_parser("model-install")
    model_install_parser.add_argument("model_id")
    model_install_parser.add_argument("--catalog", required=True)
    model_install_parser.add_argument("--models-root", default="models/voices")
    model_install_parser.add_argument("--manifest-path", default="models/MANIFEST.json")
    model_install_parser.add_argument("--config-path", default="config/config.toml")
    model_install_parser.add_argument(
        "--activate",
        action="store_true",
        help="Set the installed model as config/config.toml [tts].default_voice.",
    )
    model_install_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an already installed model directory and overwrite manifest entry.",
    )

    model_activate_parser = subparsers.add_parser("model-activate")
    model_activate_parser.add_argument("model_id")
    model_activate_parser.add_argument("--manifest-path", default="models/MANIFEST.json")
    model_activate_parser.add_argument("--config-path", default="config/config.toml")

    model_remove_parser = subparsers.add_parser("model-remove")
    model_remove_parser.add_argument("model_id")
    model_remove_parser.add_argument("--models-root", default="models/voices")
    model_remove_parser.add_argument("--manifest-path", default="models/MANIFEST.json")

    return parser


def _headers(token: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url: str, *, token: str | None = None) -> dict[str, object]:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=_headers(token))
        response.raise_for_status()
        return response.json()


def _post_json(
    url: str,
    *,
    token: str | None,
    payload: dict[str, object] | None,
) -> dict[str, object]:
    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, json=payload, headers=_headers(token))
        response.raise_for_status()
        return response.json()


def _delete_json(url: str, *, token: str | None) -> dict[str, object]:
    with httpx.Client(timeout=60.0) as client:
        response = client.delete(url, headers=_headers(token))
        response.raise_for_status()
        return response.json()


def _download_audio(url: str, *, token: str | None, out_path: Path) -> None:
    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=_headers(token))
        response.raise_for_status()
    out_path.write_bytes(response.content)
    print(out_path)


def _save_audio(
    *,
    base_url: str,
    token: str | None,
    text: str,
    voice: str | None,
    out_path: Path,
) -> None:
    payload = {"text": text}
    if voice:
        payload["voice"] = voice

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{base_url}/v1/tts",
            json=payload,
            headers=_headers(token),
        )
        response.raise_for_status()

    out_path.write_bytes(response.content)
    print(out_path)


async def _stream_to_wav(
    *,
    base_url: str,
    token: str | None,
    text: str,
    voice: str | None,
    out_path: Path,
) -> None:
    ws_url = _to_ws_url(base_url) + "/v1/tts/stream"
    headers = _headers(token)
    pcm_frames = bytearray()
    sample_rate_hz = 24000
    channels = 1

    async with websockets.connect(ws_url, additional_headers=headers) as websocket:
        payload = {"text": text}
        if voice:
            payload["voice"] = voice
        await websocket.send(json.dumps({"type": "start", "payload": payload}))

        while True:
            message = await websocket.recv()
            if isinstance(message, bytes):
                pcm_frames.extend(message)
                continue

            event = json.loads(message)
            if event["type"] == "started":
                sample_rate_hz = event["sample_rate_hz"]
                channels = event["channels"]
                continue
            if event["type"] == "error":
                raise SystemExit(json.dumps(event["error"], indent=2, sort_keys=True))
            if event["type"] in {"done", "cancelled"}:
                break

    out_path.write_bytes(
        encode_wav_pcm16(
            bytes(pcm_frames),
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )
    )
    print(out_path)


def _to_ws_url(base_url: str) -> str:
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://") :]
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://") :]
    return base_url


def _play_or_report(audio_path: Path) -> None:
    for command in ("ffplay", "aplay", "paplay"):
        executable = shutil.which(command)
        if executable is None:
            continue
        args = {
            "ffplay": [executable, "-nodisp", "-autoexit", str(audio_path)],
            "aplay": [executable, str(audio_path)],
            "paplay": [executable, str(audio_path)],
        }[command]
        subprocess.run(args, check=False)
        return
    print(audio_path)


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _handle_http_error(exc: httpx.HTTPStatusError) -> None:
    try:
        payload = exc.response.json()
    except ValueError:
        raise SystemExit(f"HTTP {exc.response.status_code}: {exc.response.text}") from exc

    if isinstance(payload, dict) and "error" in payload:
        raise SystemExit(json.dumps(payload["error"], indent=2, sort_keys=True)) from exc
    raise SystemExit(json.dumps(payload, indent=2, sort_keys=True)) from exc


def _require_token(token: str | None, *, command: str) -> None:
    if token:
        return
    raise SystemExit(
        f"The '{command}' command requires a token. Use --token or set TTS_PLATFORM_TOKEN."
    )


def _load_model_catalog(catalog_source: str) -> tuple[dict[str, object], Path | None]:
    parsed = urlparse(catalog_source)
    if parsed.scheme in {"http", "https"}:
        with httpx.Client(timeout=60.0) as client:
            response = client.get(catalog_source)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise SystemExit("Catalog root must be a JSON object.")
        return payload, None

    catalog_path = Path(catalog_source).expanduser().resolve()
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("Catalog root must be a JSON object.")
    return payload, catalog_path


def _catalog_models(catalog_payload: dict[str, object]) -> list[dict[str, object]]:
    raw_models = catalog_payload.get("models", [])
    if not isinstance(raw_models, list):
        raise SystemExit("Catalog field 'models' must be a list.")
    models: list[dict[str, object]] = []
    for index, raw_model in enumerate(raw_models):
        if not isinstance(raw_model, dict):
            raise SystemExit(f"Catalog model entry at index {index} must be an object.")
        if "id" not in raw_model:
            raise SystemExit(f"Catalog model entry at index {index} is missing 'id'.")
        models.append(dict(raw_model))
    return models


def _install_model_from_catalog(
    *,
    catalog_source: str,
    model_id: str,
    models_root: Path,
    manifest_path: Path,
    overwrite: bool,
    activate: bool = False,
    config_path: Path | None = None,
) -> dict[str, object]:
    catalog_payload, catalog_path = _load_model_catalog(catalog_source)
    models = _catalog_models(catalog_payload)
    model = next((candidate for candidate in models if candidate.get("id") == model_id), None)
    if model is None:
        raise SystemExit(f"Model '{model_id}' was not found in catalog.")

    artifact_url = str(model.get("artifact_url", "")).strip()
    if not artifact_url:
        raise SystemExit(f"Catalog model '{model_id}' is missing artifact_url.")
    artifact_bytes = _read_artifact_bytes(artifact_url=artifact_url, catalog_path=catalog_path)

    expected_sha = str(model.get("artifact_sha256", "")).strip().lower()
    checksum_verified = False
    if expected_sha:
        actual_sha = hashlib.sha256(artifact_bytes).hexdigest().lower()
        if actual_sha != expected_sha:
            raise SystemExit(
                f"Checksum mismatch for '{model_id}'. expected={expected_sha} actual={actual_sha}"
            )
        checksum_verified = True

    install_dir = models_root / model_id
    if install_dir.exists():
        if not overwrite:
            raise SystemExit(
                f"Model directory already exists: {install_dir}. Use --overwrite to replace it."
            )

    models_root.mkdir(parents=True, exist_ok=True)
    temp_install_dir: Path | None = Path(
        tempfile.mkdtemp(prefix=f".{model_id}.", dir=models_root)
    )
    try:
        _extract_zip(artifact_bytes=artifact_bytes, out_dir=temp_install_dir)
        if install_dir.exists():
            shutil.rmtree(install_dir)
        temp_install_dir.rename(install_dir)
        temp_install_dir = None
    finally:
        if temp_install_dir is not None and temp_install_dir.exists():
            shutil.rmtree(temp_install_dir)

    installed_files = sorted(
        str(path.relative_to(install_dir)).replace("\\", "/")
        for path in install_dir.rglob("*")
        if path.is_file()
    )
    manifest_entry = _build_manifest_voice_entry(model_id=model_id, model=model)
    _upsert_manifest_entry(manifest_path=manifest_path, entry=manifest_entry)

    result: dict[str, object] = {
        "installed_model": model_id,
        "install_dir": str(install_dir),
        "manifest_path": str(manifest_path),
        "files_installed": len(installed_files),
        "checksum_verified": checksum_verified,
        "next_steps": [
            f"tts model-activate {model_id}",
            "restart the local service if it is already running",
            "tts list-voices",
        ],
    }
    if not checksum_verified:
        result["warning"] = "Catalog entry has no artifact_sha256; use only trusted artifacts."

    if activate:
        resolved_config_path = config_path or Path("config/config.toml")
        activation = _activate_model(
            model_id=model_id,
            manifest_path=manifest_path,
            config_path=resolved_config_path,
        )
        result["activated_model"] = activation["activated_model"]
        result["config_path"] = activation["config_path"]
        result["next_steps"] = [
            "restart the local service if it is already running",
            "tts list-voices",
        ]

    return result


def _read_artifact_bytes(*, artifact_url: str, catalog_path: Path | None) -> bytes:
    parsed = urlparse(artifact_url)
    if parsed.scheme in {"http", "https"}:
        with httpx.Client(timeout=120.0) as client:
            response = client.get(artifact_url)
            response.raise_for_status()
            return response.content

    artifact_path = Path(artifact_url).expanduser()
    if not artifact_path.is_absolute() and catalog_path is not None:
        artifact_path = (catalog_path.parent / artifact_path).resolve()
    return artifact_path.read_bytes()


def _extract_zip(*, artifact_bytes: bytes, out_dir: Path) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(artifact_bytes)) as archive:
            _assert_safe_archive_members(archive=archive, out_dir=out_dir)
            archive.extractall(out_dir)
    except zipfile.BadZipFile as exc:
        raise SystemExit(f"Model artifact is not a valid zip file: {exc}") from exc


def _assert_safe_archive_members(*, archive: zipfile.ZipFile, out_dir: Path) -> None:
    out_dir_resolved = out_dir.resolve()
    for member in archive.infolist():
        posix_member_path = PurePosixPath(member.filename)
        windows_member_path = PureWindowsPath(member.filename)
        if (
            posix_member_path.is_absolute()
            or windows_member_path.is_absolute()
            or windows_member_path.drive
        ):
            raise SystemExit(
                f"Model artifact contains absolute path entry: {member.filename!r}"
            )
        if ".." in posix_member_path.parts or ".." in windows_member_path.parts:
            raise SystemExit(
                f"Model artifact contains unsafe path traversal entry: {member.filename!r}"
            )
        member_path = Path(*posix_member_path.parts)
        destination = (out_dir_resolved / member_path).resolve()
        if destination != out_dir_resolved and out_dir_resolved not in destination.parents:
            raise SystemExit(
                f"Model artifact contains unsafe path traversal entry: {member.filename!r}"
            )


def _build_manifest_voice_entry(*, model_id: str, model: dict[str, object]) -> dict[str, object]:
    source = f"models/voices/{model_id}"
    capabilities = model.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise SystemExit(f"Catalog model '{model_id}' has invalid capabilities.")
    backend_raw = model.get("backend", {})
    if backend_raw and not isinstance(backend_raw, dict):
        raise SystemExit(f"Catalog model '{model_id}' has invalid backend config.")
    backend = _rewrite_backend_paths(source=source, backend=dict(backend_raw))

    entry: dict[str, object] = {
        "id": model_id,
        "name": str(model.get("name", model_id)),
        "engine": str(model.get("engine", "sherpa_onnx")),
        "language": str(model.get("language", "en")),
        "sample_rate_hz": int(model.get("sample_rate_hz", 24000)),
        "license": str(model.get("license", "unknown")),
        "source": source,
        "quality_tier": str(model.get("quality_tier", "unknown")),
        "latency_tier": str(model.get("latency_tier", "unknown")),
        "tags": (
            [str(tag) for tag in model.get("tags", [])]
            if isinstance(model.get("tags"), list)
            else []
        ),
        "capabilities": {
            "supports_pitch": bool(capabilities.get("supports_pitch", False)),
            "supports_streaming": bool(capabilities.get("supports_streaming", False)),
            "supports_multi_speaker": bool(capabilities.get("supports_multi_speaker", False)),
        },
    }
    if backend:
        entry["backend"] = backend
    return entry


def _rewrite_backend_paths(*, source: str, backend: dict[str, object]) -> dict[str, object]:
    path_keys = {
        "model",
        "tokens",
        "data_dir",
        "lexicon",
        "voices",
        "acoustic_model",
        "vocoder",
    }
    list_path_keys = {"rule_fsts"}
    rewritten: dict[str, object] = {}
    for key, value in backend.items():
        if key in path_keys and isinstance(value, str):
            rewritten[key] = value if value.startswith("models/") else f"{source}/{value}"
            continue
        if key in list_path_keys and isinstance(value, list):
            rewritten[key] = [
                item if isinstance(item, str) and item.startswith("models/") else f"{source}/{item}"
                for item in value
            ]
            continue
        rewritten[key] = value
    return rewritten


def _upsert_manifest_entry(*, manifest_path: Path, entry: dict[str, object]) -> None:
    payload: dict[str, object]
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SystemExit("Manifest root must be a JSON object.")
    else:
        payload = {"version": 1, "voices": []}

    if int(payload.get("version", 1)) != 1:
        raise SystemExit(f"Unsupported manifest version: {payload.get('version')!r}")

    voices = payload.get("voices", [])
    if not isinstance(voices, list):
        raise SystemExit("Manifest field 'voices' must be a list.")
    filtered = [
        voice
        for voice in voices
        if isinstance(voice, dict) and str(voice.get("id", "")).strip() != str(entry["id"])
    ]
    filtered.append(entry)
    payload["voices"] = filtered
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _activate_model(*, model_id: str, manifest_path: Path, config_path: Path) -> dict[str, object]:
    if not _manifest_contains_voice(manifest_path=manifest_path, model_id=model_id):
        raise SystemExit(f"Model '{model_id}' was not found in manifest: {manifest_path}")

    _set_default_voice_in_config(config_path=config_path, model_id=model_id)
    return {
        "activated_model": model_id,
        "config_path": str(config_path),
        "manifest_path": str(manifest_path),
    }


def _manifest_contains_voice(*, manifest_path: Path, model_id: str) -> bool:
    if not manifest_path.exists():
        raise SystemExit(f"Manifest does not exist: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("Manifest root must be a JSON object.")
    if int(payload.get("version", 1)) != 1:
        raise SystemExit(f"Unsupported manifest version: {payload.get('version')!r}")
    voices = payload.get("voices", [])
    if not isinstance(voices, list):
        raise SystemExit("Manifest field 'voices' must be a list.")
    return any(
        isinstance(voice, dict) and str(voice.get("id", "")).strip() == model_id
        for voice in voices
    )


def _set_default_voice_in_config(*, config_path: Path, model_id: str) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    default_voice_line = f"default_voice = {_toml_string(model_id)}"

    if not config_path.exists():
        config_path.write_text(f"[tts]\n{default_voice_line}\n", encoding="utf-8")
        return

    text = config_path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    tts_section_index = _find_toml_table(lines, "tts")

    if tts_section_index is None:
        prefix = text
        if prefix and not prefix.endswith(("\n", "\r")):
            prefix += newline
        if prefix:
            prefix += newline
        config_path.write_text(
            f"{prefix}[tts]{newline}{default_voice_line}{newline}",
            encoding="utf-8",
        )
        return

    section_end = _find_next_toml_table(lines, start=tts_section_index + 1)
    default_voice_pattern = re.compile(r"^(\s*)default_voice\s*=")
    for index in range(tts_section_index + 1, section_end):
        match = default_voice_pattern.match(lines[index])
        if match:
            lines[index] = f"{match.group(1)}{default_voice_line}"
            _write_toml_lines(config_path=config_path, lines=lines, newline=newline)
            return

    lines.insert(tts_section_index + 1, default_voice_line)
    _write_toml_lines(config_path=config_path, lines=lines, newline=newline)


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _find_toml_table(lines: list[str], table_name: str) -> int | None:
    expected = f"[{table_name}]"
    for index, line in enumerate(lines):
        if line.strip() == expected:
            return index
    return None


def _find_next_toml_table(lines: list[str], *, start: int) -> int:
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            return index
    return len(lines)


def _write_toml_lines(*, config_path: Path, lines: list[str], newline: str) -> None:
    config_path.write_text(newline.join(lines) + newline, encoding="utf-8")


def _remove_model(*, model_id: str, models_root: Path, manifest_path: Path) -> dict[str, object]:
    install_dir = models_root / model_id
    removed_files = False
    if install_dir.exists():
        shutil.rmtree(install_dir)
        removed_files = True

    removed_manifest_entry = False
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SystemExit("Manifest root must be a JSON object.")
        voices = payload.get("voices", [])
        if not isinstance(voices, list):
            raise SystemExit("Manifest field 'voices' must be a list.")
        updated_voices = [
            voice
            for voice in voices
            if not (isinstance(voice, dict) and str(voice.get("id", "")).strip() == model_id)
        ]
        removed_manifest_entry = len(updated_voices) != len(voices)
        if removed_manifest_entry:
            payload["voices"] = updated_voices
            manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return {
        "model_id": model_id,
        "removed_files": removed_files,
        "removed_manifest_entry": removed_manifest_entry,
    }
