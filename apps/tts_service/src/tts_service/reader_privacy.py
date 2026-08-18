from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from reader_core import ReaderError, ReaderFolder, ReaderFolderPrivacy, ReaderValidationError
from reader_core.repositories import ReaderRepository

PRIVACY_SESSION_HEADER = "X-Reader-Privacy-Sessions"
PRIVACY_SESSION_SECONDS = 15 * 60
PRIVACY_HASH_ITERATIONS = 310_000
PRIVACY_MAX_SESSIONS_PER_REQUEST = 32
PRIVACY_MAX_SESSION_HEADER_CHARS = 4096


@dataclass(frozen=True, slots=True)
class ReaderPrivacyLockedError(ReaderError):
    folder_id: str


@dataclass(frozen=True, slots=True)
class ReaderPrivacyCredentialError(ReaderError):
    pass


@dataclass(frozen=True, slots=True)
class ReaderPrivacyRateLimitedError(ReaderError):
    retry_after_seconds: int


@dataclass(frozen=True, slots=True)
class ReaderPrivacySession:
    folder_id: str
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ReaderPrivacyLockResult:
    folder: ReaderFolder
    recovery_key: str
    session: ReaderPrivacySession


@dataclass(frozen=True, slots=True)
class _StoredSession:
    folder_id: str
    expires_at_monotonic: float
    expires_at: datetime


