"""Low-sensitivity local status and a short, fail-safe maintenance reservation.

This module never stops a process. The Windows owner remains responsible for
verifying its launcher/task before stopping it. Reservations prevent new work
between the final idle check and that owner-controlled stop.
"""

from __future__ import annotations

import ctypes
import ipaddress
import os
import secrets
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from .errors import APIError, ErrorBody

PREFIX = "/v1/service"
MAINTENANCE_SECONDS = 15


def _error(kind: str, message: str, status: int) -> APIError:
    return APIError(status_code=status, error=ErrorBody(type=kind, message=message))


class ServiceControlState:
    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self.instance_id = str(uuid4())
        self._clock = clock
        self._lock = threading.RLock()
        self._requests = 0
        self._reservation: str | None = None
        self._expires = 0.0

    def _reserved(self) -> bool:
        if self._reservation and self._clock() >= self._expires:
            self._reservation = None
        return self._reservation is not None

    def enter(self) -> bool:
        with self._lock:
            if self._reserved():
                return False
            self._requests += 1
            return True

    def leave(self) -> None:
        with self._lock:
            self._requests = max(0, self._requests - 1)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {"active_requests": self._requests, "maintenance": self._reserved()}

    def reserve(self, instance_id: str, has_background_work: Callable[[], bool]) -> str:
        with self._lock:
            if instance_id != self.instance_id:
                raise _error(
                    "service_instance_changed", "The service restarted; refresh its status.", 409
                )
            if self._reserved():
                raise _error(
                    "service_maintenance_busy", "Another service operation is in progress.", 409
                )
            if self._requests or has_background_work():
                raise _error(
                    "service_busy", "The service still has active work. Nothing was stopped.", 409
                )
            self._reservation = secrets.token_urlsafe(32)
            self._expires = self._clock() + MAINTENANCE_SECONDS
            return self._reservation

    def release(self, reservation: str) -> bool:
        with self._lock:
            if not reservation.isascii() or not self._reserved() or not secrets.compare_digest(
                reservation, self._reservation or ""
            ):
                return False
            self._reservation = None
            return True


class ServiceActivityMiddleware:
    """Track complete HTTP/WS lifetimes, including synchronous synthesis.

    Workers outliving their creation request are counted by their job managers.
    Status/health reads remain available while a reservation is held. Unknown
    routes and untrusted requests cannot bypass authentication via this middleware.
    """

    def __init__(self, app, state: ServiceControlState) -> None:
        self.app = app
        self.state = state

    async def __call__(self, scope, receive, send) -> None:
        kind = scope["type"]
        path = scope.get("path", "")
        status_read = scope.get("method") == "GET" and path in {"/v1/health", "/v1/voices"}
        if kind not in {"http", "websocket"} or path.startswith(PREFIX + "/") or status_read:
            await self.app(scope, receive, send)
            return
        if not self.state.enter():
            if kind == "websocket":
                await send(
                    {
                        "type": "websocket.close",
                        "code": 1013,
                        "reason": "Local service maintenance; retry shortly.",
                    }
                )
            else:
                response = JSONResponse(
                    _error(
                        "service_maintenance", "Local service maintenance; retry shortly.", 503
                    ).to_response(),
                    status_code=503,
                    headers={"Retry-After": str(MAINTENANCE_SECONDS)},
                )
                await response(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            self.state.leave()


def activity_snapshot(container) -> dict[str, int]:
    reader = container.reader.service
    exports = container.reader_exports
    return {
        "active_requests": int(container.service_control.snapshot()["active_requests"]),
        "active_streams": int(container.streaming_metrics.snapshot()["active_streams"]),
        "content_leases": reader.content_leases.active_lease_count() if reader else 0,
        "pending_exports": exports.active_count() if exports else 0,
        "pending_jobs": container.job_manager.active_count(),
    }


def _working_set_bytes() -> int | None:
    if os.name != "nt":
        return None  # Do not present a platform's historical peak as current RAM.
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            *[
                (name, ctypes.c_size_t)
                for name in (
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                    "PrivateUsage",
                )
            ],
        ]

    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return int(counters.WorkingSetSize)
    except (OSError, AttributeError):
        pass
    return None


def process_resources() -> dict[str, object]:
    times = os.times()
    return {
        "scope": "service_process",
        "process_id": os.getpid(),
        "cpu_seconds": times.user + times.system,
        "sample_monotonic_s": monotonic(),
        "logical_processors": os.cpu_count(),
        "working_set_bytes": _working_set_bytes(),
    }


def _native_owner(request: Request) -> None:
    try:
        local = ipaddress.ip_address(request.client.host if request.client else "").is_loopback
    except ValueError:
        local = False
    if not local or "origin" in request.headers:
        raise _error(
            "service_local_only", "Service management requires a native local client.", 403
        )
    if not request.app.state.container.auth.enabled:
        raise _error(
            "service_auth_required", "Enable local token authentication for Service Center.", 503
        )


class MaintenanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: str = Field(min_length=1, max_length=64)


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reservation: str = Field(min_length=1, max_length=128)


def build_service_control_router() -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["local-service"])

    @router.get("/status")
    def status(request: Request):
        _native_owner(request)
        container = request.app.state.container
        default = container.voice_registry.default_voice
        return {
            "contract_version": 1,
            "instance_id": container.service_control.instance_id,
            "backend_ready": container.backend_ready,
            "default_voice_loaded": container.default_voice_loaded,
            "default_voice_id": default.id if default else None,
            "default_voice_name": default.name if default else None,
            "voice_count": len(container.voice_registry.list()),
            "uptime_s": max(
                0, int((datetime.now(timezone.utc) - container.started_at).total_seconds())
            ),
            "reader_ready": container.reader.database_ready,
            "activity": activity_snapshot(container),
            "maintenance": container.service_control.snapshot()["maintenance"],
            "resources": process_resources(),
        }

    @router.post("/maintenance")
    def reserve(request: Request, payload: MaintenanceRequest):
        _native_owner(request)
        container = request.app.state.container
        reservation = container.service_control.reserve(
            payload.instance_id, lambda: any(activity_snapshot(container).values())
        )
        return {"reservation": reservation, "expires_in_seconds": MAINTENANCE_SECONDS}

    @router.post("/maintenance/release")
    def release(request: Request, payload: ReleaseRequest):
        _native_owner(request)
        return {
            "released": request.app.state.container.service_control.release(payload.reservation)
        }

    return router
