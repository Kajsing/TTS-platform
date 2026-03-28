from __future__ import annotations

from tts_core.audio import inspect_wav
from tts_core.backends import SherpaOnnxBackend
from tts_core.models import ProsodySettings, SynthesisRequest


def test_generated_wav_has_expected_structure(tmp_path) -> None:
    backend = SherpaOnnxBackend(models_root=tmp_path)

    result = backend.synthesize(
        SynthesisRequest(text="Hello world", voice="sherpa-en-debug")
    )
    stats = inspect_wav(result.audio_bytes)

    assert stats.sample_rate_hz == 24000
    assert stats.channels == 1
    assert stats.sample_width_bytes == 2
    assert stats.duration_ms >= 200
    assert stats.rms > 500


def test_audio_duration_changes_with_rate_setting(tmp_path) -> None:
    backend = SherpaOnnxBackend(models_root=tmp_path)

    slow_result = backend.synthesize(
        SynthesisRequest(
            text="Hello world this is a rate test.",
            voice="sherpa-en-debug",
            prosody=ProsodySettings(rate=0.8),
        )
    )
    fast_result = backend.synthesize(
        SynthesisRequest(
            text="Hello world this is a rate test.",
            voice="sherpa-en-debug",
            prosody=ProsodySettings(rate=1.4),
        )
    )

    slow_stats = inspect_wav(slow_result.audio_bytes)
    fast_stats = inspect_wav(fast_result.audio_bytes)

    assert slow_stats.duration_ms > fast_stats.duration_ms
    assert abs(slow_stats.rms - fast_stats.rms) < 3000
