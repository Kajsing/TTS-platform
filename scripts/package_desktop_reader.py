from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


class DesktopReaderPackageError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a self-contained TTS Platform Reader portable archive."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/windows/TTSPlatform.Reader-win-x64.zip"),
    )
    parser.add_argument("--dotnet", type=Path)
    parser.add_argument("--runtime", default="win-x64")
    parser.add_argument("--development-only", action="store_true")
    return parser


def _resolve_dotnet(explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
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
        if candidate.is_file():
            completed = subprocess.run(
                [str(candidate), "--version"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            version = completed.stdout.strip()
            if (
                completed.returncode == 0
                and version.split(".", 1)[0].isdigit()
                and int(version.split(".", 1)[0]) >= 10
            ):
                return candidate.resolve()
    raise DesktopReaderPackageError("A .NET 10 SDK executable could not be found.")


def build_package(
    *,
    repo_root: Path,
    output: Path,
    dotnet: Path,
    runtime: str,
    development_only: bool,
) -> dict[str, object]:
    license_file = repo_root / "LICENSE"
    if not license_file.is_file() and not development_only:
        raise DesktopReaderPackageError(
            "The repository license has not been selected. Pass --development-only "
            "for local testing; "
            "do not publish the desktop binary externally."
        )

    project = (
        repo_root
        / "apps"
        / "desktop_reader"
        / "src"
        / "TtsPlatform.Reader.App"
        / "TtsPlatform.Reader.App.csproj"
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tts-reader-publish-") as temporary:
        publish_dir = Path(temporary) / "publish"
        command = [
            str(dotnet),
            "publish",
            str(project),
            "-c",
            "Release",
            "-r",
            runtime,
            "--self-contained",
            "true",
            "--nologo",
            "-p:PublishSingleFile=false",
            "-p:DebugType=None",
            "-p:DebugSymbols=false",
            "-o",
            str(publish_dir),
        ]
        completed = subprocess.run(command, cwd=repo_root, text=True, check=False)
        if completed.returncode != 0:
            raise DesktopReaderPackageError("dotnet publish failed.")

        executable_name = "TtsPlatform.Reader.App.exe"
        if not (publish_dir / executable_name).is_file():
            raise DesktopReaderPackageError(f"Published executable is missing: {executable_name}")
        if development_only and not license_file.is_file():
            (publish_dir / "DEVELOPMENT-ONLY.txt").write_text(
                "This build is for local development testing only.\n"
                "The repository license must be chosen before external distribution.\n",
                encoding="utf-8",
            )

        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(publish_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(publish_dir).as_posix())

    return {
        "archive": str(output),
        "runtime": runtime,
        "self_contained": True,
        "development_only": development_only,
        "external_distribution_ready": license_file.is_file() and not development_only,
    }


def main() -> int:
    args = _parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        result = build_package(
            repo_root=repo_root,
            output=args.output,
            dotnet=_resolve_dotnet(args.dotnet),
            runtime=args.runtime,
            development_only=args.development_only,
        )
    except DesktopReaderPackageError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
