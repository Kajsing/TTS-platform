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
