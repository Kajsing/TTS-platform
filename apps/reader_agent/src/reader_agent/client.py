"""Only HTTP agent routes: no Reader DB, owner token, synthesis or website access."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from .config import AgentConfigurationError, AgentConnection, canonical_id, local_service_url

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
API_PREFIX = "v1/reader/agent/"
SAFE_TO_RETRY = frozenset({"workspace", "list", "read", "chapters", "deliver"})


class AgentServiceError(Exception):
    def __init__(self, outcome: str, code: str, *, retryable: bool = False) -> None:
        self.outcome = outcome
        self.code = code
        self.retryable = retryable
        super().__init__(code)

    def payload(self) -> dict[str, object]:
        return {"outcome": self.outcome, "code": self.code, "retryable": self.retryable}


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
        **arguments,
    ) -> dict[str, object]:
        routes = {
            "workspace": ("GET", "workspace"),
            "list": ("GET", "articles"),
            "create": ("POST", "articles"),
            "read": ("GET", ""),
            "rename": ("PATCH", ""),
            "append": ("POST", "/append"),
            "replace": ("PATCH", "/text"),
            "chapters": ("GET", "/chapters"),
            "deliver": ("POST", "/chapters"),
        }
        if operation not in routes:
            raise AgentServiceError("unauthorized", "unsupported_operation")
        method, path = routes[operation]
        try:
            if operation not in {"workspace", "list", "create"}:
                path = "articles/" + canonical_id(article_id) + path
            credential = self._credential_loader()
        except AgentConfigurationError:
            raise AgentServiceError("unauthorized", "credential_unavailable") from None
        arguments = {key: value for key, value in arguments.items() if value is not None}
        request_arguments = {"params" if method == "GET" else "json": arguments}
        try:
            async with self._http.stream(
                method,
                API_PREFIX + path,
                headers={"Authorization": "Bearer " + credential, "Accept": "application/json"},
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
                    error = _error(response.status_code, payload)
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


def _error(status: int, payload: dict) -> AgentServiceError:
    error = payload.get("error")
    code = error.get("type") if isinstance(error, dict) else None
    # Allowlist error identifiers, never forward a response body/trace or a
    # possibly secret-bearing upstream error message as an MCP tool result.
    if status in {401, 403}:
        return AgentServiceError("unauthorized", "reader_agent_unauthorized")
    if code in {"reader_document_locked", "reader_database_busy"} or status == 429:
        return AgentServiceError("busy", "reader_busy", retryable=True)
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
