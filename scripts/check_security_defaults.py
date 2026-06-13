from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CONFIG_EXAMPLE_PATH = REPO_ROOT / "config" / "config.example.toml"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"

if str(SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(SERVICE_SRC))

from tts_service.config import (  # noqa: E402
    DEFAULT_BACKEND_DEBUG,
    DEFAULT_BACKEND_MODE,
    DEFAULT_BACKEND_PROVIDER,
    DEFAULT_MAX_CHARS_PER_REQUEST,
    DEFAULT_MAX_CHARS_PER_STREAM,
    DEFAULT_METRICS_ENABLED,
    DEFAULT_REQUESTS_PER_MINUTE,
    DEFAULT_SERVER_HOST,
    DEFAULT_TOKEN_FILE,
    load_config,
)

_MISSING = object()

REQUIRED_EXPLICIT_CONFIG_VALUES = (
    (("server", "host"), DEFAULT_SERVER_HOST),
    (("auth", "enabled"), True),
    (("auth", "token_file"), DEFAULT_TOKEN_FILE),
    (("security", "allowed_origins"), []),
    (("limits", "requests_per_minute"), DEFAULT_REQUESTS_PER_MINUTE),
    (("metrics", "enabled"), DEFAULT_METRICS_ENABLED),
    (("tts", "max_chars_per_request"), DEFAULT_MAX_CHARS_PER_REQUEST),
    (("tts", "max_chars_per_stream"), DEFAULT_MAX_CHARS_PER_STREAM),
    (("backend", "mode"), DEFAULT_BACKEND_MODE),
    (("backend", "provider"), DEFAULT_BACKEND_PROVIDER),
    (("backend", "debug"), DEFAULT_BACKEND_DEBUG),
)

REQUIRED_GITIGNORE_ENTRIES = (
    "config/config.toml",
    "config/token.txt",
    "models/voices/",
)

CHECKED_ITEMS = (
    "loopback_host",
    "token_auth_enabled",
    "repo_local_token_file",
    "empty_allowed_origins",
    "rate_limit_enabled",
    "metrics_enabled",
    "stream_limit_supports_long_pages",
    "local_cpu_backend_default",
    "local_secret_and_model_ignores",
)


class SecurityDefaultsError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_security_defaults")
    parser.add_argument("--config", default=str(CONFIG_EXAMPLE_PATH))
    parser.add_argument("--gitignore", default=str(GITIGNORE_PATH))
    args = parser.parse_args(argv)

    try:
        summary = check_security_defaults(
            config_path=Path(args.config),
            gitignore_path=Path(args.gitignore),
        )
    except SecurityDefaultsError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2, sort_keys=True))


def check_security_defaults(*, config_path: Path, gitignore_path: Path) -> dict[str, object]:
    errors: list[str] = []
    raw_config = _load_raw_config(config_path)
    _check_explicit_config_values(raw_config=raw_config, errors=errors)
    try:
        config = load_config(config_path, env={})
    except ValueError as exc:
        raise SecurityDefaultsError(
            f"{_relative(config_path)} does not load with secure defaults: {exc}"
        ) from exc

    _expect(
        errors,
        config.server.host == DEFAULT_SERVER_HOST,
        f"server.host must default to {DEFAULT_SERVER_HOST!r}",
    )
    _expect(errors, config.auth.enabled is True, "auth.enabled must default to true")
    _expect(
        errors,
        config.auth.token_file == DEFAULT_TOKEN_FILE,
        f"auth.token_file must default to {DEFAULT_TOKEN_FILE!r}",
    )
    _expect(
        errors,
        config.security.allowed_origins == (),
        "security.allowed_origins must default to an empty fail-closed allow-list",
    )
    _expect(
        errors,
        config.limits.requests_per_minute > 0,
        "limits.requests_per_minute must keep rate limiting enabled",
    )
    _expect(errors, config.metrics.enabled is True, "metrics.enabled must default to true")
    _expect(
        errors,
        config.tts.max_chars_per_request == DEFAULT_MAX_CHARS_PER_REQUEST,
        f"tts.max_chars_per_request must default to {DEFAULT_MAX_CHARS_PER_REQUEST}",
    )
    _expect(
        errors,
        config.tts.max_chars_per_stream == DEFAULT_MAX_CHARS_PER_STREAM,
        f"tts.max_chars_per_stream must default to {DEFAULT_MAX_CHARS_PER_STREAM}",
    )
    _expect(
        errors,
        config.tts.max_chars_per_stream >= config.tts.max_chars_per_request,
        "tts.max_chars_per_stream must be at least max_chars_per_request",
    )
    _expect(
        errors,
        config.backend.mode == DEFAULT_BACKEND_MODE,
        f"backend.mode must default to {DEFAULT_BACKEND_MODE!r}",
    )
    _expect(
        errors,
        config.backend.provider == DEFAULT_BACKEND_PROVIDER,
        f"backend.provider must default to {DEFAULT_BACKEND_PROVIDER!r}",
    )
    _expect(errors, config.backend.debug is False, "backend.debug must default to false")
    _check_gitignore(gitignore_path=gitignore_path, errors=errors)

    if errors:
        joined_errors = "\n".join(f"- {error}" for error in errors)
        raise SecurityDefaultsError(f"Security default check failed:\n{joined_errors}")

    return {
        "config_path": str(config_path.expanduser().resolve()),
        "gitignore_path": str(gitignore_path.expanduser().resolve()),
        "checked_items": list(CHECKED_ITEMS),
    }


def _load_raw_config(config_path: Path) -> dict[str, object]:
    if not config_path.is_file():
        raise SecurityDefaultsError(f"{_relative(config_path)} must exist")
    try:
        with config_path.open("rb") as config_file:
            return tomllib.load(config_file)
    except tomllib.TOMLDecodeError as exc:
        raise SecurityDefaultsError(f"{_relative(config_path)} is not valid TOML: {exc}") from exc


def _check_explicit_config_values(
    *,
    raw_config: dict[str, object],
    errors: list[str],
) -> None:
    for path, expected_value in REQUIRED_EXPLICIT_CONFIG_VALUES:
        actual_value = _lookup_raw_config_value(raw_config=raw_config, path=path)
        label = ".".join(path)
        if actual_value is _MISSING:
            errors.append(f"config.example.toml must explicitly set {label}")
            continue
        _expect(
            errors,
            actual_value == expected_value,
            f"{label} must be explicitly set to {expected_value!r}",
        )


def _lookup_raw_config_value(
    *,
    raw_config: dict[str, object],
    path: tuple[str, ...],
) -> object:
    cursor: object = raw_config
    for segment in path:
        if not isinstance(cursor, dict) or segment not in cursor:
            return _MISSING
        cursor = cursor[segment]
    return cursor


def _check_gitignore(*, gitignore_path: Path, errors: list[str]) -> None:
    if not gitignore_path.is_file():
        errors.append(f"{_relative(gitignore_path)} must exist")
        return

    entries = _read_gitignore_entries(gitignore_path)
    for required_entry in REQUIRED_GITIGNORE_ENTRIES:
        _expect(
            errors,
            required_entry in entries,
            f".gitignore must include {required_entry!r}",
        )


def _read_gitignore_entries(path: Path) -> set[str]:
    entries: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip().replace("\\", "/")
        if not entry or entry.startswith("#"):
            continue
        entries.add(entry)
    return entries


def _expect(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _relative(path: Path) -> str:
    try:
        return path.expanduser().resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
