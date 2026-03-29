from __future__ import annotations

import importlib
import math
import threading
from array import array
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tts_core.audio import encode_wav_pcm16
from tts_core.models import (
    AudioChunk,
    SynthesisRequest,
    SynthesisResult,
    VoiceCapabilities,
    VoiceDescriptor,
)
from tts_core.registry import VoiceNotFoundError

from .base import BackendError, BackendNotReadyError


def build_stub_voice() -> VoiceDescriptor:
    return VoiceDescriptor(
        id="sherpa-en-debug",
        name="Sherpa English Debug",
        engine="sherpa_onnx",
        language="en",
        sample_rate_hz=24000,
        license="unknown",
        source="models/voices/sherpa-en-debug",
        quality_tier="development",
        latency_tier="unknown",
        tags=("stub", "debug"),
        capabilities=VoiceCapabilities(
            supports_pitch=False,
            supports_streaming=False,
            supports_multi_speaker=False,
        ),
    )


@dataclass(frozen=True, slots=True)
class SherpaOnnxBackendSettings:
    runtime_mode: str = "auto"
    provider: str = "cpu"
    num_threads: int = 1
    debug: bool = False
    max_num_sentences: int = 1


@dataclass(frozen=True, slots=True)
class SherpaOnnxVoiceRuntimeConfig:
    model_type: str
    model: str = ""
    tokens: str = ""
    data_dir: str = ""
    lexicon: str = ""
    voices: str = ""
    acoustic_model: str = ""
    vocoder: str = ""
    rule_fsts: tuple[str, ...] = ()
    speaker_id: int = 0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SherpaOnnxVoiceRuntimeConfig":
        model_type = str(data.get("model_type", "")).lower().strip()
        if model_type not in {"vits", "matcha", "kokoro", "kitten"}:
            raise BackendNotReadyError(
                "Unsupported sherpa-onnx model_type. Expected one of: vits, matcha, kokoro, kitten."
            )

        rule_fsts_raw = data.get("rule_fsts", [])
        if isinstance(rule_fsts_raw, str):
            rule_fsts = tuple(part.strip() for part in rule_fsts_raw.split(",") if part.strip())
        elif isinstance(rule_fsts_raw, list):
            rule_fsts = tuple(str(part).strip() for part in rule_fsts_raw if str(part).strip())
        else:
            raise BackendNotReadyError("sherpa-onnx rule_fsts must be a string or list.")

        return cls(
            model_type=model_type,
            model=str(data.get("model", "")),
            tokens=str(data.get("tokens", "")),
            data_dir=str(data.get("data_dir", "")),
            lexicon=str(data.get("lexicon", "")),
            voices=str(data.get("voices", "")),
            acoustic_model=str(data.get("acoustic_model", "")),
            vocoder=str(data.get("vocoder", "")),
            rule_fsts=rule_fsts,
            speaker_id=int(data.get("speaker_id", 0)),
        )


