from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field


def configure_structured_logging(log_level: str) -> logging.Logger:
    logger = logging.getLogger("tts_service")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.propagate = False
    return logger


@dataclass(slots=True)
class RequestMetrics:
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    per_endpoint: dict[str, int] = field(default_factory=dict)

    def record(self, *, endpoint: str, status_code: int, latency_ms: float) -> None:
        with self._lock:
            self.request_count += 1
            self.total_latency_ms += latency_ms
            self.per_endpoint[endpoint] = self.per_endpoint.get(endpoint, 0) + 1
            if status_code < 400:
                self.success_count += 1
            else:
                self.failure_count += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            average_latency_ms = (
                self.total_latency_ms / self.request_count if self.request_count else None
            )
            return {
                "request_count": self.request_count,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "average_latency_ms": average_latency_ms,
                "per_endpoint": dict(sorted(self.per_endpoint.items())),
            }


@dataclass(slots=True)
class SynthesisMetrics:
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    cancelled_count: int = 0
    total_latency_ms: float = 0.0
    modes: dict[str, int] = field(default_factory=dict)

    def record(self, *, mode: str, outcome: str, latency_ms: float) -> None:
        with self._lock:
            self.request_count += 1
            self.total_latency_ms += latency_ms
            self.modes[mode] = self.modes.get(mode, 0) + 1
            if outcome == "success":
                self.success_count += 1
            elif outcome == "cancelled":
                self.cancelled_count += 1
            else:
                self.failure_count += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            average_latency_ms = (
                self.total_latency_ms / self.request_count if self.request_count else None
            )
            return {
                "request_count": self.request_count,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "cancelled_count": self.cancelled_count,
                "average_latency_ms": average_latency_ms,
                "modes": dict(sorted(self.modes.items())),
            }


@dataclass(slots=True)
class JobMetrics:
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    created_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    cleaned_count: int = 0

    def record(self, event: str) -> None:
        with self._lock:
            if event == "created":
                self.created_count += 1
            elif event == "completed":
                self.completed_count += 1
            elif event == "failed":
                self.failed_count += 1
            elif event == "cancelled":
                self.cancelled_count += 1
            elif event == "cleaned":
                self.cleaned_count += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "created_count": self.created_count,
                "completed_count": self.completed_count,
                "failed_count": self.failed_count,
                "cancelled_count": self.cancelled_count,
                "cleaned_count": self.cleaned_count,
            }


@dataclass(slots=True)
class ObservabilityState:
    enabled: bool
    logger: logging.Logger
    request_metrics: RequestMetrics = field(default_factory=RequestMetrics)
    synthesis_metrics: SynthesisMetrics = field(default_factory=SynthesisMetrics)
    job_metrics: JobMetrics = field(default_factory=JobMetrics)

    def log_http_request(
        self,
        *,
        request_id: str,
        method: str,
        endpoint: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        if not self.enabled:
            return
        self.logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": method,
                    "endpoint": endpoint,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                    "outcome": "success" if status_code < 400 else "failure",
                }
            )
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "requests": self.request_metrics.snapshot(),
            "synthesis": self.synthesis_metrics.snapshot(),
            "jobs": self.job_metrics.snapshot(),
        }
