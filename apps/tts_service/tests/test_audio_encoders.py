from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from tts_service.audio_encoders import (
    AudioEncodingCancelled,
    FfmpegMp3Encoder,
)


def test_ffmpeg_discovery_validates_executable_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"placeholder")
    calls: list[list[str]] = []

    def fake_run(arguments, **_kwargs):
        calls.append(arguments)
        stdout = (
            b"ffmpeg version test"
            if arguments[-1] == "-version"
            else b" A....D libmp3lame MP3 encoder"
        )
        return SimpleNamespace(returncode=0, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    encoder = FfmpegMp3Encoder.discover(str(executable), bitrate_kbps=96)

    assert encoder is not None
    assert encoder.executable == executable.resolve()
    assert calls == [
        [str(executable.resolve()), "-version"],
        [str(executable.resolve()), "-hide_banner", "-encoders"],
    ]


def test_ffmpeg_discovery_requires_libmp3lame(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"placeholder")
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout=b"ffmpeg version test"),
            SimpleNamespace(returncode=0, stdout=b" A....D another_encoder"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: next(responses))

    assert FfmpegMp3Encoder.discover(str(executable)) is None


def test_ffmpeg_encode_uses_fixed_argument_array_and_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "ffmpeg.exe"
    source = tmp_path / "source.wav"
    target = tmp_path / "target.mp3.part"
    executable.write_bytes(b"placeholder")
    source.write_bytes(b"RIFFfake-wave")
    captured: dict[str, object] = {}

    class CompletedProcess:
        def wait(self, timeout=None):
            return 0

    def fake_popen(arguments, **kwargs):
        captured["arguments"] = arguments
        captured["kwargs"] = kwargs
        Path(arguments[-1]).write_bytes(b"ID3fake")
        return CompletedProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    encoder = FfmpegMp3Encoder(executable, bitrate_kbps=96)

    encoder.encode(source, target, title="Article title", should_cancel=lambda: False)

    arguments = captured["arguments"]
    assert isinstance(arguments, list)
    assert arguments[0] == str(executable)
    assert ["-b:a", "96k"] == arguments[arguments.index("-b:a") :][:2]
    assert "title=Article title" in arguments
    assert arguments[-3:-1] == ["-f", "mp3"]
    assert captured["kwargs"]["shell"] is False


def test_ffmpeg_encode_terminates_when_export_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "ffmpeg.exe"
    source = tmp_path / "source.wav"
    target = tmp_path / "target.mp3.part"
    source.write_bytes(b"RIFFfake-wave")

    class RunningProcess:
        terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0 if self.terminated else (_ for _ in ()).throw(subprocess.TimeoutExpired("", 1))

        def kill(self):
            self.terminated = True

    process = RunningProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    encoder = FfmpegMp3Encoder(executable)

    with pytest.raises(AudioEncodingCancelled):
        encoder.encode(source, target, title="Cancelled", should_cancel=lambda: True)

    assert process.terminated is True
    assert not target.exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_installed_ffmpeg_writes_playable_mono_mp3_with_title(tmp_path: Path) -> None:
    encoder = FfmpegMp3Encoder.discover()
    if encoder is None:
        pytest.skip("Installed FFmpeg has no libmp3lame encoder")
    source = tmp_path / "source.wav"
    target = tmp_path / "encoded.mp3.part"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        output.writeframes(b"\0\0" * 2_400)

    encoder.encode(
        source,
        target,
        title="Reader integration title",
        should_cancel=lambda: False,
    )

    assert target.read_bytes().startswith(b"ID3")
    assert b"Reader integration title" in target.read_bytes()
    decoded = subprocess.run(
        [
            str(encoder.executable),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(target),
            "-f",
            "null",
            "-",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    assert decoded.returncode == 0
