from __future__ import annotations

import argparse
import asyncio
import json
import os
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
    parser.add_argument("--token-file", default=None)
    parser.add_argument("--voice", default=None)
    parser.add_argument("--text", default="Hello from the local TTS smoke test.")
    parser.add_argument("--stream-text", default=None)
    parser.add_argument("--stream-text-file", default=None)
    parser.add_argument("--stream-text-repeat", type=int, default=1)
    parser.add_argument("--min-stream-text-chunks", type=int, default=1)
    parser.add_argument("--poll-interval-ms", type=int, default=50)
    parser.add_argument("--job-timeout-s", type=float, default=30.0)
    args = parser.parse_args()

    token = _resolve_token(token=args.token, token_file=args.token_file)
    stream_text = _resolve_stream_text(
        text=args.text,
        stream_text=args.stream_text,
        stream_text_file=args.stream_text_file,
        stream_text_repeat=args.stream_text_repeat,
    )
    summary = run_smoke(
        base_url=args.base_url.rstrip("/"),
        token=token,
        voice=args.voice,
        text=args.text,
        stream_text=stream_text,
        min_stream_text_chunks=args.min_stream_text_chunks,
        poll_interval_ms=args.poll_interval_ms,
        job_timeout_s=args.job_timeout_s,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def run_smoke(
    *,
    base_url: str,
    token: str,
    voice: str | None,
    text: str,
    poll_interval_ms: int,
    job_timeout_s: float,
    stream_text: str | None = None,
    min_stream_text_chunks: int = 1,
) -> dict[str, object]:
    if not token:
        raise SystemExit("A token is required. Use --token, --token-file, or TTS_PLATFORM_TOKEN.")
    if min_stream_text_chunks <= 0:
        raise SystemExit("--min-stream-text-chunks must be positive.")
    resolved_stream_text = stream_text if stream_text is not None else text

    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=60.0) as client:
        health = _get_json(client, f"{base_url}/v1/health")
        _validate_health(health)

        voices_payload = _get_json(client, f"{base_url}/v1/voices")
        selected_voice = _resolve_voice(voices_payload, requested_voice=voice)

        http_summary = _run_http_smoke(
            client=client,
            base_url=base_url,
            headers=headers,
            text=text,
            voice=selected_voice,
        )
        job_summary = _run_job_smoke(
            client=client,
            base_url=base_url,
            headers=headers,
            text=text,
            voice=selected_voice,
            poll_interval_ms=poll_interval_ms,
            job_timeout_s=job_timeout_s,
        )

    stream_summary = asyncio.run(
        _run_stream_smoke(
            base_url=base_url,
            token=token,
            text=resolved_stream_text,
            voice=selected_voice,
            min_text_chunks=min_stream_text_chunks,
        )
    )

    return {
        "base_url": base_url,
        "voice": selected_voice,
        "health": {
            "status": health["status"],
            "backend_ready": health["checks"]["backend_ready"],
            "default_voice_loaded": health["checks"]["default_voice_loaded"],
        },
        "voices": {
            "count": len(voices_payload["voices"]),
            "default_voice": voices_payload["default_voice"],
        },
        "input": {
            "text_chars": len(text),
            "stream_text_chars": len(resolved_stream_text),
            "min_stream_text_chunks": min_stream_text_chunks,
        },
        "http": http_summary,
        "stream": stream_summary,
        "job": job_summary,
    }


def _resolve_token(*, token: str | None, token_file: str | None) -> str:
    resolved_token = token or os.environ.get("TTS_PLATFORM_TOKEN")
    if resolved_token:
        return resolved_token.strip()
    if token_file:
        return Path(token_file).read_text(encoding="utf-8").strip()
    return ""


