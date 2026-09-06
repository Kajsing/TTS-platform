import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from test_sherpa_onnx_backend import build_fake_sherpa_onnx_module
from tts_core.backends.sherpa_onnx import (
    SherpaOnnxBackend,
    SherpaOnnxBackendSettings,
    build_stub_voice,
)
from tts_core.models import SynthesisRequest


def test_kokoro_bundle_shares_one_engine_but_keeps_per_request_speaker_ids(tmp_path, monkeypatch):
    models = tmp_path / "models/voices"
    directory = models / "bundle"
    directory.mkdir(parents=True)
    for name in ("model.onnx", "voices.bin", "tokens.txt", "us.txt", "other.txt"):
        (directory / name).write_text("synthetic", encoding="utf-8")
    (directory / "espeak").mkdir()
    voices = [
        replace(build_stub_voice(), id=f"speaker-{i}", source="models/voices/bundle")
        for i in range(21)
    ]
    configs = {
        voice.id: {
            "model_type": "kokoro",
            "model": "model.onnx",
            "voices": "voices.bin",
            "tokens": "tokens.txt",
            "data_dir": "espeak",
            "lexicon": "us.txt",
            "speaker_id": i,
        }
        for i, voice in enumerate(voices)
    }
    configs[voices[20].id]["lexicon"] = "other.txt"
    module = build_fake_sherpa_onnx_module()
    constructed, spoken = [], []
    active = maximum_active = 0
    counter_lock = threading.Lock()
    original = module.OfflineTts

    class RecordedRuntime(original):
        def __init__(self, config):
            super().__init__(config)
            constructed.append(self)

        def generate(self, text, generation_config):
            nonlocal active, maximum_active
            with counter_lock:
                active += 1
                maximum_active = max(maximum_active, active)
                spoken.append(generation_config.sid)
            try:
                time.sleep(0.005)
                return super().generate(text, generation_config)
            finally:
                with counter_lock:
                    active -= 1

    module.OfflineTts = RecordedRuntime
    monkeypatch.setattr("tts_core.backends.sherpa_onnx.importlib.import_module", lambda _: module)
    backend = SherpaOnnxBackend(
        models_root=models,
        voices=voices,
        settings=SherpaOnnxBackendSettings(runtime_mode="real"),
        voice_runtime_configs=configs,
    )
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(backend.warmup, [voice.id for voice in voices[:20]]))
    assert len(constructed) == 1
    for i, voice in enumerate(voices[:20]):
        result = backend.synthesize(SynthesisRequest(text="Short preview", voice=voice.id))
        assert result.audio_bytes[:4] == b"RIFF"
        assert spoken[-1] == i
        assert backend._runtime_by_voice_id[voice.id] is backend._runtime_by_voice_id[voices[0].id]
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(
            workers.map(
                backend.synthesize,
                [SynthesisRequest(text="Concurrent fixed sample", voice=v.id) for v in voices[:20]],
            )
        )
    assert all(r.audio_bytes[:4] == b"RIFF" for r in results)
    assert maximum_active == 1
    assert sorted(spoken[20:]) == list(range(20))
    # A different lexicon is a different runtime, even with identical weights.
    backend.warmup(voices[20].id)
    assert len(constructed) == 2
    assert (
        backend._runtime_by_voice_id[voices[20].id]
        is not backend._runtime_by_voice_id[voices[0].id]
    )
