from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


class AgentConfigurationError(ValueError):
    pass


def local_service_url(value: str) -> str:
    try:
        url = urlsplit(value)
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or url.username is not None
            or url.password is not None
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or any(character.isspace() for character in value)
        ):
            raise ValueError()
        port = url.port or 80
    except (ValueError, TypeError, AttributeError):
        raise AgentConfigurationError(
            "Use a plain HTTP loopback service URL with no path or credentials."
        ) from None
    # Never resolve localhost through configurable DNS/hosts entries.
    host = "[::1]" if url.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{port}/"


def canonical_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise AgentConfigurationError("The Reader identifier must be a UUID.") from None


@dataclass(frozen=True)
class AgentConnection:
    service_base_url: str
    grant_id: str
    directory: Path

    @classmethod
    def load(cls, path: Path) -> AgentConnection:
        try:
            with path.open("rb") as stream:
                data = stream.read(16_385)
            if len(data) > 16_384:
                raise ValueError()
            payload = json.loads(data.decode("utf-8-sig"))
            if (
                set(payload) != {"version", "service_base_url", "grant_id"}
                or type(payload["version"]) is not int
                or payload["version"] != 1
            ):
                raise ValueError()
            return cls(
                local_service_url(payload["service_base_url"]),
                canonical_id(payload["grant_id"]),
                path.resolve().parent,
            )
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            raise AgentConfigurationError(
                "Cannot read the connection file. Recreate it in Options > Agent access."
            ) from None

    def credential(self) -> str:
        if os.name != "nt":
            raise AgentConfigurationError(
                "This local adapter requires Windows protected credentials."
            )
        try:
            import win32crypt

            with (self.directory / f"{self.grant_id}.bin").open("rb") as stream:
                ciphertext = stream.read(16_385)
            if not ciphertext or len(ciphertext) > 16_384:
                raise ValueError()
            # Same CurrentUser DPAPI blob as Reader's DpapiCredentialStore;
            # UI is forbidden and no optional entropy or plaintext fallback exists.
            plaintext = win32crypt.CryptUnprotectData(ciphertext, None, None, None, 1)[1]
            credential = plaintext.decode("utf-8").strip()
            if not re.fullmatch(r"rdr_agent_[A-Za-z0-9_-]{43}", credential):
                raise ValueError()
            return credential
        except Exception:
            # DPAPI can include local paths/system information in exceptions.
            # Never forward ciphertext or an invalid decoded secret to the host.
            raise AgentConfigurationError(
                "Cannot unlock the agent credential. Use the Windows account that created it, "
                "or provision access again."
            ) from None