class ReaderPrivacyService:
    """Application-level folder privacy. It deliberately does not encrypt content."""

    def __init__(
        self,
        repository: ReaderRepository,
        *,
        session_seconds: int = PRIVACY_SESSION_SECONDS,
        hash_iterations: int = PRIVACY_HASH_ITERATIONS,
    ) -> None:
        if session_seconds < 60 or session_seconds > 24 * 60 * 60:
            raise ValueError("privacy session duration must be between 1 minute and 24 hours")
        if hash_iterations < 10_000:
            raise ValueError("privacy hash iteration count is too small")
        self._repository = repository
        self._session_seconds = session_seconds
        self._hash_iterations = hash_iterations
        self._sessions: dict[str, _StoredSession] = {}
        self._failed_attempts: dict[str, list[float]] = {}
        self._lock = threading.RLock()

    @property
    def session_seconds(self) -> int:
        return self._session_seconds

    def setup(
        self,
        folder_id: str,
        *,
        code: str,
        expected_row_version: int,
    ) -> ReaderPrivacyLockResult:
        folder = self._repository.get_folder(folder_id)
        if folder.privacy_locked:
            raise ReaderValidationError("folder already has a privacy lock")
        normalized_code = _normalize_code(code)
        recovery_key = _new_recovery_key()
        updated_at = datetime.now(timezone.utc)
        folder = self._repository.set_folder_privacy(
            ReaderFolderPrivacy(
                folder_id=folder_id,
                code_hash=_hash_secret(normalized_code, self._hash_iterations),
                recovery_hash=_hash_secret(
                    _normalize_recovery_key(recovery_key),
                    self._hash_iterations,
                ),
                updated_at=updated_at,
            ),
            expected_row_version=expected_row_version,
        )
        self._invalidate_folder_sessions(folder_id)
        return ReaderPrivacyLockResult(
            folder=folder,
            recovery_key=recovery_key,
            session=self._create_session(folder_id),
        )

    def unlock(self, folder_id: str, *, code: str) -> ReaderPrivacySession:
        privacy = self._require_privacy(folder_id)
        self._require_attempt_allowed(folder_id)
        if not _verify_secret(_normalize_code(code), privacy.code_hash):
            self._record_failed_attempt(folder_id)
            raise ReaderPrivacyCredentialError()
        self._clear_failed_attempts(folder_id)
        return self._create_session(folder_id)

    def change_code(
        self,
        folder_id: str,
        *,
        current_code: str,
        new_code: str,
        expected_row_version: int,
    ) -> ReaderPrivacyLockResult:
        privacy = self._require_privacy(folder_id)
        self._verify_current_code(folder_id, current_code, privacy)
        recovery_key = _new_recovery_key()
        updated_at = datetime.now(timezone.utc)
        folder = self._repository.set_folder_privacy(
            ReaderFolderPrivacy(
                folder_id=folder_id,
                code_hash=_hash_secret(_normalize_code(new_code), self._hash_iterations),
                recovery_hash=_hash_secret(
                    _normalize_recovery_key(recovery_key),
                    self._hash_iterations,
                ),
                updated_at=updated_at,
            ),
            expected_row_version=expected_row_version,
        )
        self._invalidate_folder_sessions(folder_id)
        return ReaderPrivacyLockResult(
            folder=folder,
            recovery_key=recovery_key,
            session=self._create_session(folder_id),
        )

    def recover(
        self,
        folder_id: str,
        *,
        recovery_key: str,
        new_code: str,
        expected_row_version: int,
    ) -> ReaderPrivacyLockResult:
        privacy = self._require_privacy(folder_id)
        self._require_attempt_allowed(folder_id)
        if not _verify_secret(
            _normalize_recovery_key(recovery_key),
            privacy.recovery_hash,
        ):
            self._record_failed_attempt(folder_id)
            raise ReaderPrivacyCredentialError()
        self._clear_failed_attempts(folder_id)
        new_recovery_key = _new_recovery_key()
        updated_at = datetime.now(timezone.utc)
        folder = self._repository.set_folder_privacy(
            ReaderFolderPrivacy(
                folder_id=folder_id,
                code_hash=_hash_secret(_normalize_code(new_code), self._hash_iterations),
                recovery_hash=_hash_secret(
                    _normalize_recovery_key(new_recovery_key),
                    self._hash_iterations,
                ),
                updated_at=updated_at,
            ),
            expected_row_version=expected_row_version,
        )
        self._invalidate_folder_sessions(folder_id)
        return ReaderPrivacyLockResult(
            folder=folder,
            recovery_key=new_recovery_key,
            session=self._create_session(folder_id),
        )

    def remove(
        self,
        folder_id: str,
        *,
        current_code: str,
        expected_row_version: int,
    ) -> ReaderFolder:
        privacy = self._require_privacy(folder_id)
        self._verify_current_code(folder_id, current_code, privacy)
        folder = self._repository.clear_folder_privacy(
            folder_id,
            expected_row_version=expected_row_version,
        )
        self._invalidate_folder_sessions(folder_id)
        return folder

    def relock(self, folder_id: str, tokens: tuple[str, ...]) -> None:
        self.require_folder_access(folder_id, tokens)
        self._invalidate_folder_sessions(folder_id)

    def unlocked_folder_ids(self, tokens: tuple[str, ...]) -> tuple[str, ...]:
        now = time.monotonic()
        with self._lock:
            self._purge_sessions_locked(now)
            return tuple(
                sorted(
                    {
                        session.folder_id
                        for token in tokens
                        if (session := self._sessions.get(token)) is not None
                    }
                )
            )

    def require_folder_access(self, folder_id: str | None, tokens: tuple[str, ...]) -> None:
        if folder_id is None:
            return
        folder = self._repository.get_folder(folder_id)
        if folder.privacy_locked and folder_id not in self.unlocked_folder_ids(tokens):
            raise ReaderPrivacyLockedError(folder_id)

    def require_document_access(self, document_id: str, tokens: tuple[str, ...]):
        document = self._repository.get_document(document_id)
        self.require_folder_access(document.folder_id, tokens)
        return document

    def can_access_folder(self, folder: ReaderFolder, tokens: tuple[str, ...]) -> bool:
        return not folder.privacy_locked or folder.id in self.unlocked_folder_ids(tokens)

    def can_access_document(self, document, tokens: tuple[str, ...]) -> bool:
        if document.folder_id is None:
            return True
        folder = self._repository.get_folder(document.folder_id)
        return self.can_access_folder(folder, tokens)

    def _require_privacy(self, folder_id: str) -> ReaderFolderPrivacy:
        privacy = self._repository.get_folder_privacy(folder_id)
        if privacy is None:
            raise ReaderValidationError("folder does not have a privacy lock")
        return privacy

    def _verify_current_code(
        self,
        folder_id: str,
        code: str,
        privacy: ReaderFolderPrivacy,
    ) -> None:
        self._require_attempt_allowed(folder_id)
        if not _verify_secret(_normalize_code(code), privacy.code_hash):
            self._record_failed_attempt(folder_id)
            raise ReaderPrivacyCredentialError()
        self._clear_failed_attempts(folder_id)

    def _create_session(self, folder_id: str) -> ReaderPrivacySession:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._session_seconds)
        stored = _StoredSession(
            folder_id=folder_id,
            expires_at_monotonic=time.monotonic() + self._session_seconds,
            expires_at=expires_at,
        )
        with self._lock:
            self._purge_sessions_locked(time.monotonic())
            self._sessions[token] = stored
        return ReaderPrivacySession(folder_id=folder_id, token=token, expires_at=expires_at)

    def _invalidate_folder_sessions(self, folder_id: str) -> None:
        with self._lock:
            for token in tuple(self._sessions):
                if self._sessions[token].folder_id == folder_id:
                    self._sessions.pop(token, None)

    def _purge_sessions_locked(self, now: float) -> None:
        for token in tuple(self._sessions):
            if self._sessions[token].expires_at_monotonic <= now:
                self._sessions.pop(token, None)

    def _require_attempt_allowed(self, folder_id: str) -> None:
        now = time.monotonic()
        with self._lock:
            failures = [
                value
                for value in self._failed_attempts.get(folder_id, [])
                if now - value < 300
            ]
            self._failed_attempts[folder_id] = failures
            if len(failures) >= 5:
                retry_after = max(1, int(300 - (now - failures[0])))
                raise ReaderPrivacyRateLimitedError(retry_after)

    def _record_failed_attempt(self, folder_id: str) -> None:
        with self._lock:
            self._failed_attempts.setdefault(folder_id, []).append(time.monotonic())

    def _clear_failed_attempts(self, folder_id: str) -> None:
        with self._lock:
            self._failed_attempts.pop(folder_id, None)


