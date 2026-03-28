from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(slots=True)
class StreamingMetrics:
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    total_streams: int = 0
    active_streams: int = 0
    completed_streams: int = 0
    cancelled_streams: int = 0
    failed_streams: int = 0
    last_time_to_first_chunk_ms: int | None = None
    total_first_chunk_samples: int = 0
    first_chunk_measurements: int = 0

    def mark_started(self) -> None:
        with self._lock:
            self.total_streams += 1
            self.active_streams += 1

    def mark_first_chunk(self, elapsed_ms: int) -> None:
        with self._lock:
            self.last_time_to_first_chunk_ms = elapsed_ms
            self.total_first_chunk_samples += elapsed_ms
            self.first_chunk_measurements += 1

    def mark_completed(self) -> None:
        with self._lock:
            self.completed_streams += 1
            self.active_streams = max(0, self.active_streams - 1)

    def mark_cancelled(self) -> None:
        with self._lock:
            self.cancelled_streams += 1
            self.active_streams = max(0, self.active_streams - 1)

    def mark_failed(self) -> None:
        with self._lock:
            self.failed_streams += 1
            self.active_streams = max(0, self.active_streams - 1)

    def snapshot(self) -> dict[str, int | float | None]:
        with self._lock:
            average_first_chunk_ms = None
            if self.first_chunk_measurements:
                average_first_chunk_ms = (
                    self.total_first_chunk_samples / self.first_chunk_measurements
                )
            return {
                "total_streams": self.total_streams,
                "active_streams": self.active_streams,
                "completed_streams": self.completed_streams,
                "cancelled_streams": self.cancelled_streams,
                "failed_streams": self.failed_streams,
                "last_time_to_first_chunk_ms": self.last_time_to_first_chunk_ms,
                "average_time_to_first_chunk_ms": average_first_chunk_ms,
            }
