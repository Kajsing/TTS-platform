from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from tts_core.backends import SherpaOnnxBackend
from tts_core.backends.base import BackendNotReadyError
from tts_core.backends.sherpa_onnx import SherpaOnnxBackendSettings
from tts_core.models import SynthesisRequest
from tts_core.registry import VoiceNotFoundError


def build_fake_sherpa_onnx_module(sample_rate: int = 16000) -> object:
    class OfflineTtsVitsModelConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class OfflineTtsMatchaModelConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class OfflineTtsKokoroModelConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class OfflineTtsKittenModelConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class OfflineTtsModelConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class OfflineTtsConfig:
        def __init__(self, *, model, rule_fsts: str, max_num_sentences: int) -> None:
            self.model = model
            self.rule_fsts = rule_fsts
            self.max_num_sentences = max_num_sentences

        def validate(self) -> bool:
            return True

    class GenerationConfig:
        def __init__(self) -> None:
            self.sid = 0
            self.speed = 1.0
            self.silence_scale = 0.0

    class OfflineTts:
        def __init__(self, config) -> None:
            self.config = config

        def generate(self, text: str, generation_config) -> object:
            frame_count = max(32, len(text) * 8)
            samples = [0.25 if index % 2 == 0 else -0.25 for index in range(frame_count)]
            return SimpleNamespace(
                samples=samples,
                sample_rate=sample_rate,
                sid=generation_config.sid,
            )

    return SimpleNamespace(
        OfflineTts=OfflineTts,
        OfflineTtsConfig=OfflineTtsConfig,
        OfflineTtsKittenModelConfig=OfflineTtsKittenModelConfig,
        OfflineTtsKokoroModelConfig=OfflineTtsKokoroModelConfig,
        OfflineTtsMatchaModelConfig=OfflineTtsMatchaModelConfig,
        OfflineTtsModelConfig=OfflineTtsModelConfig,
        OfflineTtsVitsModelConfig=OfflineTtsVitsModelConfig,
        GenerationConfig=GenerationConfig,
    )


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


def test_sherpa_backend_real_mode_validates_required_assets_before_runtime_import(tmp_path) -> None:
    backend = SherpaOnnxBackend(
        models_root=tmp_path / "models" / "voices",
        settings=SherpaOnnxBackendSettings(runtime_mode="real"),
        voice_runtime_configs={
            "sherpa-en-debug": {
                "model_type": "vits",
                "model": "models/voices/sherpa-en-debug/model.onnx",
                "tokens": "models/voices/sherpa-en-debug/tokens.txt",
            }
        },
    )

    with pytest.raises(BackendNotReadyError, match="missing backend asset"):
        backend.warmup("sherpa-en-debug")


def test_sherpa_backend_real_mode_can_synthesize_with_fake_runtime(tmp_path, monkeypatch) -> None:
    voice_dir = tmp_path / "models" / "voices" / "sherpa-en-debug"
    voice_dir.mkdir(parents=True)
    (voice_dir / "model.onnx").write_text("fake-model", encoding="utf-8")
    (voice_dir / "tokens.txt").write_text("fake-tokens", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "sherpa_onnx", build_fake_sherpa_onnx_module())

    backend = SherpaOnnxBackend(
        models_root=tmp_path / "models" / "voices",
        settings=SherpaOnnxBackendSettings(runtime_mode="real"),
        voice_runtime_configs={
            "sherpa-en-debug": {
                "model_type": "vits",
                "model": "models/voices/sherpa-en-debug/model.onnx",
                "tokens": "models/voices/sherpa-en-debug/tokens.txt",
            }
        },
    )

    backend.warmup("sherpa-en-debug")
    result = backend.synthesize(
        SynthesisRequest(text="Hello real backend", voice="sherpa-en-debug")
    )

    assert result.audio_bytes[:4] == b"RIFF"
    assert result.sample_rate_hz == 16000
    assert backend.snapshot()["loaded_real_voices"] == ["sherpa-en-debug"]
