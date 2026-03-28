from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field

from fastapi import Request
from starlette.datastructures import Headers

from .auth import AuthState
from .errors import forbidden_origin, rate_limited, unauthorized


@dataclass(frozen=True, slots=True)
class OriginPolicy:
    allowed_origins: tuple[str, ...] = ()

    def validate(self, origin: str | None) -> None:
        if not origin:
            return
        if not self.allowed_origins:
            raise forbidden_origin(details={"origin": origin, "allowed_origins": []})
        if origin not in self.allowed_origins:
            raise forbidden_origin(
                details={
                    "origin": origin,
                    "allowed_origins": list(self.allowed_origins),
                }
            )


@dataclass(slots=True)
class RateLimiter:
    requests_per_minute: int
    window_seconds: int = 60
    _events: dict[str, deque[float]] = field(
        default_factory=lambda: defaultdict(deque),
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self, client_key: str) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events[client_key]
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.requests_per_minute:
                raise rate_limited(
                    details={
                        "requests_per_minute": self.requests_per_minute,
                        "client": client_key,
                    }
                )
            events.append(now)


def extract_bearer_token(request: Request) -> str | None:
    return extract_bearer_token_from_headers(request.headers)


def extract_bearer_token_from_headers(headers: Headers) -> str | None:
    header = headers.get("authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def enforce_write_access(
    request: Request,
    *,
    auth_state: AuthState,
    origin_policy: OriginPolicy,
    rate_limiter: RateLimiter,
) -> None:
    origin_policy.validate(request.headers.get("origin"))
    client_host = request.client.host if request.client is not None else "unknown"
    rate_limiter.check(client_host)

    if not auth_state.enabled:
        return

    provided_token = extract_bearer_token(request)
    if provided_token is None or provided_token != auth_state.token:
        raise unauthorized()


def enforce_headers_access(
    *,
    headers: Headers,
    client_host: str,
    auth_state: AuthState,
    origin_policy: OriginPolicy,
    rate_limiter: RateLimiter,
) -> None:
    origin_policy.validate(headers.get("origin"))
    rate_limiter.check(client_host)

    if not auth_state.enabled:
        return

    provided_token = extract_bearer_token_from_headers(headers)
    if provided_token is None or provided_token != auth_state.token:
        raise unauthorized()


def normalize_origins(raw_origins: Sequence[str]) -> tuple[str, ...]:
    return tuple(origin.strip() for origin in raw_origins if origin.strip())
