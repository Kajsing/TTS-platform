from __future__ import annotations

import os
import subprocess
import sys

import pytest
import tts_service.main as main_module


def test_importing_main_does_not_create_default_app() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import tts_service.main as module; assert module._default_app is None",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_default_asgi_app_is_created_lazily_and_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    create_calls = 0

    def fake_create_app() -> object:
        nonlocal create_calls
        create_calls += 1
        return sentinel

    monkeypatch.setattr(main_module, "_default_app", None)
    monkeypatch.setattr(main_module, "create_app", fake_create_app)

    assert main_module.__getattr__("app") is sentinel
    assert main_module.__getattr__("app") is sentinel
    assert create_calls == 1

    with pytest.raises(AttributeError, match="has no attribute 'missing'"):
        main_module.__getattr__("missing")
