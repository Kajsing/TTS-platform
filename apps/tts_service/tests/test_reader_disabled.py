from __future__ import annotations

from pathlib import Path

from tts_service.bootstrap import build_application_state
from tts_service.config import AppConfig, AuthConfig, ReaderConfig, TTSConfig


def test_disabled_reader_does_not_touch_storage_or_block_tts_construction(
    tmp_path: Path,
) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("file", encoding="utf-8")
    database_path = blocked_parent / "reader.db"
    config = AppConfig(
        auth=AuthConfig(enabled=False),
        tts=TTSConfig(warmup_on_start=False),
        reader=ReaderConfig(enabled=False, database_path=str(database_path)),
    )

    state = build_application_state(config, repo_root=tmp_path)

    assert state.config.reader.enabled is False
    assert state.backend_ready is True
    assert state.default_voice_loaded is True
    assert not database_path.exists()
