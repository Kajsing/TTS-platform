from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .remote_access import RemoteAccessError, RemoteAccessManager, RemoteDevice

MAX_REQUEST_BYTES = 96 * 1024 * 1024
MAX_PAIRING_BYTES = 16 * 1024
MAX_WEBSOCKET_TEXT_BYTES = 128 * 1024
MAX_WEBSOCKET_BINARY_BYTES = 2 * 1024 * 1024
ORDINARY_REQUESTS_PER_MINUTE = 120
PREAUTH_FAILURES_PER_TEN_MINUTES = 5
EXPORT_CREATIONS_PER_MINUTE = 6
MAX_CONCURRENT_REMOTE_STREAMS = 4
MAX_CONCURRENT_REMOTE_UPLOADS = 2
_RESOURCE_ID = r"(?:[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}|\{[a-z_]+\})"


_ALLOWED_REMOTE_ROUTES = (
    ("GET", re.compile(r"^/v1/health$")),
    ("GET", re.compile(r"^/v1/voices$")),
    ("POST", re.compile(r"^/v1/tts$")),
    ("GET", re.compile(r"^/v1/reader/capabilities$")),
    ("GET|POST", re.compile(r"^/v1/reader/folders$")),
    ("PATCH|DELETE", re.compile(rf"^/v1/reader/folders/{_RESOURCE_ID}$")),
    ("POST", re.compile(r"^/v1/reader/folders/move-documents$")),
    (
        "POST",
        re.compile(
            rf"^/v1/reader/folders/{_RESOURCE_ID}/privacy-lock/(?:unlock|relock)$"
        ),
    ),
    ("POST", re.compile(r"^/v1/reader/imports(?:/preview)?$")),
    ("POST", re.compile(rf"^/v1/reader/imports/{_RESOURCE_ID}/commit$")),
    ("DELETE", re.compile(rf"^/v1/reader/imports/{_RESOURCE_ID}$")),
    ("GET|POST", re.compile(r"^/v1/reader/documents$")),
    ("GET|PATCH|DELETE", re.compile(rf"^/v1/reader/documents/{_RESOURCE_ID}$")),
    (
        "POST",
        re.compile(
            rf"^/v1/reader/documents/{_RESOURCE_ID}/"
            r"(?:duplicate-as-editable|restore|append|undo|redo)$"
        ),
    ),
    ("PATCH", re.compile(rf"^/v1/reader/documents/{_RESOURCE_ID}/content$")),
    ("GET", re.compile(rf"^/v1/reader/documents/{_RESOURCE_ID}/blocks$")),
    ("GET|PUT", re.compile(rf"^/v1/reader/documents/{_RESOURCE_ID}/position$")),
    ("GET|POST", re.compile(rf"^/v1/reader/documents/{_RESOURCE_ID}/bookmarks$")),
    ("PATCH|DELETE", re.compile(rf"^/v1/reader/bookmarks/{_RESOURCE_ID}$")),
    ("GET", re.compile(r"^/v1/reader/queue$")),
    ("POST", re.compile(r"^/v1/reader/queue/items$")),
    ("PATCH|DELETE", re.compile(rf"^/v1/reader/queue/items/{_RESOURCE_ID}$")),
    ("POST", re.compile(r"^/v1/reader/queue/reorder$")),
    ("POST", re.compile(rf"^/v1/reader/queue/items/{_RESOURCE_ID}/activate$")),
    ("POST", re.compile(rf"^/v1/reader/queue/advance/{_RESOURCE_ID}$")),
    ("GET|POST", re.compile(r"^/v1/reader/exports$")),
    ("GET|DELETE", re.compile(rf"^/v1/reader/exports/{_RESOURCE_ID}$")),
    ("DELETE", re.compile(rf"^/v1/reader/exports/{_RESOURCE_ID}/history$")),
    ("GET", re.compile(rf"^/v1/reader/exports/{_RESOURCE_ID}/result$")),
    ("GET|PUT", re.compile(r"^/v1/reader/highlighter$")),
    ("GET|POST", re.compile(r"^/v1/reader/rule-sets$")),
    ("PATCH|DELETE", re.compile(rf"^/v1/reader/rule-sets/{_RESOURCE_ID}$")),
    ("GET|POST", re.compile(rf"^/v1/reader/rule-sets/{_RESOURCE_ID}/rules$")),
    ("GET", re.compile(rf"^/v1/reader/rule-sets/{_RESOURCE_ID}/export$")),
    ("PATCH|DELETE", re.compile(rf"^/v1/reader/rules/{_RESOURCE_ID}$")),
    ("POST", re.compile(r"^/v1/reader/rules/preview$")),
    ("POST", re.compile(r"^/v1/reader/rule-imports$")),
    ("WEBSOCKET", re.compile(r"^/v1/reader/stream$")),
)