def parse_privacy_session_header(value: str | None) -> tuple[str, ...]:
    if value is None or not value.strip():
        return ()
    if len(value) > PRIVACY_MAX_SESSION_HEADER_CHARS:
        raise ReaderValidationError("privacy session header exceeds its limit")
    tokens = tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    if len(tokens) > PRIVACY_MAX_SESSIONS_PER_REQUEST or any(len(token) > 128 for token in tokens):
        raise ReaderValidationError("privacy session header is invalid")
    return tokens


def _normalize_code(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    if normalized != normalized.strip() or not 6 <= len(normalized) <= 128:
        raise ReaderValidationError(
            "privacy code must contain 6 through 128 characters without edge whitespace"
        )
    if len(normalized.encode("utf-8")) > 512:
        raise ReaderValidationError("privacy code exceeds its byte limit")
    return normalized


def _normalize_recovery_key(value: str) -> str:
    normalized = "".join(character for character in value.upper() if character not in " -\t\r\n")
    if not normalized.startswith("TTSR") or not 30 <= len(normalized) <= 80:
        raise ReaderValidationError("privacy recovery key is invalid")
    return normalized


def _new_recovery_key() -> str:
    body = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    return "TTSR-" + "-".join(body[index : index + 4] for index in range(0, len(body), 4))


def _hash_secret(value: str, iterations: int) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, iterations)
    return "$".join(
        (
            "pbkdf2_sha256",
            str(iterations),
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
        )
    )


def _verify_secret(value: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if not 10_000 <= iterations <= 2_000_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(digest_text + "=" * (-len(digest_text) % 4))
        actual = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
