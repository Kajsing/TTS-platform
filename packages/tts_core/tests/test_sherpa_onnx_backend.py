from __future__ import annotations

import pytest
from tts_core.backends import SherpaOnnxBackend
from tts_core.models import SynthesisRequest
from tts_core.registry import VoiceNotFoundError


def test_sherpa_backend_exposes_stub_voice(tmp_path) -> None:
    backend = SherpaOnnxBackend(models_root=tmp_path)

    voices = backend.list_voices()

    assert len(voices) == 1
    assert voices[0].id == "sherpa-en-debug"
    assert voices[0].engine == "sherpa_onnx"


def test_sherpa_backend_warmup_validates_voice_id(tmp_path) -> None:
    backend = SherpaOnnxBackend(models_root=tmp_path)

    with pytest.raises(VoiceNotFoundError):
        backend.warmup("missing")


def test_sherpa_backend_synthesize_returns_wav_audio(tmp_path) -> None:
    backend = SherpaOnnxBackend(models_root=tmp_path)

    request = SynthesisRequest(text="Hello world", voice="sherpa-en-debug")

    result = backend.synthesize(request)

    assert result.audio_bytes[:4] == b"RIFF"
    assert result.audio_bytes[8:12] == b"WAVE"
    assert result.sample_rate_hz == 24000


def test_sherpa_backend_streaming_returns_pcm_chunks(tmp_path) -> None:
    backend = SherpaOnnxBackend(models_root=tmp_path)

    request = SynthesisRequest(
        text="Hello world",
        voice="sherpa-en-debug",
        job_id="stream-job",
    )

    chunks = list(backend.synthesize_stream(request))

    assert chunks
    assert chunks[0].job_id == "stream-job"
    assert chunks[0].pcm_bytes