_DENIED_REMOTE_ROUTES = (
    ("GET|POST", re.compile(r"^/v1/service/(?:status|maintenance(?:/release)?)$")),
    ("GET|POST|PATCH|DELETE", re.compile(r"^/v1/reader/agent(?:-access)?/.*$")),
    ("POST", re.compile(r"^/v1/auth/rotate$")),
    ("POST", re.compile(r"^/v1/tts/jobs$")),
    ("GET|DELETE", re.compile(rf"^/v1/tts/jobs/{_RESOURCE_ID}$")),
    ("GET", re.compile(rf"^/v1/tts/jobs/{_RESOURCE_ID}/result$")),
    ("WEBSOCKET", re.compile(r"^/v1/tts/stream$")),
    ("PUT|DELETE", re.compile(rf"^/v1/reader/folders/{_RESOURCE_ID}/privacy-lock$")),
    (
        "POST",
        re.compile(rf"^/v1/reader/folders/{_RESOURCE_ID}/privacy-lock/recover$"),
    ),
    ("POST", re.compile(r"^/v1/reader/browser-captures$")),
    ("POST", re.compile(rf"^/v1/reader/documents/{_RESOURCE_ID}/desktop-open$")),
    ("GET", re.compile(r"^/v1/reader/desktop/open-requests/next$")),
    ("DELETE", re.compile(rf"^/v1/reader/desktop/open-requests/{_RESOURCE_ID}$")),
    ("GET", re.compile(r"^/v1/reader/diagnostics$")),
    ("GET|POST", re.compile(r"^/v1/reader/remote/(?:status|setup|invitations|devices|disable)$")),
    ("DELETE", re.compile(rf"^/v1/reader/remote/devices/{_RESOURCE_ID}$")),
)


class PairingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: int = Field(ge=1, le=1)
    ticket_id: str = Field(min_length=1, max_length=80)
    ticket_secret: str = Field(min_length=32, max_length=256)
    device_name: str = Field(min_length=1, max_length=80)


class RotationConfirmPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rotation_id: str = Field(min_length=36, max_length=36)
    pending_credential: str = Field(min_length=32, max_length=512)


@dataclass(slots=True)
class _WindowLimiter:
    limit: int
    window_seconds: float
    _events: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            self._prune(events, now)
            return len(events) >= self.limit

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            cutoff = self._prune(events, now)
            if len(events) >= self.limit:
                return False
            events.append(now)
            if len(self._events) > 4096:
                for candidate in tuple(self._events):
                    if not self._events[candidate] or self._events[candidate][-1] <= cutoff:
                        self._events.pop(candidate, None)
            return True

    def _prune(self, events: deque[float], now: float) -> float:
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        return cutoff


@dataclass(slots=True)
class _DeviceLeaseSet:
    limit: int | None = None
    _active: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def try_acquire(self, device_id: str) -> bool:
        with self._lock:
            if device_id in self._active or (
                self.limit is not None and len(self._active) >= self.limit
            ):
                return False
            self._active.add(device_id)
            return True

    def release(self, device_id: str) -> None:
        with self._lock:
            self._active.discard(device_id)


