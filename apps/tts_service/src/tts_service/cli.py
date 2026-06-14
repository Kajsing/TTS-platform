from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urljoin, urlparse

import httpx
import websockets
from tts_core.audio import encode_wav_pcm16
from tts_core.backends.base import BackendNotReadyError
from tts_core.backends.sherpa_onnx import SherpaOnnxVoiceRuntimeConfig

from .auth import initialize_auth
from .config import SecurityConfig, load_config

DEFAULT_MODEL_CATALOG_PATH = "models/catalog.json"
REAL_RUNTIME_INSTALL_STEP = 'python -m pip install -e ".[real]"'
SHERPA_ONNX_INSTALL_STEP = "python -m pip install sherpa-onnx"
NUMPY_INSTALL_STEP = "python -m pip install numpy"


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

        if args.command == "setup-local":
            _print_json(
                _setup_local(
                    repo_root=Path(args.repo_root),
                    config_path=Path(args.config_path),
                    example_config_path=Path(args.example_config_path),
                    manifest_path=Path(args.manifest_path),
                )
            )
            return

        if args.command == "serve":
            _serve_local(
                repo_root=Path(args.repo_root),
                config_path=Path(args.config_path),
                host=args.host,
                port=args.port,
                allow_non_local_host=args.allow_non_local_host,
            )
            return

        if args.command == "extension-allow-origin":
            _print_json(
                _allow_extension_origin(
                    repo_root=Path(args.repo_root),
                    config_path=Path(args.config_path),
                    origin=args.origin,
                )
            )
            return

        if args.command == "catalog-list":
            catalog, _ = _load_model_catalog(args.catalog)
            _print_json(
                _build_catalog_list_payload(
                    catalog_payload=catalog,
                    catalog_source=args.catalog,
                )
            )
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
                progress=_emit_model_install_progress,
                allow_missing_checksum=args.allow_missing_checksum,
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

        if args.command == "model-list":
            _print_json(
                _list_models(
                    repo_root=Path(args.repo_root),
                    manifest_path=Path(args.manifest_path),
                    config_path=Path(args.config_path),
                )
            )
            return

        if args.command == "model-check":
            _print_json(
                _check_model_readiness(
                    model_id=args.model_id,
                    repo_root=Path(args.repo_root),
                    manifest_path=Path(args.manifest_path),
                    config_path=Path(args.config_path),
                )
            )
            return

        if args.command == "model-remove":
            removed = _remove_model(
                model_id=args.model_id,
                models_root=Path(args.models_root),
                manifest_path=Path(args.manifest_path),
                config_path=Path(args.config_path),
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

    setup_local_parser = subparsers.add_parser("setup-local")
    setup_local_parser.add_argument("--repo-root", default=".")
    setup_local_parser.add_argument("--config-path", default="config/config.toml")
    setup_local_parser.add_argument(
        "--example-config-path",
        default="config/config.example.toml",
    )
    setup_local_parser.add_argument("--manifest-path", default="models/MANIFEST.json")

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--repo-root", default=".")
    serve_parser.add_argument("--config-path", default="config/config.toml")
    serve_parser.add_argument("--host", default=None)
    serve_parser.add_argument("--port", type=int, default=None)
    serve_parser.add_argument(
        "--allow-non-local-host",
        action="store_true",
        help="Allow binding outside localhost. The default run path only allows loopback hosts.",
    )

    extension_allow_parser = subparsers.add_parser("extension-allow-origin")
    extension_allow_parser.add_argument("origin")
    extension_allow_parser.add_argument("--repo-root", default=".")
    extension_allow_parser.add_argument("--config-path", default="config/config.toml")

    catalog_list_parser = subparsers.add_parser("catalog-list")
    catalog_list_parser.add_argument("--catalog", default=DEFAULT_MODEL_CATALOG_PATH)

    model_install_parser = subparsers.add_parser("model-install")
    model_install_parser.add_argument("model_id")
    model_install_parser.add_argument("--catalog", default=DEFAULT_MODEL_CATALOG_PATH)
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
    model_install_parser.add_argument(
        "--allow-missing-checksum",
        action="store_true",
        help=(
            "Install a catalog artifact without artifact_sha256. Use only for trusted local "
            "artifacts; checksums are required by default."
        ),
    )

    model_activate_parser = subparsers.add_parser("model-activate")
    model_activate_parser.add_argument("model_id")
    model_activate_parser.add_argument("--manifest-path", default="models/MANIFEST.json")
    model_activate_parser.add_argument("--config-path", default="config/config.toml")

    model_list_parser = subparsers.add_parser("model-list")
    model_list_parser.add_argument("--repo-root", default=".")
    model_list_parser.add_argument("--manifest-path", default="models/MANIFEST.json")
    model_list_parser.add_argument("--config-path", default="config/config.toml")

    model_check_parser = subparsers.add_parser("model-check")
    model_check_parser.add_argument("model_id", nargs="?")
    model_check_parser.add_argument("--repo-root", default=".")
    model_check_parser.add_argument("--manifest-path", default="models/MANIFEST.json")
    model_check_parser.add_argument("--config-path", default="config/config.toml")

    model_remove_parser = subparsers.add_parser("model-remove")
    model_remove_parser.add_argument("model_id")
    model_remove_parser.add_argument("--models-root", default="models/voices")
    model_remove_parser.add_argument("--manifest-path", default="models/MANIFEST.json")
    model_remove_parser.add_argument("--config-path", default="config/config.toml")

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


def _emit_model_install_progress(message: str) -> None:
    print(f"[model-install] {message}", file=sys.stderr)


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


def _setup_local(
    *,
    repo_root: Path,
    config_path: Path,
    example_config_path: Path,
    manifest_path: Path,
) -> dict[str, object]:
    resolved_repo_root = repo_root.expanduser().resolve()
    resolved_config_path = _resolve_under_root(resolved_repo_root, config_path)
    resolved_example_config_path = _resolve_under_root(resolved_repo_root, example_config_path)
    resolved_manifest_path = _resolve_under_root(resolved_repo_root, manifest_path)

    config_created = False
    if not resolved_config_path.exists():
        if not resolved_example_config_path.exists():
            raise SystemExit(f"Example config does not exist: {resolved_example_config_path}")
        resolved_config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(resolved_example_config_path, resolved_config_path)
        config_created = True

    try:
        config = load_config(resolved_config_path, env={})
    except ValueError as exc:
        raise SystemExit(f"Config is invalid: {exc}") from exc

    try:
        auth_state = initialize_auth(config.auth, repo_root=resolved_repo_root)
    except ValueError as exc:
        raise SystemExit(f"Auth setup failed: {exc}") from exc

    manifest_status = _inspect_manifest(
        manifest_path=resolved_manifest_path,
        default_voice=config.tts.default_voice,
    )
    catalog_status = _inspect_catalog_for_model_check(resolved_repo_root)
    runtime_status = _inspect_runtime_for_model_check(
        {"backend_mode": config.backend.mode}
    )
    base_url = f"http://{config.server.host}:{config.server.port}"
    return {
        "repo_root": str(resolved_repo_root),
        "config_path": str(resolved_config_path),
        "config_created": config_created,
        "auth_enabled": auth_state.enabled,
        "token_file": str(auth_state.token_file),
        "token_created": auth_state.generated,
        "service": {
            "host": config.server.host,
            "port": config.server.port,
            "base_url": base_url,
        },
        "default_voice": config.tts.default_voice,
        "manifest": manifest_status,
        "catalog": catalog_status,
        "runtime": runtime_status,
        "next_steps": _setup_local_next_steps(
            config_created=config_created,
            token_created=auth_state.generated,
            default_voice_in_manifest=bool(manifest_status["default_voice_in_manifest"]),
            default_voice_has_backend_config=bool(
                manifest_status.get("default_voice_has_backend_config")
            ),
            default_voice=config.tts.default_voice,
            catalog_status=catalog_status,
            runtime_status=runtime_status,
        ),
    }


def _resolve_under_root(repo_root: Path, path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (repo_root / expanded).resolve()


def _inspect_manifest(*, manifest_path: Path, default_voice: str) -> dict[str, object]:
    if not manifest_path.exists():
        return {
            "path": str(manifest_path),
            "exists": False,
            "voice_count": 0,
            "default_voice_in_manifest": False,
        }

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("Manifest root must be a JSON object.")
    voices = payload.get("voices", [])
    if not isinstance(voices, list):
        raise SystemExit("Manifest field 'voices' must be a list.")
    voice_ids = [
        str(voice.get("id", "")).strip()
        for voice in voices
        if isinstance(voice, dict) and str(voice.get("id", "")).strip()
    ]
    matching_default_voice = next(
        (
            voice
            for voice in voices
            if isinstance(voice, dict)
            and str(voice.get("id", "")).strip() == default_voice
        ),
        None,
    )
    return {
        "path": str(manifest_path),
        "exists": True,
        "voice_count": len(voice_ids),
        "default_voice_in_manifest": default_voice in voice_ids,
        "default_voice_has_backend_config": (
            isinstance(matching_default_voice, dict)
            and isinstance(matching_default_voice.get("backend"), dict)
        ),
    }


def _setup_local_next_steps(
    *,
    config_created: bool,
    token_created: bool,
    default_voice_in_manifest: bool,
    default_voice_has_backend_config: bool,
    default_voice: str,
    catalog_status: dict[str, object],
    runtime_status: dict[str, object],
) -> list[str]:
    steps: list[str] = []
    install_step = _setup_local_model_install_step(
        default_voice=default_voice,
        default_voice_in_manifest=default_voice_in_manifest,
        default_voice_has_backend_config=default_voice_has_backend_config,
        catalog_status=catalog_status,
    )
    if install_step:
        steps.append(install_step)
    _append_sherpa_onnx_install_step(
        steps,
        runtime_status=runtime_status,
        real_output_expected=bool(install_step) or default_voice_has_backend_config,
    )
    steps.extend(
        [
            "tts extension-allow-origin <chrome-extension-origin>",
            "tts model-check",
            "tts serve",
            "tts health",
            "tts list-voices",
        ]
    )
    if config_created or token_created:
        steps.append("read config/token.txt when a protected client needs the bearer token")
    return steps


def _setup_local_model_install_step(
    *,
    default_voice: str,
    default_voice_in_manifest: bool,
    default_voice_has_backend_config: bool,
    catalog_status: dict[str, object],
) -> str | None:
    if default_voice_in_manifest and default_voice_has_backend_config:
        return None
    if default_voice_in_manifest:
        if not _catalog_can_suggest_default_voice(
            default_voice=default_voice,
            catalog_status=catalog_status,
        ):
            return None
        return _model_check_install_step(
            model_id=default_voice,
            catalog_status=catalog_status,
            overwrite=True,
        )
    if not _catalog_has_installable_model(catalog_status):
        return "tts model-install <model-id> --catalog <catalog> --activate"
    return _model_check_install_step(
        model_id="",
        catalog_status=catalog_status,
        overwrite=False,
    )


def _catalog_has_installable_model(catalog_status: dict[str, object]) -> bool:
    return any(
        str(candidate).strip()
        for candidate in catalog_status.get("installable_model_ids", [])
    )


def _catalog_can_suggest_default_voice(
    *,
    default_voice: str,
    catalog_status: dict[str, object],
) -> bool:
    installable_model_ids = [
        str(candidate).strip()
        for candidate in catalog_status.get("installable_model_ids", [])
        if str(candidate).strip()
    ]
    if default_voice in installable_model_ids:
        return True
    return bool(str(catalog_status.get("single_installable_model_id") or "").strip())


def _allow_extension_origin(
    *,
    repo_root: Path,
    config_path: Path,
    origin: str,
) -> dict[str, object]:
    resolved_repo_root = repo_root.expanduser().resolve()
    resolved_config_path = _resolve_under_root(resolved_repo_root, config_path)
    if not resolved_config_path.exists():
        raise SystemExit(
            f"Config does not exist: {resolved_config_path}. Run 'tts setup-local' first."
        )

    normalized_origin = _normalize_extension_origin_for_cli(origin)
    try:
        config = load_config(resolved_config_path, env={})
    except ValueError as exc:
        raise SystemExit(f"Config is invalid: {exc}") from exc

    allowed_origins = list(config.security.allowed_origins)
    added = normalized_origin not in allowed_origins
    if added:
        allowed_origins.append(normalized_origin)
        _set_allowed_origins_in_config(
            config_path=resolved_config_path,
            origins=allowed_origins,
        )

    return {
        "config_path": str(resolved_config_path),
        "origin": normalized_origin,
        "added": added,
        "allowed_origins": allowed_origins,
        "next_steps": [
            "restart the local service if it is already running",
            "save config/token.txt in the Chrome extension popup",
            "open the popup and refresh service health",
        ],
    }


def _normalize_extension_origin_for_cli(origin: str) -> str:
    try:
        normalized_origins = SecurityConfig.from_mapping(
            {"allowed_origins": [origin]}
        ).allowed_origins
    except ValueError as exc:
        raise SystemExit(f"Extension origin is invalid: {exc}") from exc
    if not normalized_origins:
        raise SystemExit("Extension origin must not be empty.")
    normalized_origin = normalized_origins[0]
    if not normalized_origin.startswith("chrome-extension://"):
        raise SystemExit("Extension origin must start with chrome-extension://")
    return normalized_origin


def _set_allowed_origins_in_config(*, config_path: Path, origins: list[str]) -> None:
    origins_line = (
        "allowed_origins = ["
        + ", ".join(_toml_string(origin) for origin in origins)
        + "]"
    )
    text = config_path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    security_section_index = _find_toml_table(lines, "security")

    if security_section_index is None:
        prefix = text
        if prefix and not prefix.endswith(("\n", "\r")):
            prefix += newline
        if prefix:
            prefix += newline
        config_path.write_text(
            f"{prefix}[security]{newline}{origins_line}{newline}",
            encoding="utf-8",
        )
        return

    section_end = _find_next_toml_table(lines, start=security_section_index + 1)
    allowed_origins_pattern = re.compile(r"^(\s*)allowed_origins\s*=")
    for index in range(security_section_index + 1, section_end):
        match = allowed_origins_pattern.match(lines[index])
        if match:
            if "[" in lines[index] and "]" not in lines[index]:
                raise SystemExit(
                    "security.allowed_origins must be a single-line TOML array before "
                    "this command can update it."
                )
            lines[index] = f"{match.group(1)}{origins_line}"
            _write_toml_lines(config_path=config_path, lines=lines, newline=newline)
            return

    lines.insert(security_section_index + 1, origins_line)
    _write_toml_lines(config_path=config_path, lines=lines, newline=newline)


def _serve_local(
    *,
    repo_root: Path,
    config_path: Path,
    host: str | None,
    port: int | None,
    allow_non_local_host: bool,
    uvicorn_run: Callable[..., None] | None = None,
) -> None:
    resolved_repo_root = repo_root.expanduser().resolve()
    resolved_config_path = _resolve_under_root(resolved_repo_root, config_path)
    if not resolved_config_path.exists():
        raise SystemExit(
            f"Config does not exist: {resolved_config_path}. Run 'tts setup-local' first."
        )

    try:
        config = load_config(resolved_config_path)
    except ValueError as exc:
        raise SystemExit(f"Config is invalid: {exc}") from exc

    resolved_host = host or config.server.host
    resolved_port = port if port is not None else config.server.port
    if resolved_port <= 0:
        raise SystemExit("server port must be positive")
    if not allow_non_local_host and not _is_loopback_host(resolved_host):
        raise SystemExit(
            "Refusing to bind outside localhost by default. "
            "Use --allow-non-local-host only for an intentional trusted-network setup."
        )

    from .main import create_app

    app = create_app(config=config, repo_root=resolved_repo_root)
    runner = uvicorn_run or _run_uvicorn
    print(
        f"[serve] starting local TTS service at http://{resolved_host}:{resolved_port}",
        file=sys.stderr,
    )
    runner(
        app,
        host=resolved_host,
        port=resolved_port,
        log_level=config.server.log_level,
        reload=False,
    )


def _is_loopback_host(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def _run_uvicorn(*args: object, **kwargs: object) -> None:
    import uvicorn

    uvicorn.run(*args, **kwargs)


CatalogLocation = Path | str


@dataclass(frozen=True)
class ArtifactFile:
    path: Path
    bytes: int


def _load_model_catalog(catalog_source: str) -> tuple[dict[str, object], CatalogLocation]:
    parsed = urlparse(catalog_source)
    if parsed.scheme in {"http", "https"}:
        with httpx.Client(timeout=60.0) as client:
            response = client.get(catalog_source)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise SystemExit("Catalog root must be a JSON object.")
        return payload, catalog_source

    catalog_path = Path(catalog_source).expanduser().resolve()
    if not catalog_path.is_file():
        raise SystemExit(
            f"Catalog does not exist: {catalog_path}. "
            f"Create {DEFAULT_MODEL_CATALOG_PATH} or pass --catalog <path-or-url>."
        )
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Catalog is not valid JSON: {catalog_path}: {exc}") from exc
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


def _build_catalog_list_payload(
    *,
    catalog_payload: dict[str, object],
    catalog_source: str,
) -> dict[str, object]:
    models = _catalog_models(catalog_payload)
    warnings = _catalog_warnings(models)
    installable_count = sum(
        1 for model in models if str(model.get("artifact_url", "")).strip()
    )
    checksum_count = sum(
        1 for model in models if str(model.get("artifact_sha256", "")).strip()
    )
    return {
        "catalog": {
            "source": catalog_source,
            "version": catalog_payload.get("version", "unknown"),
            "model_count": len(models),
            "installable_count": installable_count,
            "checksum_count": checksum_count,
        },
        "models": models,
        "model_summaries": [_catalog_model_summary(model) for model in models],
        "warnings": warnings,
        "next_steps": _catalog_next_steps(models=models, catalog_source=catalog_source),
    }


def _catalog_model_summary(model: dict[str, object]) -> dict[str, object]:
    model_id = str(model.get("id", "")).strip()
    artifact_url = str(model.get("artifact_url", "")).strip()
    checksum = str(model.get("artifact_sha256", "")).strip()
    artifact_size_bytes = _catalog_artifact_size_bytes(model.get("artifact_size_bytes"))
    return {
        "id": model_id,
        "name": str(model.get("name", model_id)),
        "language": str(model.get("language", "unknown")),
        "engine": str(model.get("engine", "sherpa_onnx")),
        "sample_rate_hz": model.get("sample_rate_hz", 24000),
        "license": str(model.get("license", "unknown")),
        "license_url": _catalog_optional_string(model.get("license_url")),
        "source_url": _catalog_optional_string(model.get("source_url")),
        "upstream_url": _catalog_optional_string(model.get("upstream_url")),
        "quality_tier": str(model.get("quality_tier", "unknown")),
        "latency_tier": str(model.get("latency_tier", "unknown")),
        "tags": _catalog_string_list(model.get("tags")),
        "capabilities": _catalog_capabilities(model.get("capabilities")),
        "installable": bool(artifact_url),
        "artifact_url": artifact_url or None,
        "artifact_size_bytes": artifact_size_bytes,
        "artifact_size_mib": _catalog_artifact_size_mib(artifact_size_bytes),
        "checksum": "sha256" if checksum else "missing",
    }


def _catalog_optional_string(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _catalog_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _catalog_capabilities(value: object) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    return {
        "supports_pitch": bool(value.get("supports_pitch", False)),
        "supports_streaming": bool(value.get("supports_streaming", False)),
        "supports_multi_speaker": bool(value.get("supports_multi_speaker", False)),
    }


def _catalog_artifact_size_bytes(value: object) -> int | None:
    if value is None:
        return None
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    return size if size >= 0 else None


def _catalog_artifact_size_mib(size_bytes: int | None) -> float | None:
    if size_bytes is None:
        return None
    return round(size_bytes / (1024 * 1024), 1)


def _catalog_warnings(models: list[dict[str, object]]) -> list[str]:
    warnings: list[str] = []
    seen_ids: set[str] = set()
    for index, model in enumerate(models):
        model_id = str(model.get("id", "")).strip()
        if model_id in seen_ids:
            warnings.append(
                f"Duplicate model id '{model_id}' at index {index}; install uses the first match."
            )
        seen_ids.add(model_id)
        if not str(model.get("artifact_url", "")).strip():
            warnings.append(
                f"Model '{model_id}' is missing artifact_url and cannot be installed."
            )
        if not str(model.get("artifact_sha256", "")).strip():
            warnings.append(
                f"Model '{model_id}' is missing artifact_sha256; installs cannot verify integrity."
            )
    return warnings


def _catalog_next_steps(
    *,
    models: list[dict[str, object]],
    catalog_source: str,
) -> list[str]:
    if not models:
        return []
    installable_models = [
        str(model.get("id", "")).strip()
        for model in models
        if str(model.get("artifact_url", "")).strip()
    ]
    if len(installable_models) == 1:
        model_ref = installable_models[0]
    else:
        model_ref = "<model-id>"
    catalog_argument = (
        ""
        if catalog_source == DEFAULT_MODEL_CATALOG_PATH
        else " --catalog <catalog>"
    )
    return [
        "review model_summaries for installable models and checksum coverage",
        f"tts model-install {model_ref}{catalog_argument} --activate",
    ]


def _install_model_from_catalog(
    *,
    catalog_source: str,
    model_id: str,
    models_root: Path,
    manifest_path: Path,
    overwrite: bool,
    activate: bool = False,
    config_path: Path | None = None,
    progress: Callable[[str], None] | None = None,
    allow_missing_checksum: bool = False,
) -> dict[str, object]:
    catalog_payload, catalog_location = _load_model_catalog(catalog_source)
    models = _catalog_models(catalog_payload)
    model = next((candidate for candidate in models if candidate.get("id") == model_id), None)
    if model is None:
        raise SystemExit(f"Model '{model_id}' was not found in catalog.")
    install_steps: list[dict[str, object]] = []
    _record_install_step(
        install_steps,
        step="resolve_catalog_model",
        status="completed",
        progress=progress,
        detail=model_id,
    )

    artifact_url = str(model.get("artifact_url", "")).strip()
    if not artifact_url:
        raise SystemExit(f"Catalog model '{model_id}' is missing artifact_url.")
    catalog_artifact_size_bytes = _catalog_artifact_size_bytes(
        model.get("artifact_size_bytes")
    )
    with tempfile.TemporaryDirectory(prefix=f"tts-platform-artifact-{model_id}-") as temp_dir:
        artifact = _load_artifact_file(
            artifact_url=artifact_url,
            catalog_location=catalog_location,
            destination=Path(temp_dir) / "artifact",
        )
        _record_install_step(
            install_steps,
            step="load_artifact",
            status="completed",
            progress=progress,
            bytes=artifact.bytes,
        )

        expected_sha = str(model.get("artifact_sha256", "")).strip().lower()
        checksum_verified = False
        if expected_sha:
            actual_sha = _sha256_file(artifact.path)
            if actual_sha != expected_sha:
                raise SystemExit(
                    f"Checksum mismatch for '{model_id}'. "
                    f"expected={expected_sha} actual={actual_sha}"
                )
            checksum_verified = True
            _record_install_step(
                install_steps,
                step="verify_checksum",
                status="completed",
                progress=progress,
                algorithm="sha256",
            )
        else:
            if not allow_missing_checksum:
                _record_install_step(
                    install_steps,
                    step="verify_checksum",
                    status="failed",
                    progress=progress,
                    reason="catalog entry has no artifact_sha256",
                )
                raise SystemExit(
                    f"Catalog model '{model_id}' is missing artifact_sha256. "
                    "Add artifact_sha256 to the catalog entry or pass "
                    "--allow-missing-checksum for a trusted local artifact."
                )
            _record_install_step(
                install_steps,
                step="verify_checksum",
                status="skipped",
                progress=progress,
                reason="allowed missing artifact_sha256 for trusted local artifact",
            )

        install_dir = models_root / model_id
        if install_dir.exists():
            if not overwrite:
                raise SystemExit(
                    f"Model directory already exists: {install_dir}. "
                    "Use --overwrite to replace it."
                )

        models_root.mkdir(parents=True, exist_ok=True)
        temp_install_dir: Path | None = Path(
            tempfile.mkdtemp(prefix=f".{model_id}.", dir=models_root)
        )
        try:
            _extract_model_artifact(artifact_path=artifact.path, out_dir=temp_install_dir)
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
    _record_install_step(
        install_steps,
        step="extract_artifact",
        status="completed",
        progress=progress,
        files_installed=len(installed_files),
    )
    catalog_artifact_size_matches = (
        None
        if catalog_artifact_size_bytes is None
        else catalog_artifact_size_bytes == artifact.bytes
    )
    manifest_entry = _build_manifest_voice_entry(model_id=model_id, model=model)
    _upsert_manifest_entry(manifest_path=manifest_path, entry=manifest_entry)
    _record_install_step(
        install_steps,
        step="update_manifest",
        status="completed",
        progress=progress,
        path=str(manifest_path),
    )

    result: dict[str, object] = {
        "installed_model": model_id,
        "catalog_source": catalog_source,
        "artifact_url": artifact_url,
        "artifact_bytes": artifact.bytes,
        "artifact_size_mib": _catalog_artifact_size_mib(artifact.bytes),
        "catalog_artifact_size_bytes": catalog_artifact_size_bytes,
        "catalog_artifact_size_matches": catalog_artifact_size_matches,
        "install_dir": str(install_dir),
        "manifest_path": str(manifest_path),
        "files_installed": len(installed_files),
        "checksum_verified": checksum_verified,
        "install_steps": install_steps,
        "next_steps": [
            f"tts model-activate {model_id}",
            "restart the local service if it is already running",
            "tts list-voices",
        ],
    }
    if not checksum_verified:
        result["warning"] = (
            "Catalog entry has no artifact_sha256; install was allowed only because "
            "--allow-missing-checksum was set."
        )

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
        _record_install_step(
            install_steps,
            step="activate_model",
            status="completed",
            progress=progress,
            path=str(resolved_config_path),
        )

    return result


def _record_install_step(
    steps: list[dict[str, object]],
    *,
    step: str,
    status: str,
    progress: Callable[[str], None] | None,
    **fields: object,
) -> None:
    record: dict[str, object] = {"step": step, "status": status}
    record.update(fields)
    steps.append(record)
    if progress is not None:
        progress(_format_install_progress(record))


def _format_install_progress(step: dict[str, object]) -> str:
    label = str(step["step"]).replace("_", " ")
    status = str(step["status"])
    details: list[str] = []
    for key in ("detail", "bytes", "files_installed", "algorithm", "path", "reason"):
        if key in step:
            details.append(f"{key}={step[key]}")
    if details:
        return f"{label}: {status} ({', '.join(details)})"
    return f"{label}: {status}"


def _load_artifact_file(
    *,
    artifact_url: str,
    catalog_location: CatalogLocation,
    destination: Path,
) -> ArtifactFile:
    destination.parent.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(artifact_url)
    if parsed.scheme in {"http", "https"}:
        _download_artifact_to_file(url=artifact_url, destination=destination)
        return ArtifactFile(path=destination, bytes=destination.stat().st_size)

    if isinstance(catalog_location, str):
        resolved_url = urljoin(catalog_location, artifact_url)
        _download_artifact_to_file(url=resolved_url, destination=destination)
        return ArtifactFile(path=destination, bytes=destination.stat().st_size)

    artifact_path = Path(artifact_url).expanduser()
    if not artifact_path.is_absolute():
        artifact_path = (catalog_location.parent / artifact_path).resolve()
    with artifact_path.open("rb") as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target)
    return ArtifactFile(path=destination, bytes=destination.stat().st_size)


def _download_artifact_to_file(*, url: str, destination: Path) -> None:
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with destination.open("wb") as artifact_file:
                for chunk in response.iter_bytes():
                    artifact_file.write(chunk)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _extract_model_artifact(*, artifact_path: Path, out_dir: Path) -> None:
    if zipfile.is_zipfile(artifact_path):
        _extract_zip(artifact_path=artifact_path, out_dir=out_dir)
        return

    if tarfile.is_tarfile(artifact_path):
        _extract_tar(artifact_path=artifact_path, out_dir=out_dir)
        return

    raise SystemExit(
        "Model artifact is not a supported archive. Expected zip, tar, tar.gz, tgz, "
        "tar.bz2, or tbz2."
    )


def _extract_zip(*, artifact_path: Path, out_dir: Path) -> None:
    try:
        with zipfile.ZipFile(artifact_path) as archive:
            _assert_safe_zip_members(archive=archive, out_dir=out_dir)
            archive.extractall(out_dir)
    except zipfile.BadZipFile as exc:
        raise SystemExit(f"Model artifact is not a valid zip file: {exc}") from exc


def _extract_tar(*, artifact_path: Path, out_dir: Path) -> None:
    try:
        with tarfile.open(artifact_path) as archive:
            _assert_safe_tar_members(archive=archive, out_dir=out_dir)
            try:
                archive.extractall(out_dir, filter="data")
            except TypeError:
                archive.extractall(out_dir)
    except tarfile.TarError as exc:
        raise SystemExit(f"Model artifact is not a valid tar file: {exc}") from exc


def _assert_safe_zip_members(*, archive: zipfile.ZipFile, out_dir: Path) -> None:
    out_dir_resolved = out_dir.resolve()
    for member in archive.infolist():
        _assert_safe_archive_member_path(
            member_name=member.filename,
            out_dir_resolved=out_dir_resolved,
        )


def _assert_safe_tar_members(*, archive: tarfile.TarFile, out_dir: Path) -> None:
    out_dir_resolved = out_dir.resolve()
    for member in archive.getmembers():
        _assert_safe_archive_member_path(
            member_name=member.name,
            out_dir_resolved=out_dir_resolved,
        )
        if not (member.isdir() or member.isfile()):
            raise SystemExit(
                f"Model artifact contains unsupported tar entry: {member.name!r}"
            )


def _assert_safe_archive_member_path(*, member_name: str, out_dir_resolved: Path) -> None:
    posix_member_path = PurePosixPath(member_name)
    windows_member_path = PureWindowsPath(member_name)
    if (
        posix_member_path.is_absolute()
        or windows_member_path.is_absolute()
        or windows_member_path.drive
    ):
        raise SystemExit(f"Model artifact contains absolute path entry: {member_name!r}")
    if ".." in posix_member_path.parts or ".." in windows_member_path.parts:
        raise SystemExit(
            f"Model artifact contains unsafe path traversal entry: {member_name!r}"
        )
    member_path = Path(*posix_member_path.parts)
    destination = (out_dir_resolved / member_path).resolve()
    if destination != out_dir_resolved and out_dir_resolved not in destination.parents:
        raise SystemExit(
            f"Model artifact contains unsafe path traversal entry: {member_name!r}"
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


def _remove_model(
    *,
    model_id: str,
    models_root: Path,
    manifest_path: Path,
    config_path: Path | None = None,
) -> dict[str, object]:
    config_default_status = _inspect_config_default_for_remove(
        model_id=model_id,
        config_path=config_path,
    )
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

    result: dict[str, object] = {
        "model_id": model_id,
        "removed_files": removed_files,
        "removed_manifest_entry": removed_manifest_entry,
    }
    result.update(config_default_status)
    if config_default_status.get("active_default_voice") is True:
        result["warning"] = (
            "This model id is still configured as [tts].default_voice. "
            "Activate another installed model before restarting the service."
        )
        result["next_steps"] = [
            "tts model-activate <model-id>",
            "restart the local service",
            "tts list-voices",
        ]
    elif config_default_status.get("config_inspection_error"):
        result["warning"] = config_default_status["config_inspection_error"]
    return result


def _inspect_config_default_for_remove(
    *,
    model_id: str,
    config_path: Path | None,
) -> dict[str, object]:
    if config_path is None:
        return {}
    if not config_path.exists():
        return {
            "config_path": str(config_path),
            "active_default_voice": False,
        }
    try:
        config = load_config(config_path, env={})
    except ValueError as exc:
        return {
            "config_path": str(config_path),
            "active_default_voice": False,
            "config_inspection_error": f"Could not inspect config default voice: {exc}",
        }
    return {
        "config_path": str(config_path),
        "active_default_voice": config.tts.default_voice == model_id,
    }


def _list_models(
    *,
    repo_root: Path,
    manifest_path: Path,
    config_path: Path,
) -> dict[str, object]:
    resolved_repo_root = repo_root.expanduser().resolve()
    resolved_manifest_path = _resolve_under_root(resolved_repo_root, manifest_path)
    resolved_config_path = _resolve_under_root(resolved_repo_root, config_path)
    config_status = _inspect_config_for_model_check(resolved_config_path)
    default_voice = str(config_status.get("default_voice") or "").strip()
    manifest_status = _inspect_manifest_for_model_list(
        manifest_path=resolved_manifest_path,
        default_voice=default_voice,
    )
    catalog_status = _inspect_catalog_for_model_check(repo_root=resolved_repo_root)
    runtime_status = _inspect_runtime_for_model_check(config_status=config_status)
    return {
        "repo_root": str(resolved_repo_root),
        "config": config_status,
        "manifest": {
            key: value
            for key, value in manifest_status.items()
            if key != "models"
        },
        "catalog": catalog_status,
        "runtime": runtime_status,
        "default_voice": default_voice or None,
        "models": manifest_status.get("models", []),
        "next_steps": _model_list_next_steps(
            config_status=config_status,
            manifest_status=manifest_status,
            catalog_status=catalog_status,
            runtime_status=runtime_status,
        ),
    }


def _inspect_manifest_for_model_list(
    *,
    manifest_path: Path,
    default_voice: str,
) -> dict[str, object]:
    if not manifest_path.exists():
        return {
            "path": str(manifest_path),
            "exists": False,
            "valid": False,
            "voice_count": 0,
            "default_voice_in_manifest": False,
            "models": [],
            "error": "Manifest does not exist.",
        }
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "path": str(manifest_path),
            "exists": True,
            "valid": False,
            "voice_count": 0,
            "default_voice_in_manifest": False,
            "models": [],
            "error": f"Manifest is not valid JSON: {exc}",
        }
    if not isinstance(payload, dict):
        return _invalid_manifest_for_model_list(manifest_path, "Manifest root must be an object.")
    if payload.get("version") != 1:
        return _invalid_manifest_for_model_list(
            manifest_path,
            f"Unsupported manifest version: {payload.get('version')!r}",
        )
    voices = payload.get("voices", [])
    if not isinstance(voices, list):
        return _invalid_manifest_for_model_list(
            manifest_path,
            "Manifest field 'voices' must be a list.",
        )

    models = [
        _model_list_voice_summary(voice=voice, default_voice=default_voice)
        for voice in voices
        if isinstance(voice, dict) and str(voice.get("id", "")).strip()
    ]
    return {
        "path": str(manifest_path),
        "exists": True,
        "valid": True,
        "voice_count": len(models),
        "default_voice_in_manifest": any(
            model.get("id") == default_voice for model in models
        ),
        "models": models,
    }


def _invalid_manifest_for_model_list(manifest_path: Path, error: str) -> dict[str, object]:
    return {
        "path": str(manifest_path),
        "exists": True,
        "valid": False,
        "voice_count": 0,
        "default_voice_in_manifest": False,
        "models": [],
        "error": error,
    }


def _model_list_voice_summary(
    *,
    voice: dict[str, object],
    default_voice: str,
) -> dict[str, object]:
    model_id = str(voice.get("id", "")).strip()
    backend = voice.get("backend")
    return {
        "id": model_id,
        "name": str(voice.get("name", model_id)),
        "engine": str(voice.get("engine", "unknown")),
        "language": str(voice.get("language", "unknown")),
        "sample_rate_hz": voice.get("sample_rate_hz"),
        "quality_tier": str(voice.get("quality_tier", "unknown")),
        "source": str(voice.get("source", "")),
        "is_default": bool(model_id and model_id == default_voice),
        "has_backend_config": isinstance(backend, dict),
        "backend_model_type": (
            str(backend.get("model_type", "")).strip()
            if isinstance(backend, dict)
            else None
        ),
    }


def _model_list_next_steps(
    *,
    config_status: dict[str, object],
    manifest_status: dict[str, object],
    catalog_status: dict[str, object],
    runtime_status: dict[str, object],
) -> list[str]:
    steps: list[str] = []
    if config_status.get("valid") is not True:
        steps.append("tts setup-local")
    if manifest_status.get("valid") is not True or not manifest_status.get("models"):
        steps.append("tts catalog-list")
        steps.append(
            _model_check_install_step(
                model_id="",
                catalog_status=catalog_status,
                overwrite=False,
            )
        )
        _append_sherpa_onnx_install_step(
            steps,
            runtime_status=runtime_status,
            real_output_expected=True,
        )
        return steps
    if manifest_status.get("default_voice_in_manifest") is not True:
        steps.extend(
            [
                "tts model-activate <model-id>",
                "tts model-check <model-id>",
            ]
        )
        return steps

    default_voice = str(config_status.get("default_voice") or "").strip()
    default_model = _model_list_default_model(manifest_status)
    if (
        default_model is not None
        and default_model.get("has_backend_config") is not True
    ):
        install_step = _setup_local_model_install_step(
            default_voice=default_voice,
            default_voice_in_manifest=True,
            default_voice_has_backend_config=False,
            catalog_status=catalog_status,
        )
        if install_step:
            steps.append(install_step)
            _append_sherpa_onnx_install_step(
                steps,
                runtime_status=runtime_status,
                real_output_expected=True,
            )
            steps.append("tts model-check")
            return steps
    if default_model is not None and default_model.get("has_backend_config") is True:
        _append_sherpa_onnx_install_step(
            steps,
            runtime_status=runtime_status,
            real_output_expected=True,
        )
    if default_voice:
        steps.append(f"tts model-check {default_voice}")
    else:
        steps.append("tts model-check")
    steps.append("tts serve")
    return steps


def _model_list_default_model(
    manifest_status: dict[str, object],
) -> dict[str, object] | None:
    models = manifest_status.get("models", [])
    if not isinstance(models, list):
        return None
    return next(
        (
            model
            for model in models
            if isinstance(model, dict) and model.get("is_default") is True
        ),
        None,
    )


def _append_sherpa_onnx_install_step(
    steps: list[str],
    *,
    runtime_status: dict[str, object],
    real_output_expected: bool,
) -> None:
    if not real_output_expected or runtime_status.get("real_mode_enabled") is not True:
        return
    sherpa_missing = runtime_status.get("sherpa_onnx_installed") is not True
    numpy_missing = runtime_status.get("numpy_installed") is not True
    if sherpa_missing and numpy_missing and REAL_RUNTIME_INSTALL_STEP not in steps:
        steps.append(REAL_RUNTIME_INSTALL_STEP)
        return
    if sherpa_missing and SHERPA_ONNX_INSTALL_STEP not in steps:
        steps.append(SHERPA_ONNX_INSTALL_STEP)
    if numpy_missing and NUMPY_INSTALL_STEP not in steps:
        steps.append(NUMPY_INSTALL_STEP)


def _check_model_readiness(
    *,
    model_id: str | None,
    repo_root: Path,
    manifest_path: Path,
    config_path: Path,
) -> dict[str, object]:
    resolved_repo_root = repo_root.expanduser().resolve()
    resolved_manifest_path = _resolve_under_root(resolved_repo_root, manifest_path)
    resolved_config_path = _resolve_under_root(resolved_repo_root, config_path)
    config_status = _inspect_config_for_model_check(resolved_config_path)
    selected_model_id = model_id or str(config_status.get("default_voice") or "").strip()
    selected_source = "argument" if model_id else "config_default"
    manifest_status = _inspect_manifest_for_model_check(
        manifest_path=resolved_manifest_path,
        model_id=selected_model_id,
    )
    backend_status = _inspect_backend_for_model_check(
        repo_root=resolved_repo_root,
        model_id=selected_model_id,
        voice=manifest_status.get("voice"),
    )
    runtime_status = _inspect_runtime_for_model_check(config_status=config_status)
    catalog_status = _inspect_catalog_for_model_check(repo_root=resolved_repo_root)
    next_steps = _model_check_next_steps(
        model_id=selected_model_id,
        config_status=config_status,
        manifest_status=manifest_status,
        backend_status=backend_status,
        runtime_status=runtime_status,
        catalog_status=catalog_status,
    )
    ready = (
        bool(selected_model_id)
        and config_status.get("valid") is True
        and manifest_status.get("voice_found") is True
        and backend_status.get("configured") is True
        and backend_status.get("valid") is True
        and backend_status.get("assets_ready") is True
        and runtime_status.get("real_mode_enabled") is True
        and runtime_status.get("sherpa_onnx_installed") is True
        and runtime_status.get("numpy_installed") is True
    )

    return {
        "ready": ready,
        "model_id": selected_model_id or None,
        "selected_source": selected_source,
        "config": config_status,
        "manifest": _without_private_voice(manifest_status),
        "backend": backend_status,
        "runtime": runtime_status,
        "catalog": catalog_status,
        "next_steps": next_steps,
    }


def _inspect_config_for_model_check(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        return {
            "path": str(config_path),
            "exists": False,
            "valid": False,
            "default_voice": None,
            "backend_mode": None,
            "error": "Config does not exist.",
        }
    try:
        config = load_config(config_path, env={})
    except ValueError as exc:
        return {
            "path": str(config_path),
            "exists": True,
            "valid": False,
            "default_voice": None,
            "backend_mode": None,
            "error": str(exc),
        }
    return {
        "path": str(config_path),
        "exists": True,
        "valid": True,
        "default_voice": config.tts.default_voice,
        "backend_mode": config.backend.mode,
        "backend_provider": config.backend.provider,
        "warmup_on_start": config.tts.warmup_on_start,
    }


def _inspect_manifest_for_model_check(
    *,
    manifest_path: Path,
    model_id: str,
) -> dict[str, object]:
    if not manifest_path.exists():
        return {
            "path": str(manifest_path),
            "exists": False,
            "valid": False,
            "voice_count": 0,
            "voice_found": False,
            "voice": None,
            "error": "Manifest does not exist.",
        }
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "path": str(manifest_path),
            "exists": True,
            "valid": False,
            "voice_count": 0,
            "voice_found": False,
            "voice": None,
            "error": f"Manifest is not valid JSON: {exc}",
        }
    if not isinstance(payload, dict):
        return _invalid_manifest_for_model_check(manifest_path, "Manifest root must be an object.")
    if payload.get("version") != 1:
        return _invalid_manifest_for_model_check(
            manifest_path,
            f"Unsupported manifest version: {payload.get('version')!r}",
        )
    voices = payload.get("voices", [])
    if not isinstance(voices, list):
        return _invalid_manifest_for_model_check(
            manifest_path,
            "Manifest field 'voices' must be a list.",
        )

    matching_voice = next(
        (
            voice
            for voice in voices
            if isinstance(voice, dict) and str(voice.get("id", "")).strip() == model_id
        ),
        None,
    )
    return {
        "path": str(manifest_path),
        "exists": True,
        "valid": True,
        "voice_count": len([voice for voice in voices if isinstance(voice, dict)]),
        "voice_found": matching_voice is not None,
        "voice": matching_voice,
    }


def _invalid_manifest_for_model_check(manifest_path: Path, error: str) -> dict[str, object]:
    return {
        "path": str(manifest_path),
        "exists": True,
        "valid": False,
        "voice_count": 0,
        "voice_found": False,
        "voice": None,
        "error": error,
    }


def _inspect_backend_for_model_check(
    *,
    repo_root: Path,
    model_id: str,
    voice: object,
) -> dict[str, object]:
    if not model_id or not isinstance(voice, dict):
        return {
            "configured": False,
            "valid": False,
            "assets_ready": False,
            "asset_checks": [],
            "missing_assets": [],
        }
    backend_raw = voice.get("backend")
    if not isinstance(backend_raw, dict):
        return {
            "configured": False,
            "valid": False,
            "assets_ready": False,
            "asset_checks": [],
            "missing_assets": [],
            "warning": "Voice has no sherpa-onnx backend config; it can only use stub fallback.",
        }

    try:
        runtime_config = SherpaOnnxVoiceRuntimeConfig.from_mapping(backend_raw)
    except (BackendNotReadyError, ValueError, TypeError) as exc:
        return {
            "configured": True,
            "valid": False,
            "assets_ready": False,
            "asset_checks": [],
            "missing_assets": [],
            "error": str(exc),
        }

    asset_checks, config_errors = _model_backend_asset_checks(
        repo_root=repo_root,
        runtime_config=runtime_config,
    )
    missing_assets = [check["path"] for check in asset_checks if check.get("exists") is not True]
    return {
        "configured": True,
        "valid": not config_errors,
        "model_type": runtime_config.model_type,
        "assets_ready": not config_errors and not missing_assets,
        "asset_checks": asset_checks,
        "missing_assets": missing_assets,
        "errors": config_errors,
    }


def _model_backend_asset_checks(
    *,
    repo_root: Path,
    runtime_config: SherpaOnnxVoiceRuntimeConfig,
) -> tuple[list[dict[str, object]], list[str]]:
    required_fields = {
        "vits": ("model",),
        "matcha": ("acoustic_model", "vocoder"),
        "kokoro": ("model", "voices", "tokens", "data_dir"),
        "kitten": ("model", "voices", "tokens", "data_dir"),
    }[runtime_config.model_type]
    config_errors: list[str] = []
    if runtime_config.model_type in {"vits", "matcha"} and not (
        runtime_config.data_dir or runtime_config.tokens
    ):
        config_errors.append(
            f"{runtime_config.model_type} voices must define either data_dir or tokens."
        )

    checks: list[dict[str, object]] = []
    for field in required_fields:
        checks.append(
            _model_asset_check(
                repo_root=repo_root,
                field=field,
                raw_path=str(getattr(runtime_config, field)),
                required=True,
            )
        )
    for field in ("tokens", "data_dir", "lexicon"):
        raw_path = str(getattr(runtime_config, field))
        if raw_path and field not in required_fields:
            checks.append(
                _model_asset_check(
                    repo_root=repo_root,
                    field=field,
                    raw_path=raw_path,
                    required=False,
                )
            )
    for index, raw_path in enumerate(runtime_config.rule_fsts):
        checks.append(
            _model_asset_check(
                repo_root=repo_root,
                field=f"rule_fsts[{index}]",
                raw_path=raw_path,
                required=False,
            )
        )
    return checks, config_errors


def _model_asset_check(
    *,
    repo_root: Path,
    field: str,
    raw_path: str,
    required: bool,
) -> dict[str, object]:
    resolved_path = _resolve_model_asset_path(repo_root=repo_root, raw_path=raw_path)
    return {
        "field": field,
        "path": str(resolved_path) if resolved_path is not None else "",
        "required": required,
        "exists": resolved_path is not None and resolved_path.exists(),
    }


def _resolve_model_asset_path(*, repo_root: Path, raw_path: str) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (repo_root / path).resolve()


def _inspect_runtime_for_model_check(config_status: dict[str, object]) -> dict[str, object]:
    backend_mode = str(config_status.get("backend_mode") or "")
    return {
        "backend_mode": backend_mode or None,
        "real_mode_enabled": backend_mode in {"auto", "real"},
        "sherpa_onnx_installed": importlib.util.find_spec("sherpa_onnx") is not None,
        "numpy_installed": importlib.util.find_spec("numpy") is not None,
    }


def _inspect_catalog_for_model_check(repo_root: Path) -> dict[str, object]:
    catalog_path = (repo_root / DEFAULT_MODEL_CATALOG_PATH).resolve()
    status: dict[str, object] = {
        "default_path": DEFAULT_MODEL_CATALOG_PATH,
        "path": str(catalog_path),
        "exists": catalog_path.is_file(),
    }
    if not catalog_path.is_file():
        return status

    try:
        catalog_payload, _ = _load_model_catalog(str(catalog_path))
        models = _catalog_models(catalog_payload)
    except SystemExit as exc:
        status.update(
            {
                "valid": False,
                "model_count": 0,
                "installable_model_ids": [],
                "error": str(exc),
            }
        )
        return status

    installable_model_ids = [
        str(model.get("id", "")).strip()
        for model in models
        if str(model.get("id", "")).strip()
        and str(model.get("artifact_url", "")).strip()
    ]
    status.update(
        {
            "valid": True,
            "model_count": len(models),
            "installable_model_ids": installable_model_ids,
            "single_installable_model_id": (
                installable_model_ids[0] if len(installable_model_ids) == 1 else None
            ),
        }
    )
    return status


def _model_check_next_steps(
    *,
    model_id: str,
    config_status: dict[str, object],
    manifest_status: dict[str, object],
    backend_status: dict[str, object],
    runtime_status: dict[str, object],
    catalog_status: dict[str, object],
) -> list[str]:
    steps: list[str] = []
    if config_status.get("exists") is not True:
        steps.append("tts setup-local")
    if not model_id or manifest_status.get("voice_found") is not True:
        steps.append(
            _model_check_install_step(
                model_id=model_id,
                catalog_status=catalog_status,
                overwrite=False,
            )
        )
        return steps
    if backend_status.get("configured") is not True:
        steps.append(
            _model_check_install_step(
                model_id=model_id,
                catalog_status=catalog_status,
                overwrite=True,
            )
        )
    elif backend_status.get("assets_ready") is not True:
        steps.append(
            _model_check_install_step(
                model_id=model_id,
                catalog_status=catalog_status,
                overwrite=True,
            )
        )
    _append_sherpa_onnx_install_step(
        steps,
        runtime_status=runtime_status,
        real_output_expected=True,
    )
    if runtime_status.get("real_mode_enabled") is not True:
        steps.append("set [backend].mode to auto or real in config/config.toml")
    if not steps:
        steps.extend(
            [
                "restart the local service if it is already running",
                (
                    "python3 scripts/smoke_service.py --token-file "
                    f"config/token.txt --voice {model_id}"
                ),
            ]
        )
    return steps


def _model_check_catalog_argument(catalog_status: dict[str, object]) -> str:
    if catalog_status.get("exists") is True:
        return ""
    return " --catalog <path-or-url>"


def _model_check_install_step(
    *,
    model_id: str,
    catalog_status: dict[str, object],
    overwrite: bool,
) -> str:
    model_ref, refers_to_selected_model = _model_check_catalog_model_ref(
        model_id=model_id,
        catalog_status=catalog_status,
    )
    overwrite_arg = " --overwrite" if overwrite and refers_to_selected_model else ""
    return (
        f"tts model-install {model_ref}"
        f"{_model_check_catalog_argument(catalog_status)} --activate{overwrite_arg}"
    )


def _model_check_catalog_model_ref(
    *,
    model_id: str,
    catalog_status: dict[str, object],
) -> tuple[str, bool]:
    installable_model_ids = [
        str(candidate)
        for candidate in catalog_status.get("installable_model_ids", [])
        if str(candidate).strip()
    ]
    if model_id and model_id in installable_model_ids:
        return model_id, True

    single_installable_model_id = str(
        catalog_status.get("single_installable_model_id") or ""
    ).strip()
    if single_installable_model_id:
        return single_installable_model_id, False

    if model_id:
        return model_id, True
    return "<model-id>", False


def _without_private_voice(manifest_status: dict[str, object]) -> dict[str, object]:
    public_status = dict(manifest_status)
    voice = public_status.pop("voice", None)
    if isinstance(voice, dict):
        public_status["voice"] = {
            "id": voice.get("id"),
            "name": voice.get("name"),
            "engine": voice.get("engine"),
            "language": voice.get("language"),
            "source": voice.get("source"),
            "has_backend_config": isinstance(voice.get("backend"), dict),
        }
    else:
        public_status["voice"] = None
    return public_status


if __name__ == "__main__":
    main()
