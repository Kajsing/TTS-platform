from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for source_root in (
    REPO_ROOT / "apps" / "tts_service" / "src",
    REPO_ROOT / "packages" / "tts_core" / "src",
    REPO_ROOT / "packages" / "reader_core" / "src",
):
    sys.path.insert(0, str(source_root))


class RealVoicePlaybackError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Play a short Reader document through a real installed local voice."
    )
    parser.add_argument("--voice", default="vits-piper-en_US-lessac-high")
    parser.add_argument("--dotnet", type=Path)
    return parser


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _resolve_dotnet(explicit: Path | None) -> Path:
    candidates = [explicit] if explicit is not None else []
    configured = os.environ.get("TTS_PLATFORM_DOTNET")
    if configured:
        candidates.append(Path(configured))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "TTSPlatform" / "dotnet" / "dotnet.exe")
    executable = shutil.which("dotnet")
    if executable:
        candidates.append(Path(executable))
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise RealVoicePlaybackError("A .NET 10 SDK executable was not found.")


def main() -> int:
    args = _parser().parse_args()
    if os.name != "nt":
        print("Real Reader audio playback requires Windows.", file=sys.stderr)
        return 1

    try:
        import sherpa_onnx  # noqa: F401
        import uvicorn
        from tts_service.config import AppConfig
        from tts_service.main import create_app
    except ImportError:
        print(
            "The real local runtime is unavailable. Run this check with the project .venv.",
            file=sys.stderr,
        )
        return 1

    try:
        dotnet = _resolve_dotnet(args.dotnet)
        with tempfile.TemporaryDirectory(prefix="tts-reader-real-voice-") as temporary_value:
            temporary = Path(temporary_value)
            token_path = temporary / "service" / "token.txt"
            config = AppConfig.from_mapping(
                {
                    "auth": {"enabled": True, "token_file": str(token_path)},
                    "backend": {"mode": "auto", "provider": "cpu"},
                    "tts": {"default_voice": args.voice, "warmup_on_start": False},
                    "limits": {"requests_per_minute": 1000},
                    "reader": {
                        "enabled": True,
                        "home_path": str(temporary / "reader"),
                    },
                }
            )
            app = create_app(config=config, repo_root=REPO_ROOT)
            if not app.state.container.voice_registry.has(args.voice):
                raise RealVoicePlaybackError(f"Installed voice was not found: {args.voice}")
            port = _free_port()
            server = uvicorn.Server(
                uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=port,
                    log_level="warning",
                    access_log=False,
                )
            )
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            deadline = time.monotonic() + 30
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RealVoicePlaybackError("The real-voice Reader service did not start.")
                time.sleep(0.05)

            try:
                token = token_path.read_text(encoding="utf-8").strip()
                base_url = f"http://127.0.0.1:{port}/"
                request = urllib.request.Request(
                    f"{base_url}v1/reader/documents",
                    data=json.dumps(
                        {
                            "title": "Real voice playback check",
                            "source_type": "plain_text",
                            "text": (
                                "This is the TTS Platform Reader real voice playback check."
                            ),
                        }
                    ).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    document_id = json.load(response)["id"]

                smoke_dll = (
                    REPO_ROOT
                    / "apps"
                    / "desktop_reader"
                    / "tools"
                    / "TtsPlatform.Reader.Playback.Smoke"
                    / "bin"
                    / "Release"
                    / "net10.0-windows"
                    / "TtsPlatform.Reader.Playback.Smoke.dll"
                )
                completed = subprocess.run(
                    [str(dotnet), str(smoke_dll), base_url, str(token_path), document_id],
                    cwd=REPO_ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=120,
                )
                if completed.returncode != 0:
                    raise RealVoicePlaybackError(
                        f"Real voice playback failed:\n{completed.stderr}{completed.stdout}"
                    )
                playback = json.loads(completed.stdout)
            finally:
                server.should_exit = True
                thread.join(timeout=15)

        print(
            json.dumps(
                {
                    **playback,
                    "voice": args.voice,
                    "runtime": "sherpa_onnx",
                    "audio_output": "NAudio WASAPI shared mode",
                },
                indent=2,
            )
        )
        return 0
    except (OSError, RealVoicePlaybackError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