def create_remote_gateway_app(manager: RemoteAccessManager) -> FastAPI:
    app = FastAPI(
        title="TTS Platform Reader Remote Gateway",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    preauth_limiter = _WindowLimiter(PREAUTH_FAILURES_PER_TEN_MINUTES, 600.0)
    device_limiter = _WindowLimiter(ORDINARY_REQUESTS_PER_MINUTE, 60.0)
    export_limiter = _WindowLimiter(EXPORT_CREATIONS_PER_MINUTE, 60.0)
    stream_leases = _DeviceLeaseSet(limit=MAX_CONCURRENT_REMOTE_STREAMS)
    upload_leases = _DeviceLeaseSet(limit=MAX_CONCURRENT_REMOTE_UPLOADS)

    @app.post("/v1/remote/pair")
    async def pair(request: Request) -> JSONResponse:
        client_key = _client_host(request)
        if request.headers.get("origin"):
            return _error(403, "remote_browser_origin_denied", "Browser origins are not allowed.")
        if preauth_limiter.blocked(client_key):
            return _error(
                429,
                "remote_pairing_rate_limited",
                "Too many failed pairing attempts. Try again later.",
                headers={"Retry-After": "600"},
            )
        try:
            body = await _bounded_body(request, MAX_PAIRING_BYTES)
            payload = PairingPayload.model_validate_json(body)
            device, credential = manager.store.consume_invitation(
                payload.ticket_id,
                payload.ticket_secret,
                payload.device_name,
            )
        except (RemoteAccessError, ValidationError, ValueError):
            if not preauth_limiter.allow(client_key):
                return _error(
                    429,
                    "remote_pairing_rate_limited",
                    "Too many failed pairing attempts. Try again later.",
                    headers={"Retry-After": "600"},
                )
            return _error(
                401,
                "remote_pairing_invalid",
                "Pairing invitation is invalid or expired.",
            )
        return _json(
            {
                "contract_version": 1,
                "device": device.to_payload(),
                "credential": credential,
            },
            status_code=201,
        )

    @app.post("/v1/remote/device/rotation")
    async def begin_rotation(request: Request) -> JSONResponse:
        authenticated = _authenticate_request(
            manager, request, device_limiter, preauth_limiter
        )
        if isinstance(authenticated, JSONResponse):
            return authenticated
        rotation_id, credential = manager.store.begin_rotation(authenticated.id)
        return _json(
            {
                "rotation_id": rotation_id,
                "pending_credential": credential,
                "expires_in_seconds": 600,
            }
        )

    @app.post("/v1/remote/device/rotation/confirm")
    async def confirm_rotation(request: Request) -> JSONResponse:
        authenticated = _authenticate_request(
            manager, request, device_limiter, preauth_limiter
        )
        if isinstance(authenticated, JSONResponse):
            return authenticated
        try:
            body = await _bounded_body(request, MAX_PAIRING_BYTES)
            payload = RotationConfirmPayload.model_validate_json(body)
            device = manager.store.confirm_rotation(
                authenticated.id,
                payload.rotation_id,
                payload.pending_credential,
            )
        except (RemoteAccessError, ValidationError, ValueError):
            return _error(
                400,
                "remote_rotation_invalid",
                "Pending remote credential is invalid or expired.",
            )
        return _json({"device": device.to_payload(), "confirmed": True})

    @app.websocket("/v1/reader/stream")
    async def reader_stream(websocket: WebSocket) -> None:
        device = await _authenticate_websocket(
            manager, websocket, device_limiter, preauth_limiter
        )
        if device is None:
            return
        if not stream_leases.try_acquire(device.id):
            await websocket.close(code=1013, reason="One active stream is allowed per device.")
            return
        try:
            await _proxy_websocket(manager, websocket, device)
        finally:
            stream_leases.release(device.id)

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        response_model=None,
    )
    async def proxy_http(path: str, request: Request) -> JSONResponse | StreamingResponse:
        full_path = "/" + path
        if not _proxy_path_is_safe(request, full_path):
            return _error(404, "remote_route_denied", "This operation is not available remotely.")
        if not is_remote_route_allowed(request.method, full_path):
            return _error(404, "remote_route_denied", "This operation is not available remotely.")
        if _query_contains_credentials(request):
            return _error(
                400,
                "remote_query_credential_denied",
                "Credentials are not accepted in query strings.",
            )
        device = _authenticate_request(
            manager, request, device_limiter, preauth_limiter
        )
        if isinstance(device, JSONResponse):
            return device
        is_upload = request.method == "POST" and full_path in {
            "/v1/reader/imports",
            "/v1/reader/imports/preview",
        }
        if is_upload and not upload_leases.try_acquire(device.id):
            return _error(
                429,
                "remote_upload_busy",
                "One active import upload is allowed per device.",
            )
        if (
            request.method == "POST"
            and full_path == "/v1/reader/exports"
            and not export_limiter.allow(device.id)
        ):
            if is_upload:
                upload_leases.release(device.id)
            return _error(
                429,
                "remote_export_rate_limited",
                "Remote export creation limit exceeded.",
                headers={"Retry-After": "60"},
            )
        try:
            body = await _bounded_body(request, MAX_REQUEST_BYTES)
            return await _proxy_http(manager, request, full_path, body)
        except RemoteAccessError as exc:
            return _error(503, "remote_gateway_unavailable", str(exc))
        finally:
            if is_upload:
                upload_leases.release(device.id)

    return app


def is_remote_route_allowed(method: str, path: str) -> bool:
    return classify_remote_route(method, path) == "allow"


