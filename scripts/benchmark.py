from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import websockets

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"

for path in (SERVICE_SRC, CORE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tts_core.audio import encode_wav_pcm16, inspect_wav  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:7777")
    parser.add_argument("--token", default=None)
    parser.add_argument("--voice", default=None)
    parser.add_argument("--text", default="Hello from the local TTS benchmark.")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--mode", choices=["http", "stream", "job"], default="http")
    parser.add_argument("--poll-interval-ms", type=int, default=50)
    parser.add_argument("--job-timeout-s", type=float, default=30.0)
    args = parser.parse_args()

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    latencies_ms: list[float] = []
    audio_durations_ms: list[int] = []
    byte_sizes: list[int] = []

    if args.mode == "http":
        with httpx.Client(timeout=60.0) as client:
            for _ in range(args.iterations):
                payload = {"text": args.text}
                if args.voice:
                    payload["voice"] = args.voice
                start_time = time.perf_counter()
                response = client.post(
                    f"{args.base_url.rstrip('/')}/v1/tts",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                latency_ms = (time.perf_counter() - start_time) * 1000
                latencies_ms.append(latency_ms)
                stats = inspect_wav(response.content)
                audio_durations_ms.append(stats.duration_ms)
                byte_sizes.append(len(response.content))
    elif args.mode == "stream":
        for _ in range(args.iterations):
            result = asyncio.run(
                _run_stream_iteration(
                    base_url=args.base_url.rstrip("/"),
                    token=args.token,
                    text=args.text,
                    voice=args.voice,
                )
            )
            latencies_ms.append(result["latency_ms"])
            audio_durations_ms.append(result["audio_duration_ms"])
            byte_sizes.append(result["bytes"])
    else:
        with httpx.Client(timeout=60.0) as client:
            for _ in range(args.iterations):
                result = _run_job_iteration(
                    client=client,
                    base_url=args.base_url.rstrip("/"),
                    token=args.token,
                    text=args.text,
                    voice=args.voice,
                    poll_interval_ms=args.poll_interval_ms,
                    job_timeout_s=args.job_timeout_s,
                )
                latencies_ms.append(result["latency_ms"])
                audio_durations_ms.append(result["audio_duration_ms"])
                byte_sizes.append(result["bytes"])

    average_latency_ms = sum(latencies_ms) / len(latencies_ms)
    average_audio_duration_ms = sum(audio_durations_ms) / len(audio_durations_ms)
    average_rtf = (
        average_latency_ms / average_audio_duration_ms if average_audio_duration_ms else None
    )
    summary = {
        "mode": args.mode,
        "iterations": args.iterations,
        "average_latency_ms": average_latency_ms,
        "min_latency_ms": min(latencies_ms),
        "max_latency_ms": max(latencies_ms),
        "average_audio_duration_ms": average_audio_duration_ms,
        "average_output_bytes": sum(byte_sizes) / len(byte_sizes),
        "average_rtf": average_rtf,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


async def _run_stream_iteration(
    *,
    base_url: str,
    token: str | None,
    text: str,
    voice: str | None,
) -> dict[str, float | int]:
    ws_url = _to_ws_url(base_url) + "/v1/tts/stream"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    pcm_bytes = bytearray()
    sample_rate_hz = 24000
    channels = 1
    start_time = time.perf_counter()

    async with websockets.connect(ws_url, additional_headers=headers) as websocket:
        payload = {"text": text}
        if voice:
            payload["voice"] = voice
        await websocket.send(json.dumps({"type": "start", "payload": payload}))

        while True:
            message = await websocket.recv()
            if isinstance(message, bytes):
                pcm_bytes.extend(message)
                continue
            event = json.loads(message)
            if event["type"] == "started":
                sample_rate_hz = event["sample_rate_hz"]
                channels = event["channels"]
                continue
            if event["type"] == "error":
                raise SystemExit(json.dumps(event["error"], indent=2, sort_keys=True))
            if event["type"] == "done":
                break

    latency_ms = (time.perf_counter() - start_time) * 1000
    wav_bytes = encode_wav_pcm16(bytes(pcm_bytes), sample_rate_hz=sample_rate_hz, channels=channels)
    stats = inspect_wav(wav_bytes)
    return {
        "latency_ms": latency_ms,
        "audio_duration_ms": stats.duration_ms,
        "bytes": len(wav_bytes),
    }


def _run_job_iteration(
    *,
    client: httpx.Client,
    base_url: str,
    token: str | None,
    text: str,
    voice: str | None,
    poll_interval_ms: int,
    job_timeout_s: float,
) -> dict[str, float | int]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {"text": text}
    if voice:
        payload["voice"] = voice

    start_time = time.perf_counter()
    create_response = client.post(
        f"{base_url}/v1/tts/jobs",
        json=payload,
        headers=headers,
    )
    create_response.raise_for_status()
    job_id = create_response.json()["job_id"]

    deadline = time.perf_counter() + job_timeout_s
    status_payload = {}
    while time.perf_counter() < deadline:
        status_response = client.get(f"{base_url}/v1/tts/jobs/{job_id}", headers=headers)
        status_response.raise_for_status()
        status_payload = status_response.json()
        if status_payload["status"] == "completed":
            break
        if status_payload["status"] in {"failed", "cancelled"}:
            raise SystemExit(json.dumps(status_payload, indent=2, sort_keys=True))
        time.sleep(poll_interval_ms / 1000)
    else:
        raise SystemExit(f"Timed out waiting for async job {job_id} to complete.")

    result_response = client.get(f"{base_url}/v1/tts/jobs/{job_id}/result", headers=headers)
    result_response.raise_for_status()
    latency_ms = (time.perf_counter() - start_time) * 1000
    stats = inspect_wav(result_response.content)
    return {
        "latency_ms": latency_ms,
        "audio_duration_ms": stats.duration_ms,
        "bytes": len(result_response.content),
    }


def _to_ws_url(base_url: str) -> str:
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://") :]
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://") :]
    return base_url


if __name__ == "__main__":
    main()
