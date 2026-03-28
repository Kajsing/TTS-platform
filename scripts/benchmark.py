from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"

for path in (SERVICE_SRC, CORE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tts_core.audio import inspect_wav  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:7777")
    parser.add_argument("--token", default=None)
    parser.add_argument("--voice", default=None)
    parser.add_argument("--text", default="Hello from the local TTS benchmark.")
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    latencies_ms: list[float] = []
    audio_durations_ms: list[int] = []
    byte_sizes: list[int] = []

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

    average_latency_ms = sum(latencies_ms) / len(latencies_ms)
    average_audio_duration_ms = sum(audio_durations_ms) / len(audio_durations_ms)
    average_rtf = (
        average_latency_ms / average_audio_duration_ms if average_audio_duration_ms else None
    )
    summary = {
        "iterations": args.iterations,
        "average_latency_ms": average_latency_ms,
        "min_latency_ms": min(latencies_ms),
        "max_latency_ms": max(latencies_ms),
        "average_audio_duration_ms": average_audio_duration_ms,
        "average_output_bytes": sum(byte_sizes) / len(byte_sizes),
        "average_rtf": average_rtf,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
