"""Transport-independent contracts for the optional agent workspace."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from .errors import ReaderError, ReaderValidationError
from .models import ReaderDocument

AGENT_OPERATIONS = frozenset(
    {
        "workspace",
        "list",
        "read",
        "create",
        "rename",
        "append",
        "replace",
        "chapters",
        "deliver",
    }
)
MAX_AGENT_TEXT = 200_000
MAX_AGENT_PAGE = 20_000


class AgentUnauthorizedError(ReaderError):
    def __init__(self) -> None:
        super().__init__("Agent access is unavailable for this operation.")


class AgentConflictError(ReaderError):
    """A chapter/retry identity or explicit replacement is ambiguous."""


def credential_digest(credential: str) -> str:
    # Generated secrets carry 256 random bits; a slow password KDF adds no
    # guessing resistance here. The prefix keeps them distinct from owner auth.
    if not re.fullmatch(r"rdr_agent_[A-Za-z0-9_-]{43}", credential):
        raise AgentUnauthorizedError()
    return hashlib.sha256(credential.encode("ascii")).hexdigest()


def bounded_text(value: str, name: str, maximum: int, *, empty: bool = False) -> None:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ReaderValidationError(
            f"{name} must contain {'0' if empty else '1'} to {maximum} characters"
        )
    if "\x00" in value:
        raise ReaderValidationError(f"{name} must not contain NUL")


@dataclass(frozen=True)
class AgentGrant:
    id: str
    folder_id: str
    name: str
    operations: tuple[str, ...]
    created_at: str
    revoked_at: str | None


@dataclass(frozen=True)
class AgentArticlePage:
    document: ReaderDocument
    text: str
    offset: int
    next_offset: int | None
    text_length: int


@dataclass(frozen=True)
class ChapterDelivery:
    story_key: str
    chapter_key: str
    retry_key: str
    source_url: str
    title: str
    text: str
    order_label: str | None = None
    order_index: int | None = None

    def __post_init__(self) -> None:
        for name in ("story_key", "chapter_key", "retry_key"):
            bounded_text(getattr(self, name), name, 200)
        bounded_text(self.title, "title", 500)
        bounded_text(self.text, "text", MAX_AGENT_TEXT)
        bounded_text(self.source_url, "source_url", 2048)
        try:
            url = urlsplit(self.source_url)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
            ):
                raise ValueError()
        except ValueError:
            raise ReaderValidationError(
                "source_url must be an HTTP(S) URL without credentials"
            ) from None
        if self.order_label is not None:
            bounded_text(self.order_label, "order_label", 200)
        if self.order_index is not None and (
            type(self.order_index) is not int or abs(self.order_index) > 2**53 - 1
        ):
            raise ReaderValidationError("order_index must be a JSON-safe integer")

    def fingerprint(self) -> str:
        # Retry IDs are delivery attempts, not part of chapter identity. Exact
        # payload comparison intentionally refuses silently changed source text.
        payload = {key: value for key, value in vars(self).items() if key != "retry_key"}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class ChapterReceipt:
    id: str
    document_id: str
    story_key: str
    chapter_key: str
    source_url: str
    title: str
    order_label: str | None
    order_index: int | None
    order_warning: str | None
    imported_at: datetime
    result_row_version: int
    result_content_revision: int
    outcome: str = "imported"
