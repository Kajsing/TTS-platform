from __future__ import annotations

import os
import re
import threading
import uuid
import wave
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from reader_core import (
    ExportAudioFormat,
    ExportPhase,
    ExportStatus,
    ReaderBlock,
    ReaderCursor,
    ReaderDatabaseError,
    ReaderError,
    ReaderExportJob,
    ReaderValidationError,
)
from speech_rules import RuleContext
from tts_core.audio import decode_wav_pcm16
from tts_core.backends.base import TTSBackend
from tts_core.models import AudioFormat, ProsodySettings, SynthesisOptions, SynthesisRequest
from tts_core.registry import VoiceRegistry
from tts_core.text import ChunkPlanner, SentenceSegmenter, TextNormalizer

from .audio_encoders import AudioEncodingCancelled, FfmpegMp3Encoder
from .observability import ObservabilityState
from .reader_service import ReaderApplicationService
from .reader_streaming import ReaderBlockSlice, ReaderSpeechCompiler

_UNSAFE_FILENAME = re.compile(r"[^\w .()\[\]-]+", flags=re.UNICODE)
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class ReaderExportCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _StagedExport:
    temporary: Path
    destination: Path


class ReaderExportManager:
    """Runs persistent Reader audio exports independently of desktop connections."""

    def __init__(
        self,
        *,
        service: ReaderApplicationService,
        backend: TTSBackend,
        voice_registry: VoiceRegistry,
        normalizer: TextNormalizer,
        segmenter: SentenceSegmenter,
        chunk_planner: ChunkPlanner,
        output_directory: Path,
        max_workers: int,
        observability: ObservabilityState,
        configured_formats: tuple[str, ...] = ("wav",),
        mp3_encoder: FfmpegMp3Encoder | None = None,
    ) -> None:
        self.service = service
        self.backend = backend
        self.voice_registry = voice_registry
        self.output_directory = output_directory.resolve()
        self.output_directory.mkdir(parents=True, exist_ok=True)
        self._normalizer = normalizer
        self._segmenter = segmenter
        self._chunk_planner = chunk_planner
        self._observability = observability
        self._mp3_encoder = mp3_encoder
        self.available_formats = tuple(
            value
            for value in configured_formats
            if value == "wav" or (value == "mp3" and mp3_encoder is not None)
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="reader-export",
        )
        self._lock = threading.RLock()
        self._futures: dict[str, Future[None]] = {}
        for job in self.service.repository.recover_export_jobs():
            self._submit(job.id)

    def create(
        self,
        *,
        document_ids: tuple[str, ...],
        section_ids: tuple[str, ...] = (),
        start_cursor: ReaderCursor | None = None,
        end_cursor: ReaderCursor | None = None,
        voice_id: str | None = None,
        audio_format: ExportAudioFormat = ExportAudioFormat.WAV,
        output_basename: str | None = None,
        overwrite_existing: bool = False,
    ) -> ReaderExportJob:
        if not document_ids or len(document_ids) > 100:
            raise ReaderValidationError("exports require between 1 and 100 documents")
        if len(set(document_ids)) != len(document_ids):
            raise ReaderValidationError("export document IDs must be unique")
        if (section_ids or start_cursor or end_cursor) and len(document_ids) != 1:
            raise ReaderValidationError("sections and source ranges require one document")
        if audio_format.value not in self.available_formats:
            raise ReaderValidationError(
                f"{audio_format.value.upper()} export is not available on this service"
            )
        resolved_voice = voice_id or self._default_voice_id()
        self.voice_registry.get(resolved_voice)
        now = datetime.now(timezone.utc)
        job = self.service.repository.create_export_job(
            ReaderExportJob(
                id=str(uuid.uuid4()),
                status=ExportStatus.QUEUED,
                document_ids=document_ids,
                section_ids=section_ids,
                start_cursor=start_cursor,
                end_cursor=end_cursor,
                voice_id=resolved_voice,
                audio_format=audio_format,
                output_basename=output_basename,
                overwrite_existing=overwrite_existing,
                total_documents=len(document_ids),
                created_at=now,
                updated_at=now,
            )
        )
        self._observability.reader_metrics.record_export("created", 0.0)
        self._submit(job.id)
        return job

    def cancel(self, job_id: str) -> ReaderExportJob:
        job = self.service.repository.request_export_cancel(job_id)
        self.backend.cancel(job_id)
        return job

    def result_path(self, job: ReaderExportJob, index: int = 0) -> Path:
        if job.status is not ExportStatus.COMPLETED:
            raise ReaderValidationError("export result is not ready")
        if index < 0 or index >= len(job.output_files):
            raise ReaderValidationError("export result index is invalid")
        candidate = self._output_path(job.output_files[index])
        if not candidate.is_file():
            raise ReaderValidationError("export result is unavailable")
        return candidate

    def delete(self, job_id: str) -> None:
        job = self.service.repository.get_export_job(job_id)
        if job.status in {ExportStatus.QUEUED, ExportStatus.RUNNING}:
            raise ReaderValidationError(
                "active exports must be cancelled before deletion"
            )
        try:
            for filename in job.output_files:
                self._output_path(filename).unlink(missing_ok=True)
        except OSError as exc:
            raise ReaderDatabaseError("Reader export output could not be removed") from exc
        self.service.repository.delete_export_job(job_id)
        with self._lock:
            self._futures.pop(job_id, None)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _submit(self, job_id: str) -> None:
        with self._lock:
            current = self._futures.get(job_id)
            if current is not None and not current.done():
                return
            self._futures[job_id] = self._executor.submit(self._run, job_id)

    def _output_path(self, filename: str) -> Path:
        candidate = (self.output_directory / filename).resolve()
        if candidate.parent != self.output_directory:
            raise ReaderValidationError("export result path is invalid")
        return candidate

    def _run(self, job_id: str) -> None:
        started_at = monotonic()
        staged: list[_StagedExport] = []
        outcome = "failed"
        try:
            job = self.service.repository.claim_export_job(job_id)
            if job.status is not ExportStatus.RUNNING:
                outcome = job.status.value
                return
            if job.audio_format.value not in self.available_formats:
                raise ReaderValidationError(
                    f"{job.audio_format.value.upper()} export is not available on this service"
                )
            destinations = self._destinations(job)
            self._ensure_destinations_available(destinations, job.overwrite_existing)
            total_documents = len(job.document_ids)
            last_progress: tuple[ExportPhase, int, int, str | None] | None = None

            def overall_percent(document_index: int, document_fraction: float) -> int:
                completed_fraction = (document_index + document_fraction) / total_documents
                return min(96, max(0, int(completed_fraction * 96)))

            def report_progress(
                phase: ExportPhase,
                percent: int,
                completed_documents: int,
                current_document_id: str | None,
            ) -> None:
                nonlocal last_progress
                snapshot = (
                    phase,
                    min(99, max(0, percent)),
                    completed_documents,
                    current_document_id,
                )
                if snapshot == last_progress:
                    return
                self.service.repository.update_export_progress(
                    job_id,
                    completed_documents=completed_documents,
                    current_document_id=current_document_id,
                    output_files=(),
                    progress_phase=phase,
                    progress_percent=snapshot[1],
                )
                last_progress = snapshot

            report_progress(ExportPhase.PREPARING, 0, 0, job.document_ids[0])
            for index, (document_id, destination) in enumerate(
                zip(job.document_ids, destinations, strict=True)
            ):
                self._raise_if_cancelled(job_id)
                temporary = self.output_directory / (
                    f".{job.id}-{index:03d}.{job.audio_format.value}.part"
                )
                temporary.unlink(missing_ok=True)
                synthesis_share = (
                    0.85 if job.audio_format is ExportAudioFormat.MP3 else 0.95
                )

                def report_fragment_progress(
                    completed: int,
                    total: int,
                    *,
                    share: float = synthesis_share,
                    document_index: int = index,
                    current_document_id: str = document_id,
                ) -> None:
                    fraction = share * completed / max(total, 1)
                    report_progress(
                        ExportPhase.SYNTHESIZING,
                        overall_percent(document_index, fraction),
                        document_index,
                        current_document_id,
                    )

                if job.audio_format is ExportAudioFormat.WAV:
                    self._render_document(
                        job,
                        document_id,
                        temporary,
                        progress_callback=report_fragment_progress,
                    )
                else:
                    source_wav = self.output_directory / (
                        f".{job.id}-{index:03d}.source.wav.part"
                    )
                    source_wav.unlink(missing_ok=True)
                    self._render_document(
                        job,
                        document_id,
                        source_wav,
                        progress_callback=report_fragment_progress,
                    )
                    encoder = self._mp3_encoder
                    if encoder is None:
                        raise ReaderValidationError(
                            "MP3 export is not available on this service"
                        )
                    report_progress(
                        ExportPhase.ENCODING,
                        overall_percent(index, 0.90),
                        index,
                        document_id,
                    )
                    encoder.encode(
                        source_wav,
                        temporary,
                        title=self.service.get_document(document_id).title,
                        should_cancel=lambda: self._is_cancel_requested(job.id),
                    )
                    source_wav.unlink(missing_ok=True)
                staged.append(_StagedExport(temporary, destination))
                next_document_id = (
                    job.document_ids[index + 1]
                    if index + 1 < total_documents
                    else None
                )
                report_progress(
                    (
                        ExportPhase.PREPARING
                        if next_document_id is not None
                        else ExportPhase.FINALIZING
                    ),
                    overall_percent(index, 1.0),
                    index + 1,
                    next_document_id,
                )
            self._raise_if_cancelled(job_id)
            report_progress(ExportPhase.FINALIZING, 98, total_documents, None)
            self._ensure_destinations_available(destinations, job.overwrite_existing)
            for item in staged:
                if job.overwrite_existing:
                    os.replace(item.temporary, item.destination)
                else:
                    os.link(item.temporary, item.destination)
                    item.temporary.unlink()
            names = tuple(item.destination.name for item in staged)
            self.service.repository.finish_export_job(
                job_id,
                status=ExportStatus.COMPLETED,
                output_files=names,
            )
            outcome = "completed"
        except (ReaderExportCancelled, AudioEncodingCancelled):
            self.service.repository.finish_export_job(job_id, status=ExportStatus.CANCELLED)
            outcome = "cancelled"
        except Exception as exc:
            try:
                current = self.service.repository.get_export_job(job_id)
                if current.cancel_requested:
                    self.service.repository.finish_export_job(
                        job_id,
                        status=ExportStatus.CANCELLED,
                    )
                    outcome = "cancelled"
                else:
                    self.service.repository.finish_export_job(
                        job_id,
                        status=ExportStatus.FAILED,
                        error_type=type(exc).__name__,
                        error_message="Export failed during audio generation or encoding.",
                    )
            except ReaderError:
                pass
        finally:
            for item in staged:
                item.temporary.unlink(missing_ok=True)
            for temporary in self.output_directory.glob(f".{job_id}-*.part"):
                temporary.unlink(missing_ok=True)
            clear_cancel = getattr(self.backend, "clear_cancel", None)
            if clear_cancel is not None:
                clear_cancel(job_id)
            self._observability.reader_metrics.record_export(
                outcome,
                (monotonic() - started_at) * 1000,
            )

    def _render_document(
        self,
        job: ReaderExportJob,
        document_id: str,
        target: Path,
        *,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        bundle = self.service.get_document_bundle(document_id)
        voice_id = job.voice_id or self._default_voice_id()
        voice = self.voice_registry.get(voice_id)
        slices = self._selected_slices(job, bundle.blocks, document_id)
        rules = self.service.ordered_rules(())
        compiler = ReaderSpeechCompiler(
            self._normalizer,
            self._segmenter,
            self._chunk_planner,
            rule_engine=self.service.rule_engine() if rules else None,
            rules=rules,
            rule_context=RuleContext(
                language=bundle.document.language_hint,
                engine=getattr(self.backend, "name", self.backend.__class__.__name__),
                voice=voice_id,
                document_id=document_id,
            ),
        )
        fragments, _ = compiler.compile_slices_with_warnings(
            slices,
            content_revision=bundle.document.content_revision,
            language_hint=bundle.document.language_hint,
        )
        total_fragments = max(len(fragments), 1)
        if progress_callback is not None:
            progress_callback(0, total_fragments)
        sample_rate: int | None = None
        channels: int | None = None
        with wave.open(str(target), "wb") as output:
            for fragment_index, fragment in enumerate(fragments, start=1):
                self._raise_if_cancelled(job.id)
                result = self.backend.synthesize(
                    SynthesisRequest(
                        text=fragment.spoken_text,
                        voice=voice_id,
                        format=AudioFormat.WAV,
                        prosody=ProsodySettings(
                            sentence_pause_ms=max(120, fragment.pause_ms_hint)
                        ),
                        options=SynthesisOptions(normalize_text=False),
                        language_hint=bundle.document.language_hint,
                        job_id=job.id,
                    )
                )
                pcm, chunk_rate, chunk_channels = decode_wav_pcm16(result.audio_bytes)
                if sample_rate is None:
                    sample_rate, channels = chunk_rate, chunk_channels
                    output.setnchannels(channels)
                    output.setsampwidth(2)
                    output.setframerate(sample_rate)
                elif sample_rate != chunk_rate or channels != chunk_channels:
                    raise ReaderValidationError(
                        "backend returned inconsistent WAV settings during export"
                    )
                output.writeframesraw(pcm)
                pause_frames = int(chunk_rate * min(fragment.pause_ms_hint, 5000) / 1000)
                if pause_frames:
                    output.writeframesraw(b"\0" * pause_frames * chunk_channels * 2)
                if progress_callback is not None:
                    progress_callback(fragment_index, total_fragments)
            if sample_rate is None:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(voice.sample_rate_hz)
                output.writeframes(b"")
                if progress_callback is not None:
                    progress_callback(1, 1)
        with target.open("rb+") as completed:
            completed.flush()
            os.fsync(completed.fileno())

    def _selected_slices(
        self,
        job: ReaderExportJob,
        blocks: tuple[ReaderBlock, ...],
        document_id: str,
    ) -> tuple[ReaderBlockSlice, ...]:
        start = (
            self.service.repository.resolve_cursor(job.start_cursor)
            if job.start_cursor
            else None
        )
        end = (
            self.service.repository.resolve_cursor(job.end_cursor)
            if job.end_cursor
            else None
        )
        if start is not None and start.document_id != document_id:
            raise ReaderValidationError("export start cursor belongs to another document")
        if end is not None and end.document_id != document_id:
            raise ReaderValidationError("export end cursor belongs to another document")
        if start and end and (start.block_ordinal, start.character_offset) > (
            end.block_ordinal,
            end.character_offset,
        ):
            raise ReaderValidationError("export source range is reversed")
        selected_sections = set(job.section_ids)
        available_sections = {block.section_id for block in blocks if block.section_id is not None}
        if not selected_sections.issubset(available_sections):
            raise ReaderValidationError("export section does not belong to the document")
        slices: list[ReaderBlockSlice] = []
        for block in blocks:
            if selected_sections and block.section_id not in selected_sections:
                continue
            if start is not None and block.ordinal < start.block_ordinal:
                continue
            if end is not None and block.ordinal > end.block_ordinal:
                continue
            block_start = (
                start.character_offset
                if start and block.ordinal == start.block_ordinal
                else 0
            )
            block_end = (
                end.character_offset
                if end and block.ordinal == end.block_ordinal
                else len(block.text)
            )
            if block_start > block_end or block_end > len(block.text):
                raise ReaderValidationError("export source range is invalid")
            for offset in range(block_start, block_end, 32_000):
                slices.append(ReaderBlockSlice(block, offset, min(block_end, offset + 32_000)))
        return tuple(slices)

    def _destinations(self, job: ReaderExportJob) -> tuple[Path, ...]:
        result: list[Path] = []
        for index, document_id in enumerate(job.document_ids):
            document = self.service.get_document(document_id)
            requested = job.output_basename if len(job.document_ids) == 1 else None
            base = _safe_basename(requested or document.title)
            if len(job.document_ids) > 1:
                base = f"{index + 1:03d}-{base}"
            candidate = (
                self.output_directory / f"{base}.{job.audio_format.value}"
            ).resolve()
            if candidate.parent != self.output_directory:
                raise ReaderValidationError("export filename escapes the output directory")
            result.append(candidate)
        if len(set(result)) != len(result):
            raise ReaderValidationError("export filenames are not unique")
        return tuple(result)

    @staticmethod
    def _ensure_destinations_available(
        destinations: tuple[Path, ...],
        overwrite: bool,
    ) -> None:
        if not overwrite and any(path.exists() for path in destinations):
            raise FileExistsError("an export destination already exists")

    def _raise_if_cancelled(self, job_id: str) -> None:
        if self._is_cancel_requested(job_id):
            raise ReaderExportCancelled()

    def _is_cancel_requested(self, job_id: str) -> bool:
        return self.service.repository.get_export_job(job_id).cancel_requested

    def _default_voice_id(self) -> str:
        voice = self.voice_registry.default_voice
        if voice is None:
            raise ReaderValidationError("no default voice is configured")
        return voice.id


def resolve_export_directory(service: ReaderApplicationService) -> Path:
    configured = Path(service.config.exports.output_directory).expanduser()
    return configured if configured.is_absolute() else service.reader_home_path / configured


def _safe_basename(value: str) -> str:
    leaf = Path(value.strip()).name
    if leaf.lower().endswith((".wav", ".mp3")):
        leaf = leaf[:-4]
    cleaned = _UNSAFE_FILENAME.sub("_", leaf).strip(" ._")[:120]
    cleaned = cleaned or "reader-export"
    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned
