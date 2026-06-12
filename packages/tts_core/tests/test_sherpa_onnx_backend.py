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


def build_fake_sherpa_onnx_callback_module(
    sample_rate: int = 16000,
    *,
    after_first_callback=None,
) -> tuple[object, list[int]]:
    callback_returns: list[int] = []

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
            self.sample_rate = sample_rate

        def generate(self, text: str, generation_config, callback=None) -> object:
            if callback is None:
                return SimpleNamespace(samples=[0.75] * 32, sample_rate=sample_rate)

            callback_returns.append(callback([0.25] * 8, 0.5))
            if after_first_callback is not None:
                after_first_callback()
            callback_returns.append(callback([-0.25] * 8, 1.0))
            return SimpleNamespace(samples=[0.75] * 32, sample_rate=sample_rate)

    module = SimpleNamespace(
        OfflineTts=OfflineTts,
        OfflineTtsConfig=OfflineTtsConfig,
        OfflineTtsKittenModelConfig=OfflineTtsKittenModelConfig,
        OfflineTtsKokoroModelConfig=OfflineTtsKokoroModelConfig,
        OfflineTtsMatchaModelConfig=OfflineTtsMatchaModelConfig,
        OfflineTtsModelConfig=OfflineTtsModelConfig,
        OfflineTtsVitsModelConfig=OfflineTtsVitsModelConfig,
        GenerationConfig=GenerationConfig,
    )
    return module, callback_returns


def build_real_backend(tmp_path, monkeypatch, module: object) -> SherpaOnnxBackend:
    voice_dir = tmp_path / "models" / "voices" / "sherpa-en-debug"
    voice_dir.mkdir(parents=True)
    (voice_dir / "model.onnx").write_text("fake-model", encoding="utf-8")
    (voice_dir / "tokens.txt").write_text("fake-tokens", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "sherpa_onnx", module)

    return SherpaOnnxBackend(
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
    backend = build_real_backend(tmp_path, monkeypatch, build_fake_sherpa_onnx_module())

    backend.warmup("sherpa-en-debug")
    result = backend.synthesize(
        SynthesisRequest(text="Hello real backend", voice="sherpa-en-debug")
    )

    assert result.audio_bytes[:4] == b"RIFF"
    assert result.sample_rate_hz == 16000
    assert backend.snapshot()["loaded_real_voices"] == ["sherpa-en-debug"]


def test_sherpa_backend_real_stream_uses_runtime_callback(tmp_path, monkeypatch) -> None:
    module, callback_returns = build_fake_sherpa_onnx_callback_module()
    backend = build_real_backend(tmp_path, monkeypatch, module)

    chunks = list(
        backend.synthesize_stream(
            SynthesisRequest(
                text="Hello callback stream",
                voice="sherpa-en-debug",
                job_id="stream-job",
            )
        )
    )

    assert callback_returns == [1, 1]
    assert [chunk.sample_rate_hz for chunk in chunks] == [16000, 16000]
    assert [chunk.is_last for chunk in chunks] == [False, True]
    assert sum(len(chunk.pcm_bytes) for chunk in chunks) == 32


def test_sherpa_backend_runtime_callback_stops_after_cancel(tmp_path, monkeypatch) -> None:
    backend_holder: dict[str, SherpaOnnxBackend] = {}

    def cancel_after_first_callback() -> None:
        backend_holder["backend"].cancel("stream-job")

    module, callback_returns = build_fake_sherpa_onnx_callback_module(
        after_first_callback=cancel_after_first_callback
    )
    backend = build_real_backend(tmp_path, monkeypatch, module)
    backend_holder["backend"] = backend

    chunks = list(
        backend.synthesize_stream(
            SynthesisRequest(
                text="Hello cancellable callback stream",
                voice="sherpa-en-debug",
                job_id="stream-job",
            )
        )
    )

    assert chunks == []
    assert callback_returns == [1, 0]
    assert backend.is_cancelled("stream-job") is False


def test_sherpa_backend_runtime_synthesis_callback_stops_after_cancel(
    tmp_path,
    monkeypatch,
) -> None:
    backend_holder: dict[str, SherpaOnnxBackend] = {}

    def cancel_after_first_callback() -> None:
        backend_holder["backend"].cancel("job-to-cancel")

    module, callback_returns = build_fake_sherpa_onnx_callback_module(
        after_first_callback=cancel_after_first_callback
    )
    backend = build_real_backend(tmp_path, monkeypatch, module)
    backend_holder["backend"] = backend

    result = backend.synthesize(
        SynthesisRequest(
            text="Hello cancellable runtime generation",
            voice="sherpa-en-debug",
            job_id="job-to-cancel",
        )
    )

    assert result.audio_bytes[:4] == b"RIFF"
    assert callback_returns == [1, 0]
    assert backend.is_cancelled("job-to-cancel") is True


def test_sherpa_backend_real_stream_falls_back_without_callback(tmp_path, monkeypatch) -> None:
    backend = build_real_backend(tmp_path, monkeypatch, build_fake_sherpa_onnx_module())

    chunks = list(
        backend.synthesize_stream(
            SynthesisRequest(
                text="Hello fallback stream",
                voice="sherpa-en-debug",
                job_id="stream-job",
            )
        )
    )

    assert chunks
    assert chunks[-1].is_last is True
    assert sum(len(chunk.pcm_bytes) for chunk in chunks) > 32