def _resolve_stream_text(
    *,
    text: str,
    stream_text: str | None,
    stream_text_file: str | None,
    stream_text_repeat: int,
) -> str:
    if stream_text_repeat <= 0:
        raise SystemExit("--stream-text-repeat must be positive.")
    if stream_text is not None and stream_text_file is not None:
        raise SystemExit("Use either --stream-text or --stream-text-file, not both.")
    if stream_text_file is not None:
        resolved_stream_text = Path(stream_text_file).read_text(encoding="utf-8")
    elif stream_text is not None:
        resolved_stream_text = stream_text
    else:
        resolved_stream_text = text
    return "\n\n".join(resolved_stream_text for _ in range(stream_text_repeat))


def _get_json(client: httpx.Client, url: str) -> dict[str, object]:
    response = client.get(url)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object from {url}.")
    return payload


def _validate_health(health: dict[str, object]) -> None:
    checks = health.get("checks")
    if not isinstance(checks, dict):
        raise SystemExit("Health payload is missing checks.")
    if health.get("status") != "ok":
        raise SystemExit(f"Health status is not ok: {health!r}")
    if checks.get("backend_ready") is not True:
        raise SystemExit(f"Health backend_ready is not true: {health!r}")
    if checks.get("default_voice_loaded") is not True:
        raise SystemExit(f"Health default_voice_loaded is not true: {health!r}")


def _resolve_voice(voices_payload: dict[str, object], *, requested_voice: str | None) -> str:
    voices = voices_payload.get("voices")
    if not isinstance(voices, list) or not voices:
        raise SystemExit("Voice list is empty.")

    available_voice_ids = [
        voice["id"]
        for voice in voices
        if isinstance(voice, dict) and isinstance(voice.get("id"), str)
    ]
    if requested_voice:
        if requested_voice not in available_voice_ids:
            raise SystemExit(f"Requested voice '{requested_voice}' is not available.")
        return requested_voice

    default_voice = voices_payload.get("default_voice")
    if isinstance(default_voice, str) and default_voice in available_voice_ids:
        return default_voice
    return available_voice_ids[0]


def _run_http_smoke(
    *,
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    text: str,
    voice: str,
) -> dict[str, object]:
    start_time = time.perf_counter()
    response = client.post(
        f"{base_url}/v1/tts",
        json={"text": text, "voice": voice},
        headers=headers,
    )
    response.raise_for_status()
    _require_wav_bytes(response.content, label="sync response")
    stats = inspect_wav(response.content)
    return {
        "latency_ms": (time.perf_counter() - start_time) * 1000,
        "audio_duration_ms": stats.duration_ms,
        "bytes": len(response.content),
        "sample_rate_hz": stats.sample_rate_hz,
    }


async def _run_stream_smoke(
    *,
    base_url: str,
    token: str,
    text: str,
    voice: str,
    min_text_chunks: int,
) -> dict[str, object]:
    ws_url = _to_ws_url(base_url) + "/v1/tts/stream"
    pcm_bytes = bytearray()
    sample_rate_hz = 24000
    channels = 1
    marks = 0
    frames = 0
    text_chunk_count: int | None = None
    start_time = time.perf_counter()

    async with websockets.connect(
        ws_url,
        additional_headers={"Authorization": f"Bearer {token}"},
    ) as websocket:
        await websocket.send(
            json.dumps({"type": "start", "payload": {"text": text, "voice": voice}})
        )

        while True:
            message = await websocket.recv()
            if isinstance(message, bytes):
                pcm_bytes.extend(message)
                frames += 1
                continue

            event = json.loads(message)
            if event["type"] == "started":
                sample_rate_hz = event["sample_rate_hz"]
                channels = event["channels"]
                text_chunk_count = _resolve_text_chunk_count(event, label="started")
                continue
            if event["type"] == "mark":
                marks += 1
                continue
            if event["type"] == "error":
                raise SystemExit(json.dumps(event["error"], indent=2, sort_keys=True))
            if event["type"] == "done":
                break

    if frames == 0:
        raise SystemExit("Streaming smoke test produced no audio frames.")
    if marks != frames:
        raise SystemExit(
            "Streaming smoke test expected mark count to match frame count, "
            f"got {marks} vs {frames}."
        )
    if text_chunk_count is None:
        raise SystemExit("Streaming smoke test did not receive started progress metadata.")
    if text_chunk_count < min_text_chunks:
        raise SystemExit(
            "Streaming smoke test expected at least "
            f"{min_text_chunks} text chunk(s), got {text_chunk_count}."
        )

    wav_bytes = encode_wav_pcm16(bytes(pcm_bytes), sample_rate_hz=sample_rate_hz, channels=channels)
    _require_wav_bytes(wav_bytes, label="stream assembly")
    stats = inspect_wav(wav_bytes)
    return {
        "latency_ms": (time.perf_counter() - start_time) * 1000,
        "audio_duration_ms": stats.duration_ms,
        "bytes": len(wav_bytes),
        "sample_rate_hz": sample_rate_hz,
        "channels": channels,
        "frames": frames,
        "marks": marks,
        "text_chars": len(text),
        "text_chunk_count": text_chunk_count,
    }