def classify_remote_route(method: str, path: str) -> str | None:
    normalized_method = method.upper()
    for methods, pattern in _ALLOWED_REMOTE_ROUTES:
        if normalized_method in methods.split("|") and pattern.fullmatch(path):
            return "allow"
    for methods, pattern in _DENIED_REMOTE_ROUTES:
        if normalized_method in methods.split("|") and pattern.fullmatch(path):
            return "deny"
    return None


def _authenticate_request(
    manager: RemoteAccessManager,
    request: Request,
    limiter: _WindowLimiter,
    failure_limiter: _WindowLimiter,
) -> RemoteDevice | JSONResponse:
    if request.headers.get("origin"):
        return _error(403, "remote_browser_origin_denied", "Browser origins are not allowed.")
    client_key = _client_host(request)
    if failure_limiter.blocked(client_key):
        return _error(
            429,
            "remote_auth_rate_limited",
            "Too many failed authentication attempts. Try again later.",
            headers={"Retry-After": "600"},
        )
    credential = _bearer(request.headers.get("authorization"))
    try:
        device = manager.store.authenticate(credential or "", touch=False)
    except RemoteAccessError:
        if not failure_limiter.allow(client_key):
            return _error(
                429,
                "remote_auth_rate_limited",
                "Too many failed authentication attempts. Try again later.",
                headers={"Retry-After": "600"},
            )
        return _error(401, "remote_unauthorized", "Remote device credential is invalid or revoked.")
    if not limiter.allow(device.id):
        return _error(
            429,
            "remote_rate_limited",
            "Remote device request limit exceeded.",
            headers={"Retry-After": "60"},
        )
    try:
        return manager.store.authenticate(credential or "")
    except RemoteAccessError:
        return _error(401, "remote_unauthorized", "Remote device credential is invalid or revoked.")


async def _authenticate_websocket(
    manager: RemoteAccessManager,
    websocket: WebSocket,
    limiter: _WindowLimiter,
    failure_limiter: _WindowLimiter,
) -> RemoteDevice | None:
    if websocket.headers.get("origin"):
        await websocket.close(code=1008, reason="Browser origins are not allowed.")
        return None
    client_host = websocket.client.host if websocket.client is not None else "unknown"
    if failure_limiter.blocked(client_host):
        await websocket.close(code=1013, reason="Too many failed authentication attempts.")
        return None
    credential = _bearer(websocket.headers.get("authorization")) or ""
    try:
        device = manager.store.authenticate(credential, touch=False)
    except RemoteAccessError:
        if not failure_limiter.allow(client_host):
            await websocket.close(code=1013, reason="Too many failed authentication attempts.")
            return None
        await websocket.close(code=1008, reason="Remote credential is invalid or revoked.")
        return None
    if not limiter.allow(device.id):
        await websocket.close(code=1013, reason="Remote request limit exceeded.")
        return None
    try:
        return manager.store.authenticate(credential)
    except RemoteAccessError:
        await websocket.close(code=1008, reason="Remote credential is invalid or revoked.")
        return None


async def _proxy_http(
    manager: RemoteAccessManager,
    request: Request,
    path: str,
    body: bytes,
) -> StreamingResponse:
    token = manager.local_token()
    upstream_url = f"{manager.local_base_url}{path}"
    if request.url.query:
        upstream_url += "?" + request.url.query
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": request.headers.get("accept", "application/json"),
    }
    for name in ("content-type", "x-reader-privacy-sessions"):
        value = request.headers.get(name)
        if value:
            headers[name] = value
    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))
    try:
        upstream_request = client.build_request(
            request.method,
            upstream_url,
            content=body if body else None,
            headers=headers,
        )
        response = await client.send(upstream_request, stream=True)
    except (httpx.HTTPError, OSError) as exc:
        await client.aclose()
        raise RemoteAccessError("The local Reader service could not be reached.") from exc

    response_headers = {"Cache-Control": "no-store"}
    for name in ("content-type", "content-length", "content-disposition", "retry-after"):
        value = response.headers.get(name)
        if value:
            response_headers[name] = value

    async def stream_body() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_body(),
        status_code=response.status_code,
        headers=response_headers,
    )


