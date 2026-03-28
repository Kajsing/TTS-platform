from __future__ import annotations

from pathlib import Path

import pytest
from tts_service.auth import initialize_auth, rotate_auth_token
from tts_service.config import AuthConfig


def test_initialize_auth_rejects_empty_token_file(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    token_file.write_text("", encoding="utf-8")

    with pytest.raises(ValueError):
        initialize_auth(AuthConfig(enabled=True, token_file=str(token_file)), repo_root=tmp_path)


def test_rotate_auth_token_rewrites_token_file(tmp_path: Path) -> None:
    auth_state = initialize_auth(
        AuthConfig(enabled=True, token_file=str(tmp_path / "token.txt")),
        repo_root=tmp_path,
    )

    rotated_state = rotate_auth_token(auth_state)

    assert rotated_state.token is not None
    assert rotated_state.token != auth_state.token
    assert rotated_state.token_file.read_text(encoding="utf-8").strip() == rotated_state.token
