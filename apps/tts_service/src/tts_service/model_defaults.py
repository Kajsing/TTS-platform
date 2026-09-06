"""Stage a service default without touching the running engine or Reader settings."""

from __future__ import annotations

import copy
import json
import os
import re
import stat
import uuid
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 support, matching the service config loader.
    import tomli as tomllib

from .model_installation import manifest_lock

MAX_CONFIG_BYTES = 2 * 1024 * 1024


def config_bytes(path: Path) -> bytes | None:
    try:
        with path.open("rb") as source:
            data = source.read(MAX_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(data) > MAX_CONFIG_BYTES:
        raise ValueError("The local configuration exceeds the supported size limit.")
    return data


def default_config_bytes(original: bytes, voice_id: str) -> bytes:
    """Edit one scalar; reparse and compare everything else before any write.

    Unusual inline/dotted/multiline layouts are refused rather than normalized.
    The comparison also protects against apparent table headers inside strings.
    """
    text = original.decode("utf-8")
    parsed = tomllib.loads(text)
    expected = copy.deepcopy(parsed)
    expected.setdefault("tts", {})["default_voice"] = voice_id
    lines = text.splitlines(keepends=True)
    table = re.compile(r"^\s*\[\s*tts\s*\]\s*(?:#.*)?$")
    starts = [index for index, line in enumerate(lines) if table.fullmatch(line.rstrip("\r\n"))]
    if len(starts) != 1:
        raise ValueError("Use a conventional [tts] table before changing the service default.")
    start = starts[0] + 1
    end = next(
        (i for i in range(start, len(lines)) if lines[i].lstrip().startswith("[")), len(lines)
    )
    scalar = re.compile(
        r"""^(\s*default_voice\s*=\s*)("(?:[^"\\\r\n]|\\.)*"|'[^'\r\n]*')(\s*(?:\#.*)?)$"""
    )
    matches = [(i, scalar.fullmatch(lines[i].rstrip("\r\n"))) for i in range(start, end)]
    matches = [(i, match) for i, match in matches if match]
    newline = "\r\n" if "\r\n" in text else "\n"
    value = json.dumps(voice_id, ensure_ascii=False)
    if len(matches) == 1:
        index, match = matches[0]
        ending = lines[index][len(lines[index].rstrip("\r\n")) :]
        lines[index] = match[1] + value + match[3] + ending
    elif not matches and "default_voice" not in parsed.get("tts", {}):
        if not lines[start - 1].endswith(("\r", "\n")):
            lines[start - 1] += newline
        lines.insert(start, f"default_voice = {value}{newline}")
    else:
        raise ValueError("The service default uses an unsupported TOML layout. Nothing changed.")
    result = "".join(lines)
    if tomllib.loads(result) != expected:
        raise ValueError("The default edit would affect other settings. Nothing changed.")
    return result.encode("utf-8")


def _copy_private(source: Path, destination: Path) -> None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        # Reject EFS rather than stage an encrypted config as plaintext. Normal
        # token-file configurations are unaffected; no permissions are weakened.
        if source.stat().st_file_attributes & 0x4000:
            raise ValueError("Encrypted config files require manual default selection.")
        security = ctypes.WinDLL("advapi32", use_last_error=True)
        get_security = security.GetFileSecurityW
        get_security.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_security.restype = wintypes.BOOL
        needed = wintypes.DWORD()
        get_security(str(source), 4, None, 0, ctypes.byref(needed))
        if not 0 < needed.value <= 1024 * 1024:
            raise OSError("Could not read the config access permissions.")
        descriptor = ctypes.create_string_buffer(needed.value)
        if not get_security(str(source), 4, descriptor, needed, ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        control, revision = wintypes.WORD(), wintypes.DWORD()
        get_control = security.GetSecurityDescriptorControl
        get_control.argtypes = [
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.WORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_control.restype = wintypes.BOOL
        if not get_control(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise ctypes.WinError(ctypes.get_last_error())
        # The new file is empty until the exact original DACL has been applied.
        with destination.open("xb"):
            pass
        set_security = security.SetFileSecurityW
        set_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPVOID]
        set_security.restype = wintypes.BOOL
        flags = 4 | (0x80000000 if control.value & 0x1000 else 0x20000000)
        if not set_security(str(destination), flags, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), stat.S_IMODE(source.stat().st_mode))


def _replace_private(path: Path, staging: Path, backup: Path) -> None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        replace = kernel.ReplaceFileW
        replace.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPVOID,
        ]
        replace.restype = wintypes.BOOL
        # No IGNORE_ACL/MERGE flags. A backup also protects documented partial
        # ReplaceFile failures (1176/1177); never force a replacement on failure.
        if not replace(str(path), str(staging), str(backup), 0, None, None):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(staging, path)


def save_default(path: Path, expected: bytes, voice_id: str) -> None:
    """Preserve credentials, comments, DACLs and all unrelated settings."""
    with manifest_lock(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError("The config must be a regular, unlinked local file.")
        if config_bytes(path) != expected:
            raise ValueError("The local configuration changed. Refresh before trying again.")
        replacement = default_config_bytes(expected, voice_id)
        if replacement == expected:
            return
        unique = uuid.uuid4().hex
        staging = path.with_name(f".{path.name}.{unique}.tmp")
        backup = path.with_name(f".{path.name}.{unique}.recovery")
        try:
            _copy_private(path, staging)
            with staging.open("r+b") as output:
                output.write(replacement)
                output.truncate()
                output.flush()
                os.fsync(output.fileno())
            if config_bytes(path) != expected:
                raise ValueError("The local configuration changed before commit. Refresh it.")
            _replace_private(path, staging, backup)
            # A successful replacement is authoritative even if backup cleanup
            # fails. Preserve a private recovery file instead of reporting a retry.
            try:
                backup.unlink(missing_ok=True)
            except OSError:
                pass
        except Exception:
            if not path.exists() and backup.exists():
                # Windows rename refuses an existing destination. POSIX link is
                # likewise no-overwrite, so a concurrent edit is never discarded.
                if os.name == "nt":
                    backup.rename(path)
                else:
                    os.link(backup, path)
                    backup.unlink()
            raise
        finally:
            staging.unlink(missing_ok=True)