async def _proxy_websocket(
    manager: RemoteAccessManager,
    client_socket: WebSocket,
    device: RemoteDevice,
) -> None:
    try:
        from websockets.asyncio.client import connect
    except ImportError:  # pragma: no cover - compatibility with websockets 12
        from websockets import connect  # type: ignore[no-redef]

    token = manager.local_token()
    upstream_url = manager.local_base_url.replace("http://", "ws://", 1)
    upstream_url = upstream_url.replace("https://", "wss://", 1) + "/v1/reader/stream"
    headers = {"Authorization": f"Bearer {token}"}
    privacy = client_socket.headers.get("x-reader-privacy-sessions")
    if privacy:
        headers["x-reader-privacy-sessions"] = privacy
    await client_socket.accept()
    try:
        async with connect(
            upstream_url,
            additional_headers=headers,
            open_timeout=5.0,
            max_size=None,
        ) as upstream:
            tasks = {
                asyncio.create_task(_client_to_upstream(client_socket, upstream)),
                asyncio.create_task(_upstream_to_client(upstream, client_socket)),
                asyncio.create_task(_revocation_watch(manager, device.id)),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                exception = task.exception()
                if exception is not None:
                    raise exception
    except RemoteAccessError:
        await client_socket.close(code=1008, reason="Remote device was revoked.")
    except Exception:
        await client_socket.close(code=1011, reason="Remote Reader stream ended.")


async def _client_to_upstream(client_socket: WebSocket, upstream: Any) -> None:
    while True:
        message = await client_socket.receive()
        message_type = message.get("type")
        if message_type == "websocket.disconnect":
            return
        text = message.get("text")
        data = message.get("bytes")
        if text is not None:
            if len(text.encode("utf-8")) > MAX_WEBSOCKET_TEXT_BYTES:
                raise RemoteAccessError("Remote WebSocket text frame exceeded the limit.")
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise RemoteAccessError("Remote WebSocket text frame is invalid.") from exc
            if _contains_credential_key(decoded):
                raise RemoteAccessError("Credentials are not accepted in WebSocket messages.")
            await upstream.send(text)
        elif data is not None:
            if len(data) > MAX_WEBSOCKET_BINARY_BYTES:
                raise RemoteAccessError("Remote WebSocket binary frame exceeded the limit.")
            await upstream.send(data)


async def _upstream_to_client(upstream: Any, client_socket: WebSocket) -> None:
    async for message in upstream:
        if isinstance(message, str):
            if len(message.encode("utf-8")) > MAX_WEBSOCKET_TEXT_BYTES:
                raise RemoteAccessError("Local WebSocket text frame exceeded the remote limit.")
            await client_socket.send_text(message)
        else:
            data = bytes(message)
            if len(data) > MAX_WEBSOCKET_BINARY_BYTES:
                raise RemoteAccessError("Local WebSocket binary frame exceeded the remote limit.")
            await client_socket.send_bytes(data)


async def _revocation_watch(manager: RemoteAccessManager, device_id: str) -> None:
    while True:
        await asyncio.sleep(0.5)
        if not manager.store.is_active(device_id):
            raise RemoteAccessError("Remote device was revoked.")


async def _bounded_body(request: Request, limit: int) -> bytes:
    raw_length = request.headers.get("content-length")
    if raw_length:
        try:
            if int(raw_length) > limit:
                raise RemoteAccessError("Remote request body exceeded the limit.")
        except ValueError as exc:
            raise RemoteAccessError("Remote request Content-Length is invalid.") from exc
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise RemoteAccessError("Remote request body exceeded the limit.")
        body.extend(chunk)
    return bytes(body)


def _bearer(value: str | None) -> str | None:
    if not value:
        return None
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _client_host(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _query_contains_credentials(request: Request) -> bool:
    credential_names = {
        "auth",
        "auth_token",
        "authorization",
        "credential",
        "ticket_secret",
        "token",
    }
    return any(key.lower() in credential_names for key in request.query_params)


def _proxy_path_is_safe(request: Request, path: str) -> bool:
    raw_path = request.scope.get("raw_path", b"")
    if isinstance(raw_path, bytes) and b"%" in raw_path:
        return False
    if "\\" in path:
        return False
    return all(segment not in {".", ".."} for segment in path.split("/"))


def _contains_credential_key(value: object) -> bool:
    credential_names = {
        "auth",
        "auth_token",
        "authorization",
        "credential",
        "ticket_secret",
        "token",
    }
    if isinstance(value, dict):
        return any(
            str(key).lower() in credential_names or _contains_credential_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_credential_key(item) for item in value)
    return False


def _json(payload: dict[str, object], *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code, headers={"Cache-Control": "no-store"})


def _error(
    status_code: int,
    error_type: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response_headers = {"Cache-Control": "no-store", **(headers or {})}
    return JSONResponse(
        {
            "error": {
                "type": error_type,
                "message": message,
                "param": None,
                "request_id": None,
                "details": {},
            }
        },
        status_code=status_code,
        headers=response_headers,
    )
