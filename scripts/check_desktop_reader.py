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
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class DesktopReaderCheckError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the .NET desktop Reader, live paging, and portable WPF package."
    )
    parser.add_argument("--require-dotnet", action="store_true")
    parser.add_argument(
        "--require-windows-audio",
        action="store_true",
        help="Require a real Windows shared-mode audio endpoint smoke.",
    )
    parser.add_argument("--dotnet", type=Path)
    parser.add_argument("--skip-build", action="store_true")
    return parser


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise DesktopReaderCheckError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}"
        )
    return completed.stdout


def _dotnet_candidates(explicit: Path | None) -> Iterator[Path]:
    if explicit is not None:
        yield explicit
    configured = os.environ.get("TTS_PLATFORM_DOTNET")
    if configured:
        yield Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        yield Path(local_app_data) / "TTSPlatform" / "dotnet" / "dotnet.exe"
    executable = shutil.which("dotnet")
    if executable:
        yield Path(executable)


def _resolve_dotnet(explicit: Path | None, *, required: bool) -> Path | None:
    checked: set[Path] = set()
    for candidate in _dotnet_candidates(explicit):
        candidate = candidate.resolve()
        if candidate in checked or not candidate.is_file():
            continue
        checked.add(candidate)
        completed = subprocess.run(
            [str(candidate), "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        version = completed.stdout.strip()
        if completed.returncode == 0 and version.split(".", 1)[0].isdigit() and int(
            version.split(".", 1)[0]
        ) >= 10:
            return candidate
    if required:
        raise DesktopReaderCheckError(
            ".NET SDK 10 or newer was not found. Set TTS_PLATFORM_DOTNET or pass --dotnet."
        )
    return None


def _check_source_shape(repo_root: Path) -> dict[str, object]:
    reader_root = repo_root / "apps" / "desktop_reader"
    required = [
        reader_root / "TtsPlatform.Reader.sln",
        reader_root / "src" / "TtsPlatform.Reader.Client" / "ReaderServiceClient.cs",
        reader_root / "src" / "TtsPlatform.Reader.Application" / "Onboarding.cs",
        reader_root / "src" / "TtsPlatform.Reader.Windows" / "JsonDesktopSettingsStore.cs",
        reader_root / "src" / "TtsPlatform.Reader.Windows" / "WasapiAudioOutput.cs",
        reader_root / "src" / "TtsPlatform.Reader.Client" / "ReaderStreamClient.cs",
        reader_root / "src" / "TtsPlatform.Reader.Application" / "Playback.cs",
        reader_root / "src" / "TtsPlatform.Reader.App" / "MainWindow.xaml",
        reader_root / "src" / "TtsPlatform.Reader.App" / "Resources" / "Strings.en-US.resx",
        reader_root / "src" / "TtsPlatform.Reader.App" / "Resources" / "Strings.da-DK.resx",
    ]
    missing = [str(path.relative_to(repo_root)) for path in required if not path.is_file()]
    if missing:
        raise DesktopReaderCheckError(f"Desktop Reader files are missing: {missing}")

    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in reader_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".cs", ".csproj", ".xaml"}
    )
    forbidden = [
        "AddClipboardFormatListener",
        "WM_HOTKEY",
        "System.Windows.Forms.Clipboard",
    ]
    found = [value for value in forbidden if value.casefold() in source_text.casefold()]
    if found:
        raise DesktopReaderCheckError(
            f"Milestone 4 must not contain clipboard capture code: {found}"
        )
    if "<TargetFramework>net10.0-windows</TargetFramework>" not in source_text:
        raise DesktopReaderCheckError("The WPF application does not target net10.0-windows.")
    if "NAudio" not in source_text or "ReaderStreamProtocolParser" not in source_text:
        raise DesktopReaderCheckError("Milestone 4 audio or stream protocol code is missing.")
    return {"required_files": len(required), "clipboard_features": "absent"}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def _live_reader_service(repo_root: Path, temporary: Path) -> Iterator[tuple[str, Path]]:
    for source_root in (
        repo_root / "apps" / "tts_service" / "src",
        repo_root / "packages" / "tts_core" / "src",
        repo_root / "packages" / "reader_core" / "src",
    ):
        sys.path.insert(0, str(source_root))

    import uvicorn
    from tts_service.config import AppConfig
    from tts_service.main import create_app

    token_path = temporary / "service" / "token.txt"
    reader_home = temporary / "reader"
    config = AppConfig.from_mapping(
        {
            "auth": {"enabled": True, "token_file": str(token_path)},
            "backend": {"mode": "stub"},
            "tts": {"warmup_on_start": False},
            "limits": {"requests_per_minute": 1000},
            "reader": {"enabled": True, "home_path": str(reader_home)},
        }
    )
    app = create_app(config=config, repo_root=temporary)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, name="desktop-reader-live-smoke", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() >= deadline:
            raise DesktopReaderCheckError("The temporary local Reader service did not start.")
        time.sleep(0.05)

    base_url = f"http://127.0.0.1:{port}/"
    try:
        token = token_path.read_text(encoding="utf-8").strip()
        for index in range(2):
            request = urllib.request.Request(
                f"{base_url}v1/reader/documents",
                data=json.dumps(
                    {
                        "title": f"Desktop paging smoke {index + 1}",
                        "source_type": "plain_text",
                        "text": f"Live 😀 paging document {index + 1}.",
                        "allow_duplicate": False,
                    }
                ).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status != 201:
                    raise DesktopReaderCheckError("A live smoke document could not be created.")
        yield base_url, token_path
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise DesktopReaderCheckError("The temporary local Reader service did not stop.")


def _check_live_paging(repo_root: Path, dotnet: Path, temporary: Path) -> dict[str, object]:
    smoke_dll = (
        repo_root
        / "apps"
        / "desktop_reader"
        / "tools"
        / "TtsPlatform.Reader.Client.Smoke"
        / "bin"
        / "Release"
        / "net10.0"
        / "TtsPlatform.Reader.Client.Smoke.dll"
    )
    with _live_reader_service(repo_root, temporary) as (base_url, token_path):
        output = _run(
            [str(dotnet), str(smoke_dll), base_url, str(token_path)],
            cwd=repo_root,
        )
    payload = json.loads(output)
    if payload.get("live_reader_paging") is not True:
        raise DesktopReaderCheckError("The .NET client did not confirm live Reader paging.")
    if payload.get("live_utf16_edit") is not True:
        raise DesktopReaderCheckError("The .NET client did not confirm a live UTF-16 edit.")
    if (
        payload.get("live_reader_stream") is not True
        or payload.get("live_position_resume") is not True
    ):
        raise DesktopReaderCheckError(
            "The .NET client did not confirm Reader WebSocket streaming and durable resume."
        )
    return payload


def _check_preview_snapshot(repo_root: Path, temporary: Path) -> dict[str, object]:
    output = _run(
        [
            sys.executable,
            str(repo_root / "scripts" / "create_reader_preview_snapshot.py"),
            "--output",
            str(temporary / "preview" / "reader-preview.db"),
        ],
        cwd=repo_root,
    )
    payload = json.loads(output)
    if payload.get("integrity_ok") is not True or payload.get("document_count") != 2:
        raise DesktopReaderCheckError("The Reader preview snapshot is not consistent.")
    return payload


def _check_windows_audio(
    repo_root: Path,
    dotnet: Path,
    *,
    required: bool,
) -> dict[str, object]:
    if os.name != "nt":
        if required:
            raise DesktopReaderCheckError(
                "The required Windows audio smoke cannot run off Windows."
            )
        return {"status": "skipped", "reason": "Windows audio requires Windows"}
    if not required:
        return {"status": "skipped", "reason": "pass --require-windows-audio"}

    smoke_dll = (
        repo_root
        / "apps"
        / "desktop_reader"
        / "tools"
        / "TtsPlatform.Reader.Audio.Smoke"
        / "bin"
        / "Release"
        / "net10.0-windows"
        / "TtsPlatform.Reader.Audio.Smoke.dll"
    )
    payload = json.loads(_run([str(dotnet), str(smoke_dll)], cwd=repo_root))
    if payload.get("windows_audio") is not True:
        raise DesktopReaderCheckError("NAudio did not confirm the default Windows audio endpoint.")
    return {"status": "passed", **payload}


def _build_development_package(
    repo_root: Path, dotnet: Path, temporary: Path
) -> tuple[Path, dict[str, object]]:
    archive = temporary / "TTSPlatform.Reader-development-win-x64.zip"
    output = _run(
        [
            sys.executable,
            str(repo_root / "scripts" / "package_desktop_reader.py"),
            "--dotnet",
            str(dotnet),
            "--output",
            str(archive),
            "--development-only",
        ],
        cwd=repo_root,
    )
    json_start = output.rfind("{")
    if json_start < 0:
        raise DesktopReaderCheckError("The desktop package command returned no summary.")
    summary = json.loads(output[json_start:])
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
    required = {
        "TtsPlatform.Reader.App.exe",
        "TtsPlatform.Reader.App.dll",
        "TtsPlatform.Reader.App.runtimeconfig.json",
        "THIRD_PARTY_NOTICES.md",
        "DEVELOPMENT-ONLY.txt",
    }
    if not required.issubset(names):
        raise DesktopReaderCheckError(
            f"The desktop package is missing runtime files: {sorted(required - names)}"
        )
    forbidden_names = {"settings.json", "token.txt"}
    forbidden = [
        name for name in names if Path(name).name.casefold() in forbidden_names
    ]
    if forbidden:
        raise DesktopReaderCheckError(
            f"Desktop package contains local secret/settings files: {forbidden}"
        )
    return archive, summary


def _check_wpf_render(archive: Path, temporary: Path) -> dict[str, object]:
    if os.name != "nt":
        return {"status": "skipped", "reason": "WPF render requires Windows"}
    extracted = temporary / "portable"
    with zipfile.ZipFile(archive) as package:
        package.extractall(extracted)
    marker = temporary / "wpf-rendered.json"
    environment = os.environ.copy()
    environment["TTS_PLATFORM_READER_SMOKE_MARKER"] = str(marker)
    _run(
        [str(extracted / "TtsPlatform.Reader.App.exe"), "--smoke-test"],
        cwd=extracted,
        env=environment,
    )
    if not marker.is_file():
        raise DesktopReaderCheckError("The WPF process exited without rendering its main window.")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if payload.get("rendered") is not True:
        raise DesktopReaderCheckError("The WPF render marker is invalid.")
    return {"status": "passed", "title": payload.get("title")}


def main() -> int:
    args = _parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        source = _check_source_shape(repo_root)
        dotnet = _resolve_dotnet(args.dotnet, required=args.require_dotnet)
        if dotnet is None:
            print(json.dumps({"source": source, "dotnet": "skipped"}, indent=2))
            return 0
        solution = repo_root / "apps" / "desktop_reader" / "TtsPlatform.Reader.sln"
        if not args.skip_build:
            _run([str(dotnet), "restore", str(solution)], cwd=repo_root)
            _run(
                [str(dotnet), "build", str(solution), "-c", "Release", "--no-restore"],
                cwd=repo_root,
            )
            _run(
                [str(dotnet), "test", str(solution), "-c", "Release", "--no-build"],
                cwd=repo_root,
            )
        with tempfile.TemporaryDirectory(prefix="tts-reader-check-") as temporary_value:
            temporary = Path(temporary_value)
            live_paging = _check_live_paging(repo_root, dotnet, temporary)
            preview_snapshot = _check_preview_snapshot(repo_root, temporary)
            windows_audio = _check_windows_audio(
                repo_root,
                dotnet,
                required=args.require_windows_audio,
            )
            archive, package = _build_development_package(repo_root, dotnet, temporary)
            wpf = _check_wpf_render(archive, temporary)
        print(
            json.dumps(
                {
                    "source": source,
                    "dotnet": str(dotnet),
                    "live_paging": live_paging,
                    "preview_snapshot": preview_snapshot,
                    "windows_audio": windows_audio,
                    "portable_package": package,
                    "wpf_render": wpf,
                },
                indent=2,
            )
        )
        return 0
    except DesktopReaderCheckError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
