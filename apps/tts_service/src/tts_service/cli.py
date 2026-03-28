from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

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