def _run_job_smoke(
    *,
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    text: str,
    voice: str,
    poll_interval_ms: int,
    job_timeout_s: float,
) -> dict[str, object]:
    start_time = time.perf_counter()
    create_response = client.post(
        f"{base_url}/v1/tts/jobs",
        json={"text": text, "voice": voice},
        headers=headers,
    )
    create_response.raise_for_status()
    create_payload = create_response.json()
    if not isinstance(create_payload, dict) or not isinstance(create_payload.get("job_id"), str):
        raise SystemExit("Job creation response is missing job_id.")
    job_id = create_payload["job_id"]

    deadline = time.perf_counter() + job_timeout_s
    status_payload: dict[str, object] | None = None
    while time.perf_counter() < deadline:
        status_response = client.get(f"{base_url}/v1/tts/jobs/{job_id}", headers=headers)
        status_response.raise_for_status()
        raw_status = status_response.json()
        if not isinstance(raw_status, dict):
            raise SystemExit(f"Unexpected job status payload for {job_id}.")
        status_payload = raw_status
        if status_payload.get("status") == "completed":
            break
        if status_payload.get("status") in {"failed", "cancelled"}:
            raise SystemExit(json.dumps(status_payload, indent=2, sort_keys=True))
        time.sleep(poll_interval_ms / 1000)
    else:
        raise SystemExit(f"Timed out waiting for async job {job_id} to complete.")

    result_response = client.get(f"{base_url}/v1/tts/jobs/{job_id}/result", headers=headers)
    result_response.raise_for_status()
    _require_wav_bytes(result_response.content, label="job result")
    stats = inspect_wav(result_response.content)
    return {
        "job_id": job_id,
        "status": status_payload["status"] if status_payload is not None else "unknown",
        "latency_ms": (time.perf_counter() - start_time) * 1000,
        "audio_duration_ms": stats.duration_ms,
        "bytes": len(result_response.content),
        "sample_rate_hz": stats.sample_rate_hz,
    }


def _require_wav_bytes(audio_bytes: bytes, *, label: str) -> None:
    if audio_bytes[:4] != b"RIFF" or audio_bytes[8:12] != b"WAVE":
        raise SystemExit(f"{label} is not a WAV payload.")
    stats = inspect_wav(audio_bytes)
    if stats.duration_ms <= 0:
        raise SystemExit(f"{label} has no audible duration.")


def _resolve_text_chunk_count(event: dict[str, object], *, label: str) -> int:
    progress = event.get("progress")
    if not isinstance(progress, dict):
        raise SystemExit(f"Streaming {label} event is missing progress metadata.")
    text_chunk_count = progress.get("text_chunk_count")
    if not isinstance(text_chunk_count, int) or text_chunk_count <= 0:
        raise SystemExit(f"Streaming {label} event has invalid text_chunk_count.")
    return text_chunk_count


def _to_ws_url(base_url: str) -> str:
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://") :]
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://") :]
    return base_url


if __name__ == "__main__":
    main()
