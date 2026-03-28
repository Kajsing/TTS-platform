from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ErrorBody:
    type: str
    message: str
    param: str | None = None
    request_id: str = field(default_factory=lambda: str(uuid4()))
    details: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "message": self.message,
            "param": self.param,
            "request_id": self.request_id,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class APIError(Exception):
    status_code: int
    error: ErrorBody
    headers: dict[str, str] = field(default_factory=dict)

    def to_response(self) -> dict[str, object]:
        return {"error": self.error.as_dict()}


def invalid_request(
    message: str,
    *,
    param: str | None = None,
    details: dict[str, object] | None = None,
) -> APIError:
    return APIError(
        status_code=400,
        error=ErrorBody(
            type="invalid_request",
            message=message,
            param=param,
            details=details or {},
        ),
    )


def unauthorized(
    message: str = "Authentication required.",
    *,
    details: dict[str, object] | None = None,
) -> APIError:
    return APIError(
        status_code=401,
        error=ErrorBody(
            type="unauthorized",
            message=message,
            details=details or {},
        ),
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden_origin(
    message: str = "Origin is not allowed.",
    *,
    details: dict[str, object] | None = None,
) -> APIError:
    return APIError(
        status_code=403,
        error=ErrorBody(
            type="forbidden_origin",
            message=message,
            details=details or {},
        ),
    )


def not_found(
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> APIError:
    return APIError(
        status_code=404,
        error=ErrorBody(
            type="not_found",
            message=message,
            details=details or {},
        ),
    )


def conflict(
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> APIError:
    return APIError(
        status_code=409,
        error=ErrorBody(
            type="conflict",
            message=message,
            details=details or {},
        ),
    )


def rate_limited(
    message: str = "Rate limit exceeded.",
    *,
    details: dict[str, object] | None = None,
) -> APIError:
    return APIError(
        status_code=429,
        error=ErrorBody(
            type="rate_limited",
            message=message,
            details=details or {},
        ),
    )


def internal_error(
    message: str = "Internal server error",
    *,
    details: dict[str, object] | None = None,
) -> APIError:
    return APIError(
        status_code=500,
        error=ErrorBody(
            type="internal_error",
            message=message,
            details=details or {},
        ),
    )


def engine_error(
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> APIError:
    return APIError(
        status_code=500,
        error=ErrorBody(
            type="engine_error",
            message=message,
            details=details or {},
        ),
    )
