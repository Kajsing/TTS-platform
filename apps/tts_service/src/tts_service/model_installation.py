"""Local installation primitives shared by the CLI and Service Center bridge."""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO


class ModelInstallCancelled(Exception):
    """Cancellation is cooperative; it is not accepted inside the commit phase."""


@dataclass
class ModelInstallControl:
    cancelled: Callable[[], bool] = lambda: False
    progress: Callable[[dict[str, object]], None] | None = None
    timeout_seconds: float = 1800
    require_assets: bool = False
    _started: float = field(default_factory=time.monotonic)
    _last_report: float = 0
    _last_phase: str = ""

    def check(self) -> None:
        if self.cancelled():
            raise ModelInstallCancelled("Model installation was cancelled before commit.")
        if time.monotonic() - self._started > self.timeout_seconds:
            raise ModelInstallCancelled("Model installation exceeded its time limit.")

    def report(
        self,
        phase: str,
        *,
        completed: int | None = None,
        total: int | None = None,
        cancellable: bool = True,
        force: bool = False,
    ) -> None:
        if cancellable:
            self.check()
        now = time.monotonic()
        if not force and phase == self._last_phase and now - self._last_report < 0.1:
            return
        self._last_report, self._last_phase = now, phase
        if self.progress is not None:
            self.progress(
                {
                    "phase": phase,
                    "completed": completed,
                    "total": total,
                    "cancellable": cancellable,
                }
            )

    def copy(
        self, source: BinaryIO, target: BinaryIO, *, phase: str, total: int | None = None
    ) -> None:
        completed = 0
        while True:
            self.check()
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            target.write(chunk)
            completed += len(chunk)
            if phase == "extracting":
                self.report(phase)  # Streaming archives have no reliable overall byte total.
            else:
                self.report(phase, completed=completed, total=total)
        if phase != "extracting":
            self.report(phase, completed=completed, total=total, force=True)


def read_snapshot(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def atomic_write(path: Path, content: bytes) -> None:
    """Replace only after a flushed same-directory temporary file is complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    staging = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


@contextmanager
def manifest_lock(path: Path) -> Iterator[None]:
    """Nonblocking cross-process lock. Keep the lock file to avoid inode races."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                "Another model operation is updating the manifest. Try again later."
            ) from exc
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