@dataclass(slots=True)
class SherpaOnnxBackend:
    models_root: Path
    voices: Sequence[VoiceDescriptor] = field(default_factory=lambda: (build_stub_voice(),))
    settings: SherpaOnnxBackendSettings = field(default_factory=SherpaOnnxBackendSettings)
    voice_runtime_configs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    name: str = "sherpa_onnx"
    _cancelled_job_ids: set[str] = field(default_factory=set, init=False, repr=False)
    _cancel_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _runtime_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _runtime_by_voice_id: dict[str, object] = field(default_factory=dict, init=False, repr=False)
    _module_cache: object | None = field(default=None, init=False, repr=False)
    _module_missing: bool = field(default=False, init=False, repr=False)

    def list_voices(self) -> list[VoiceDescriptor]:
        return list(self.voices)

    def snapshot(self) -> dict[str, object]:
        with self._runtime_lock:
            loaded_real_voices = sorted(self._runtime_by_voice_id)
        return {
            "name": self.name,
            "runtime_mode": self.settings.runtime_mode,
            "provider": self.settings.provider,
            "configured_real_voices": len(self.voice_runtime_configs),
            "loaded_real_voices": loaded_real_voices,
            "module_loaded": self._module_cache is not None,
        }

    def warmup(self, voice_id: str | None = None) -> None:
        if voice_id is None:
            return
        self._resolve_voice(voice_id)
        if self.settings.runtime_mode == "stub":
            return
        runtime_config = self._get_runtime_config(voice_id)
        if runtime_config is None:
            if self.settings.runtime_mode == "real":
                raise BackendNotReadyError(
                    f"Voice '{voice_id}' is missing sherpa-onnx backend configuration."
                )
            return
        self._get_or_create_runtime(voice_id, runtime_config)

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        voice = self._resolve_voice(request.voice)
        runtime_config = self._get_runtime_config(request.voice)
        if runtime_config is not None and self.settings.runtime_mode != "stub":
            return self._synthesize_with_runtime(request, voice, runtime_config)
        if self.settings.runtime_mode == "real":
            raise BackendNotReadyError(
                f"Voice '{request.voice}' is missing sherpa-onnx backend configuration."
            )
        return self._synthesize_with_stub(request, voice)

    def synthesize_stream(self, request: SynthesisRequest) -> Iterator[AudioChunk]:
        voice = self._resolve_voice(request.voice)
        runtime_config = self._get_runtime_config(request.voice)
        if runtime_config is not None and self.settings.runtime_mode != "stub":
            pcm_bytes, sample_rate_hz = self._generate_runtime_pcm(request, runtime_config)
        elif self.settings.runtime_mode == "real":
            raise BackendNotReadyError(
                f"Voice '{request.voice}' is missing sherpa-onnx backend configuration."
            )
        else:
            pcm_bytes = self._render_pcm16(
                request.text,
                sample_rate_hz=voice.sample_rate_hz,
                rate=request.prosody.rate,
                volume=request.prosody.volume,
                pitch=request.prosody.pitch,
            )
            sample_rate_hz = voice.sample_rate_hz

        job_id = request.job_id or "stream-job"
        bytes_per_frame = 2
        chunk_size = max(
            bytes_per_frame,
            int(
                sample_rate_hz
                * bytes_per_frame
                * max(request.options.stream_frame_ms, 10)
                / 1000
            ),
        )
        total_size = len(pcm_bytes)
        chunk_index = 0

        for start in range(0, total_size, chunk_size):
            if self._is_cancelled(job_id):
                self._clear_cancel(job_id)
                return

            pcm_chunk = pcm_bytes[start : start + chunk_size]
            duration_ms = int(len(pcm_chunk) / bytes_per_frame / sample_rate_hz * 1000)
            yield AudioChunk(
                job_id=job_id,
                chunk_index=chunk_index,
                sample_rate_hz=sample_rate_hz,
                channels=1,
                pcm_bytes=pcm_chunk,
                duration_ms=max(duration_ms, 1),
                is_last=start + chunk_size >= total_size,
            )
            chunk_index += 1

        self._clear_cancel(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._cancel_lock:
            self._cancelled_job_ids.add(job_id)
        return True

    def _synthesize_with_stub(
        self,
        request: SynthesisRequest,
        voice: VoiceDescriptor,
    ) -> SynthesisResult:
        pcm_bytes = self._render_pcm16(
            request.text,
            sample_rate_hz=voice.sample_rate_hz,
            rate=request.prosody.rate,
            volume=request.prosody.volume,
            pitch=request.prosody.pitch,
        )
        wav_bytes = encode_wav_pcm16(
            pcm_bytes,
            sample_rate_hz=voice.sample_rate_hz,
            channels=1,
        )
        return SynthesisResult(
            audio_bytes=wav_bytes,
            sample_rate_hz=voice.sample_rate_hz,
            channels=1,
        )

    def _synthesize_with_runtime(
        self,
        request: SynthesisRequest,
        voice: VoiceDescriptor,
        runtime_config: SherpaOnnxVoiceRuntimeConfig,
    ) -> SynthesisResult:
        pcm_bytes, sample_rate_hz = self._generate_runtime_pcm(request, runtime_config)
        wav_bytes = encode_wav_pcm16(
            pcm_bytes,
            sample_rate_hz=sample_rate_hz or voice.sample_rate_hz,
            channels=1,
        )
        return SynthesisResult(
            audio_bytes=wav_bytes,
            sample_rate_hz=sample_rate_hz or voice.sample_rate_hz,
            channels=1,
        )

    def _generate_runtime_pcm(
        self,
        request: SynthesisRequest,
        runtime_config: SherpaOnnxVoiceRuntimeConfig,
    ) -> tuple[bytes, int]:
        runtime = self._get_or_create_runtime(request.voice, runtime_config)
        module = self._load_runtime_module()
        generation_config = module.GenerationConfig()
        generation_config.sid = runtime_config.speaker_id
        generation_config.speed = max(request.prosody.rate, 0.1)
        generation_config.silence_scale = 0.2
        try:
            audio = runtime.generate(request.text, generation_config)
        except Exception as exc:  # pragma: no cover - depends on external runtime
            raise BackendError(f"sherpa-onnx synthesis failed: {exc}") from exc
        if len(audio.samples) == 0:
            raise BackendError("sherpa-onnx returned empty audio.")
        return self._float_samples_to_pcm16(audio.samples), int(audio.sample_rate)

    def _get_or_create_runtime(
        self,
        voice_id: str,
        runtime_config: SherpaOnnxVoiceRuntimeConfig,
    ) -> object:
        with self._runtime_lock:
            runtime = self._runtime_by_voice_id.get(voice_id)
            if runtime is not None:
                return runtime
            resolved = self._resolve_runtime_paths(voice_id, runtime_config)
            module = self._load_runtime_module()
            tts_config = module.OfflineTtsConfig(
                model=module.OfflineTtsModelConfig(
                    vits=module.OfflineTtsVitsModelConfig(
                        model=resolved.model,
                        lexicon=resolved.lexicon,
                        data_dir=resolved.data_dir,
                        tokens=resolved.tokens,
                    ),
                    matcha=module.OfflineTtsMatchaModelConfig(
                        acoustic_model=resolved.acoustic_model,
                        vocoder=resolved.vocoder,
                        lexicon=resolved.lexicon,
                        tokens=resolved.tokens,
                        data_dir=resolved.data_dir,
                    ),
                    kokoro=module.OfflineTtsKokoroModelConfig(
                        model=resolved.model,
                        voices=resolved.voices,
                        tokens=resolved.tokens,
                        data_dir=resolved.data_dir,
                        lexicon=resolved.lexicon,
                    ),
                    kitten=module.OfflineTtsKittenModelConfig(
                        model=resolved.model,
                        voices=resolved.voices,
                        tokens=resolved.tokens,
                        data_dir=resolved.data_dir,
                    ),
                    provider=self.settings.provider,
                    debug=self.settings.debug,
                    num_threads=self.settings.num_threads,
                ),
                rule_fsts=",".join(resolved.rule_fsts),
                max_num_sentences=self.settings.max_num_sentences,
            )
            if not tts_config.validate():
                raise BackendNotReadyError(
                    f"sherpa-onnx config validation failed for voice '{voice_id}'."
                )
            try:
                runtime = module.OfflineTts(tts_config)
            except Exception as exc:  # pragma: no cover - depends on external runtime
                raise BackendNotReadyError(
                    f"Failed to initialize sherpa-onnx runtime for voice '{voice_id}': {exc}"
                ) from exc
            self._runtime_by_voice_id[voice_id] = runtime
            return runtime

    def _resolve_runtime_paths(
        self,
        voice_id: str,
        runtime_config: SherpaOnnxVoiceRuntimeConfig,
    ) -> SherpaOnnxVoiceRuntimeConfig:
        resolved = SherpaOnnxVoiceRuntimeConfig(
            model_type=runtime_config.model_type,
            model=self._resolve_path(runtime_config.model),
            tokens=self._resolve_path(runtime_config.tokens),
            data_dir=self._resolve_path(runtime_config.data_dir),
            lexicon=self._resolve_path(runtime_config.lexicon),
            voices=self._resolve_path(runtime_config.voices),
            acoustic_model=self._resolve_path(runtime_config.acoustic_model),
            vocoder=self._resolve_path(runtime_config.vocoder),
            rule_fsts=tuple(self._resolve_path(path) for path in runtime_config.rule_fsts),
            speaker_id=runtime_config.speaker_id,
        )
        self._validate_runtime_paths(voice_id, resolved)
        return resolved

    def _validate_runtime_paths(
        self,
        voice_id: str,
        runtime_config: SherpaOnnxVoiceRuntimeConfig,
    ) -> None:
        required_paths = {
            "vits": [runtime_config.model],
            "matcha": [runtime_config.acoustic_model, runtime_config.vocoder],
            "kokoro": [
                runtime_config.model,
                runtime_config.voices,
                runtime_config.tokens,
                runtime_config.data_dir,
            ],
            "kitten": [
                runtime_config.model,
                runtime_config.voices,
                runtime_config.tokens,
                runtime_config.data_dir,
            ],
        }[runtime_config.model_type]
        if runtime_config.model_type in {"vits", "matcha"} and not (
            runtime_config.data_dir or runtime_config.tokens
        ):
            raise BackendNotReadyError(
                f"Voice '{voice_id}' must define either data_dir or tokens for "
                f"{runtime_config.model_type}."
            )
        for path in required_paths:
            self._require_existing_path(voice_id, path)
        if runtime_config.tokens:
            self._require_existing_path(voice_id, runtime_config.tokens)
        if runtime_config.data_dir:
            self._require_existing_path(voice_id, runtime_config.data_dir)
        if runtime_config.lexicon:
            self._require_existing_path(voice_id, runtime_config.lexicon)
        for rule_fst in runtime_config.rule_fsts:
            self._require_existing_path(voice_id, rule_fst)

    def _require_existing_path(self, voice_id: str, path_value: str) -> None:
        if not path_value:
            raise BackendNotReadyError(f"Voice '{voice_id}' has an empty backend asset path.")
        path = Path(path_value)
        if not path.exists():
            raise BackendNotReadyError(
                f"Voice '{voice_id}' is missing backend asset: {path.as_posix()}"
            )

    def _resolve_path(self, raw_path: str) -> str:
        if not raw_path:
            return ""
        path = Path(raw_path)
        if path.is_absolute():
            return str(path)
        return str((self._repo_root() / path).resolve())

    def _repo_root(self) -> Path:
        return self.models_root.parent.parent

    def _get_runtime_config(self, voice_id: str) -> SherpaOnnxVoiceRuntimeConfig | None:
        raw_config = self.voice_runtime_configs.get(voice_id)
        if raw_config is None:
            return None
        return SherpaOnnxVoiceRuntimeConfig.from_mapping(raw_config)

    def _load_runtime_module(self) -> object:
        if self._module_missing:
            raise BackendNotReadyError(
                "The sherpa_onnx package is not installed. Install it to use real backend mode."
            )
        if self._module_cache is not None:
            return self._module_cache
        try:
            self._module_cache = importlib.import_module("sherpa_onnx")
        except ModuleNotFoundError as exc:
            self._module_missing = True
            raise BackendNotReadyError(
                "The sherpa_onnx package is not installed. Install it to use real backend mode."
            ) from exc
        return self._module_cache

    def _resolve_voice(self, voice_id: str) -> VoiceDescriptor:
        for voice in self.voices:
            if voice.id == voice_id:
                return voice
        raise VoiceNotFoundError(f"Unknown voice id for sherpa-onnx backend: {voice_id}")

    def _render_pcm16(
        self,
        text: str,
        *,
        sample_rate_hz: int,
        rate: float,
        volume: float,
        pitch: int,
    ) -> bytes:
        safe_rate = max(rate, 0.25)
        clamped_volume = min(max(volume, 0.0), 1.5)
        amplitude = int(32767 * 0.18 * clamped_volume)
        base_frequency = 170 + max(min(pitch, 24), -24) * 2
        samples = array("h")

        self._append_silence(samples, sample_rate_hz, duration_ms=40)
        for token in self._tokenize(text):
            if token.isspace():
                self._append_silence(samples, sample_rate_hz, duration_ms=30)
                continue

            if token in {".", "!", "?"}:
                self._append_silence(samples, sample_rate_hz, duration_ms=150)
                continue

            if token in {",", ";", ":"}:
                self._append_silence(samples, sample_rate_hz, duration_ms=80)
                continue

            token_duration_ms = max(70, int((80 + len(token) * 28) / safe_rate))
            token_frequency = base_frequency + (sum(ord(char) for char in token) % 110)
            self._append_tone(
                samples,
                sample_rate_hz,
                frequency_hz=token_frequency,
                duration_ms=token_duration_ms,
                amplitude=amplitude,
            )
            self._append_silence(samples, sample_rate_hz, duration_ms=20)

        self._append_silence(samples, sample_rate_hz, duration_ms=60)
        return samples.tobytes()

    def _tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        current = []
        punctuation = {".", ",", "!", "?", ";", ":"}

        for character in text:
            if character.isspace():
                if current:
                    tokens.append("".join(current))
                    current = []
                tokens.append(" ")
                continue
            if character in punctuation:
                if current:
                    tokens.append("".join(current))
                    current = []
                tokens.append(character)
                continue
            current.append(character)

        if current:
            tokens.append("".join(current))
        return tokens

    def _append_silence(
        self,
        samples: array,
        sample_rate_hz: int,
        *,
        duration_ms: int,
    ) -> None:
        silence_samples = int(sample_rate_hz * (duration_ms / 1000))
        samples.extend([0] * silence_samples)

    def _append_tone(
        self,
        samples: array,
        sample_rate_hz: int,
        *,
        frequency_hz: int,
        duration_ms: int,
        amplitude: int,
    ) -> None:
        sample_count = max(1, int(sample_rate_hz * (duration_ms / 1000)))
        attack_count = max(1, int(sample_count * 0.1))
        release_count = max(1, int(sample_count * 0.12))

        for sample_index in range(sample_count):
            attack = min(1.0, sample_index / attack_count)
            release = min(1.0, (sample_count - sample_index - 1) / release_count)
            envelope = min(attack, release, 1.0)
            phase = 2 * math.pi * frequency_hz * (sample_index / sample_rate_hz)
            sample = int(amplitude * envelope * math.sin(phase))
            samples.append(sample)

    def _float_samples_to_pcm16(self, samples: Sequence[float]) -> bytes:
        pcm_samples = array("h")
        for sample in samples:
            clamped = max(-1.0, min(1.0, float(sample)))
            pcm_samples.append(int(clamped * 32767))
        return pcm_samples.tobytes()

    def _is_cancelled(self, job_id: str) -> bool:
        with self._cancel_lock:
            return job_id in self._cancelled_job_ids

    def _clear_cancel(self, job_id: str) -> None:
        with self._cancel_lock:
            self._cancelled_job_ids.discard(job_id)
