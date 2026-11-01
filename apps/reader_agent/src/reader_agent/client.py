"""Only HTTP agent routes: no Reader DB, owner token, synthesis or website access."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from .config import AgentConfigurationError, AgentConnection, canonical_id, local_service_url

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RETRY_AFTER_SECONDS = 86_400
API_PREFIX = "v1/reader/agent/"
SAFE_TO_RETRY = frozenset({
    "workspace", "list", "read", "chapters", "deliver", "create_once",
    "content_chapters", "chapter_text", "search",
    "preview_import", "import_chapter", "story_status",
})
REQUEST_BUDGETS = frozenset({"agent", "background", "playback"})


class AgentServiceError(Exception):
    def __init__(
        self,
        outcome: str,
        code: str,
        *,
        retryable: bool = False,
        reason: str | None = None,
        retry_after_seconds: int | None = None,
        request_budget: str | None = None,
    ) -> None:
        self.outcome = outcome
        self.code = code
        self.retryable = retryable
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        self.request_budget = request_budget
        super().__init__(code)

    def payload(self) -> dict[str, object]:
        result: dict[str, object] = {
            "outcome": self.outcome,
            "code": self.code,
            "retryable": self.retryable,
        }
        for key in ("reason", "retry_after_seconds", "request_budget"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


class AgentHttpClient:
    def __init__(
        self,
        connection: AgentConnection,
        *,
        credential_loader: Callable[[], str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.connection = connection
        self._credential_loader = credential_loader or connection.credential
        self._http = httpx.AsyncClient(
            base_url=local_service_url(connection.service_base_url),
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(20.0, connect=3.0),
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
            transport=transport,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def call(
        self,
        operation: str,
        *,
        article_id: str | None = None,
        plan_id: str | None = None,
        **arguments,
    ) -> dict[str, object]:
        routes = {
            "workspace": ("GET", "workspace"),
            "list": ("GET", "articles"),
            "create": ("POST", "articles"),
            "create_once": ("POST", "articles"),
            "read": ("GET", ""),
            "rename": ("PATCH", ""),
            "append": ("POST", "/append"),
            "replace": ("PATCH", "/text"),
            "chapters": ("GET", "/chapters"),
            "deliver": ("POST", "/chapters"),
            "content_chapters": ("GET", "/content-chapters"),
            "chapter_text": ("GET", "/chapter-text"),
            "search": ("GET", "/search"),
            "preview_import": ("POST", "import-plans"),
            "import_chapter": ("POST", ""),
            "story_status": ("GET", "stories/status"),
        }
        if operation not in routes:
            raise AgentServiceError("unauthorized", "unsupported_operation")
        if operation == "create_once" and (
            not isinstance(arguments.get("retry_key"), str)
            or not 1 <= len(arguments["retry_key"]) <= 200
            or not arguments["retry_key"].strip()
            or "\x00" in arguments["retry_key"]
        ):
            raise AgentServiceError("invalid_request", "reader_invalid_request")
        method, path = routes[operation]
        try:
            if operation == "import_chapter":
                path = "import-plans/" + canonical_id(plan_id) + "/chapters"
            elif operation not in {
                "workspace", "list", "create", "create_once", "preview_import", "story_status"
            }:
                path = "articles/" + canonical_id(article_id) + path
            credential = self._credential_loader()
        except AgentConfigurationError:
            raise AgentServiceError("unauthorized", "credential_unavailable") from None
        arguments = {key: value for key, value in arguments.items() if value is not None}
        if method == "GET":
            request_arguments = {"params": arguments}
        else:
            try:
                body = json.dumps(
                    arguments, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                ).encode("utf-8")
            except (TypeError, ValueError, UnicodeError):
                raise AgentServiceError("invalid_request", "reader_invalid_request") from None
            if len(body) > MAX_REQUEST_BYTES:
                raise AgentServiceError("invalid_request", "reader_invalid_request")
            request_arguments = {"content": body}
        try:
            async with self._http.stream(
                method,
                API_PREFIX + path,
                headers={"Authorization": "Bearer " + credential, "Accept": "application/json",
                         "Content-Type": "application/json"},
                **request_arguments,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise AgentServiceError("service_unavailable", "redirect_refused")
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise AgentServiceError("service_unavailable", "response_too_large")
                    chunks.append(chunk)
                try:
                    payload = json.loads(b"".join(chunks))
                    if not isinstance(payload, dict):
                        raise ValueError()
                except ValueError:
                    raise AgentServiceError("service_unavailable", "invalid_response") from None
                if response.is_error:
                    error = _error(response.status_code, payload, response.headers)
                    if error.outcome == "service_unavailable" and operation not in SAFE_TO_RETRY:
                        error.retryable = False
                    raise error
                if operation == "workspace" and payload.get("grant_id") != self.connection.grant_id:
                    raise AgentServiceError("unauthorized", "grant_mismatch")
                return payload
        except httpx.TimeoutException:
            # A write may have committed. No automatic retry of non-idempotent
            # edits; chapter callers retain their retry key for a later attempt.
            raise AgentServiceError(
                "service_unavailable", "request_timeout", retryable=operation in SAFE_TO_RETRY
            ) from None
        except httpx.HTTPError:
            raise AgentServiceError(
                "service_unavailable", "connection_failed", retryable=operation in SAFE_TO_RETRY
            ) from None


def _error(status: int, payload: dict, headers: httpx.Headers | None = None) -> AgentServiceError:
    error = payload.get("error")
    code = error.get("type") if isinstance(error, dict) else None
    code = code if isinstance(code, str) else None
    # Allowlist error identifiers, never forward a response body/trace or a
    # possibly secret-bearing upstream error message as an MCP tool result.
    if status in {401, 403}:
        return AgentServiceError("unauthorized", "reader_agent_unauthorized")
    if status == 429 or code in {"reader_document_locked", "reader_database_busy"}:
        reason = "rate_limited" if status == 429 else code
        if reason == "reader_document_locked":
            # Playback duration is unknown; a generic retry header cannot predict it.
            return AgentServiceError("busy", "reader_busy", retryable=True, reason=reason)
        details = error.get("details") if isinstance(error, dict) else None
        details = details if isinstance(details, dict) else {}
        headers = headers if headers is not None else httpx.Headers()
        delays = [
            _bounded_delay(details.get("retry_after_seconds")),
            _retry_after(headers.get("Retry-After")),
        ]
        valid_delays = [value for value in delays if value is not None]
        budget_values = [details.get("request_budget"), headers.get("X-TTS-Request-Budget")]
        budgets = {
            value for value in budget_values if isinstance(value, str) and value in REQUEST_BUDGETS
        }
        return AgentServiceError(
            "busy",
            "reader_busy",
            retryable=True,
            reason=reason,
            retry_after_seconds=max(valid_delays) if valid_delays else None,
            request_budget=next(iter(budgets)) if len(budgets) == 1 else None,
        )
    if status == 409:
        code = (
            code
            if code in {"reader_revision_conflict", "reader_agent_conflict"}
            else "reader_conflict"
        )
        return AgentServiceError("conflict", code)
    if status in {400, 413, 422}:
        return AgentServiceError("invalid_request", "reader_invalid_request")
    return AgentServiceError("service_unavailable", "reader_service_unavailable", retryable=True)


def _bounded_delay(value: object) -> int | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= value <= MAX_RETRY_AFTER_SECONDS
        and math.isfinite(value)
    ):
        return math.ceil(value)
    return None


def _retry_after(value: str | None) -> int | None:
    if value is None or len(value) > 128:
        return None
    value = value.strip()
    if value.isascii() and value.isdecimal():
        return _bounded_delay(int(value))
    try:
        deadline = parsedate_to_datetime(value)
        if deadline.tzinfo is None:
            return None
        return _bounded_delay(max(0.0, (deadline - datetime.now(timezone.utc)).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None
