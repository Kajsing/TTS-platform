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

    if args.command == "health":
        _print_json(_get_json(f"{base_url}/v1/health"))
        return

    if args.command == "list-voices":
        _print_json(_get_json(f"{base_url}/v1/voices"))
        return

    if args.command == "save":
        _save_audio(
            base_url=base_url,
            token=token,
            text=args.text,
            voice=args.voice,
            out_path=Path(args.out),
        )
        return

    if args.command == "say":
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

    raise SystemExit(f"Unknown command: {args.command}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tts")
    parser.add_argument("--base-url", default="http://127.0.0.1:7777")
    parser.add_argument("--token", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health")
    subparsers.add_parser("list-voices")

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

    return parser


def _headers(token: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url: str) -> dict[str, object]:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


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
                raise SystemExit(json.dumps(event["error"]))
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
