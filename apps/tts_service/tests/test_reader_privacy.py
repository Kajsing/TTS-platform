from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from reader_core import ReaderFolder, SqliteReaderRepository
from tts_service import reader_privacy
from tts_service.reader_privacy import (
    ReaderPrivacyCredentialError,
    ReaderPrivacyLockedError,
    ReaderPrivacyRateLimitedError,
    ReaderPrivacyService,
)


def test_privacy_session_expires_and_only_hashes_are_persisted(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SqliteReaderRepository(tmp_path / "reader.db")
    now = datetime.now(timezone.utc)
    folder = repository.create_folder(
        ReaderFolder(
            id=str(uuid.uuid4()),
            name="Personal",
            normalized_name="personal",
            created_at=now,
            updated_at=now,
        )
    )
    monotonic = [100.0]
    monkeypatch.setattr(reader_privacy.time, "monotonic", lambda: monotonic[0])
    privacy = ReaderPrivacyService(
        repository,
        session_seconds=60,
        hash_iterations=10_000,
    )

    result = privacy.setup(
        folder.id,
        code="correct horse",
        expected_row_version=folder.row_version,
    )
    stored = repository.get_folder_privacy(folder.id)

    assert stored is not None
    assert "correct horse" not in stored.code_hash
    assert result.recovery_key not in stored.recovery_hash
    assert stored.code_hash.startswith("pbkdf2_sha256$10000$")
    privacy.require_folder_access(folder.id, (result.session.token,))

    monotonic[0] += 61
    with pytest.raises(ReaderPrivacyLockedError):
        privacy.require_folder_access(folder.id, (result.session.token,))

    unlocked = privacy.unlock(folder.id, code="correct horse")
    privacy.require_folder_access(folder.id, (unlocked.token,))
    restarted = ReaderPrivacyService(repository, hash_iterations=10_000)
    with pytest.raises(ReaderPrivacyLockedError):
        restarted.require_folder_access(folder.id, (unlocked.token,))


def test_privacy_credentials_are_throttled_after_five_failures(tmp_path) -> None:
    repository = SqliteReaderRepository(tmp_path / "reader.db")
    now = datetime.now(timezone.utc)
    folder = repository.create_folder(
        ReaderFolder(
            id=str(uuid.uuid4()),
            name="Personal",
            normalized_name="personal",
            created_at=now,
            updated_at=now,
        )
    )
    privacy = ReaderPrivacyService(repository, hash_iterations=10_000)
    privacy.setup(
        folder.id,
        code="correct horse",
        expected_row_version=folder.row_version,
    )

    for _ in range(5):
        with pytest.raises(ReaderPrivacyCredentialError):
            privacy.unlock(folder.id, code="wrong secret")

    with pytest.raises(ReaderPrivacyRateLimitedError) as error:
        privacy.unlock(folder.id, code="correct horse")
    assert 1 <= error.value.retry_after_seconds <= 300
