from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from tts_core.models import JobStatus, SynthesisResult, utc_now

from .errors import conflict, not_found, rate_limited
from .observability import ObservabilityState
from .schemas import SynthesizeRequestPayload
from .synthesis import SynthesisCancelledError, SynthesisExecution, SynthesisService


@dataclass(slots=True)
class JobRecord:
    job_id: str
    status: JobStatus
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    error_message: str | None = None
    result: SynthesisResult | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "error_message": self.error_message,
            "result_available": self.result is not None,
            "result_format": self.result.format.value if self.result is not None else None,
        }


@dataclass(slots=True)
class InMemoryJobManager:
    max_workers: int
    backend: object
    observability: ObservabilityState | None = None
    completed_job_ttl_seconds: int = 300
    max_stored_jobs: int = 128
    max_job_seconds: float = 300
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _jobs: dict[str, JobRecord] = field(default_factory=dict)
    _executions: dict[str, SynthesisExecution] = field(default_factory=dict)
    _futures: dict[str, Future[None]] = field(default_factory=dict)
    _timers: dict[str, threading.Timer] = field(default_factory=dict)
    _executor: ThreadPoolExecutor = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="tts-job",
        )

    def create_job(
        self,
        payload: SynthesizeRequestPayload,
        *,
        synthesis_service: SynthesisService,
    ) -> JobRecord:
        with self._lock:
            self._ensure_job_capacity_locked()

        job_id = str(uuid4())
        execution = synthesis_service.prepare_request(payload, job_id=job_id)
        record = JobRecord(job_id=job_id, status=JobStatus.QUEUED)
        timeout_timer = threading.Timer(
            self.max_job_seconds,
            self._timeout_job,
            args=(job_id,),
        )
        timeout_timer.daemon = True
        with self._lock:
            self._ensure_job_capacity_locked()
            self._jobs[job_id] = record
            self._executions[job_id] = execution
            self._timers[job_id] = timeout_timer
            self._futures[job_id] = self._executor.submit(
                self._run_job,
                job_id,
                execution,
                synthesis_service,
            )
            timeout_timer.start()
        self._record_job_event("created")
        return record

    def get_job(self, job_id: str) -> JobRecord:
        with self._lock:
            self._cleanup_locked()
            record = self._jobs.get(job_id)
            if record is None:
                raise not_found("Job not found.", details={"job_id": job_id})
            return record

    def get_job_result(self, job_id: str) -> SynthesisResult:
        record = self.get_job(job_id)
        if record.result is None:
            raise conflict(
                "Job result is not available.",
                details={"job_id": job_id, "status": record.status.value},
            )
        return record.result

    def cancel_job(self, job_id: str) -> JobRecord:
        clear_backend_cancel = False
        with self._lock:
            self._cleanup_locked()
            record = self._jobs.get(job_id)
            future = self._futures.get(job_id)
            if record is None:
                raise not_found("Job not found.", details={"job_id": job_id})
            if record.status in {
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                return record
            if future is not None:
                clear_backend_cancel = future.cancel()
            self.backend.cancel(job_id)
            self._mark_cancelled_locked(record)
            self._cancel_timeout_locked(job_id)
        if clear_backend_cancel:
            self._clear_backend_cancel(job_id)
        return record

    def _run_job(
        self,
        job_id: str,
        execution: SynthesisExecution,
        synthesis_service: SynthesisService,
    ) -> None:
        clear_backend_cancel = False
        with self._lock:
            record = self._jobs[job_id]
            if record.status != JobStatus.QUEUED:
                self._cancel_timeout_locked(job_id)
                clear_backend_cancel = True
            else:
                record.status = JobStatus.RUNNING
                record.updated_at = utc_now()
        if clear_backend_cancel:
            self._clear_backend_cancel(job_id)
            return

        try:
            result = synthesis_service.synthesize_execution(execution)
        except SynthesisCancelledError:
            with self._lock:
                record = self._jobs[job_id]
                if record.status == JobStatus.RUNNING:
                    self._mark_cancelled_locked(record)
                self._cancel_timeout_locked(job_id)
            self._clear_backend_cancel(job_id)
            return
        except Exception as exc:  # pragma: no cover - exercised via API tests
            with self._lock:
                record = self._jobs[job_id]
                if record.status == JobStatus.RUNNING:
                    record.status = JobStatus.FAILED
                    record.error_message = str(exc)
                    record.updated_at = utc_now()
                    self._record_job_event("failed")
                self._cancel_timeout_locked(job_id)
            self._clear_backend_cancel(job_id)
            return

        with self._lock:
            record = self._jobs[job_id]
            if record.status == JobStatus.RUNNING:
                record.status = JobStatus.COMPLETED
                record.result = result
                record.updated_at = utc_now()
                self._record_job_event("completed")
            self._cancel_timeout_locked(job_id)
            self._cleanup_locked()
        self._clear_backend_cancel(job_id)

    def _timeout_job(self, job_id: str) -> None:
        clear_backend_cancel = False
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None or record.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                self._timers.pop(job_id, None)
                return
            future = self._futures.get(job_id)
            if future is not None:
                clear_backend_cancel = future.cancel()
            self.backend.cancel(job_id)
            record.status = JobStatus.FAILED
            record.result = None
            record.error_message = "Job exceeded max_job_seconds."
            record.updated_at = utc_now()
            self._timers.pop(job_id, None)
            self._record_job_event("failed")
        if clear_backend_cancel:
            self._clear_backend_cancel(job_id)

    def _ensure_job_capacity_locked(self) -> None:
        self._cleanup_locked()
        if len(self._jobs) < self.max_stored_jobs:
            return

        terminal_jobs = self._terminal_jobs_locked()
        while len(self._jobs) >= self.max_stored_jobs and terminal_jobs:
            job_id, _ = terminal_jobs.pop(0)
            self._drop_job_locked(job_id)

        if len(self._jobs) >= self.max_stored_jobs:
            raise rate_limited(
                "Job queue is full.",
                details={
                    "max_stored_jobs": self.max_stored_jobs,
                    "active_jobs": self._active_job_count_locked(),
                },
            )

    def _cleanup_locked(self) -> None:
        now = utc_now()
        expired_job_ids = [
            job_id
            for job_id, record in self._jobs.items()
            if record.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
            and record.updated_at <= now - timedelta(seconds=self.completed_job_ttl_seconds)
        ]
        for job_id in expired_job_ids:
            self._drop_job_locked(job_id)

        terminal_jobs = self._terminal_jobs_locked()
        overflow = len(self._jobs) - self.max_stored_jobs
        if overflow <= 0:
            return
        for job_id, _ in terminal_jobs[:overflow]:
            self._drop_job_locked(job_id)

    def _terminal_jobs_locked(self) -> list[tuple[str, JobRecord]]:
        return sorted(
            (
                (job_id, record)
                for job_id, record in self._jobs.items()
                if record.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
            ),
            key=lambda item: item[1].updated_at,
        )

    def _active_job_count_locked(self) -> int:
        return sum(
            1
            for record in self._jobs.values()
            if record.status in {JobStatus.QUEUED, JobStatus.RUNNING}
        )

    def _drop_job_locked(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        self._executions.pop(job_id, None)
        self._futures.pop(job_id, None)
        self._cancel_timeout_locked(job_id)
        self._record_job_event("cleaned")

    def _mark_cancelled_locked(self, record: JobRecord) -> None:
        record.status = JobStatus.CANCELLED
        record.result = None
        record.error_message = None
        record.updated_at = utc_now()
        self._record_job_event("cancelled")

    def _clear_backend_cancel(self, job_id: str) -> None:
        clear_cancel = getattr(self.backend, "clear_cancel", None)
        if clear_cancel is not None:
            clear_cancel(job_id)

    def _cancel_timeout_locked(self, job_id: str) -> None:
        timer = self._timers.pop(job_id, None)
        if timer is not None:
            timer.cancel()

    def _record_job_event(self, event: str) -> None:
        if self.observability is not None:
            self.observability.job_metrics.record(event)
