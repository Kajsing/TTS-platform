from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from .config import AuthConfig


@dataclass(frozen=True, slots=True)
class AuthState:
    enabled: bool
    token_file: Path
    token: str | None
    generated: bool = False


def initialize_auth(auth_config: AuthConfig, *, repo_root: Path) -> AuthState:
    token_file = Path(auth_config.token_file)
    if not token_file.is_absolute():
        token_file = repo_root / token_file

    if not auth_config.enabled:
        return AuthState(enabled=False, token_file=token_file, token=None, generated=False)

    token_file.parent.mkdir(parents=True, exist_ok=True)
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("Auth token file is empty.")
        return AuthState(enabled=True, token_file=token_file, token=token, generated=False)

    token = secrets.token_urlsafe(32)
    file_descriptor = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as token_file_handle:
        token_file_handle.write(token)
        token_file_handle.write("\n")
    return AuthState(enabled=True, token_file=token_file, token=token, generated=True)
