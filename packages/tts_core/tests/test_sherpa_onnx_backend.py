from __future__ import annotations

import pytest
from tts_core.backends import BackendNotReadyError, SherpaOnnxBackend
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


def test_sherpa_backend_synthesize_is_explicitly_not_ready(tmp_path) -> None:
    backend = SherpaOnnxBackend(models_root=tmp_path)

    request = SynthesisRequest(text="Hello world", voice="sherpa-en-debug")

    with pytest.raises(BackendNotReadyError):
        backend.synthesize(request)
