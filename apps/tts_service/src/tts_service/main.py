from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from .bootstrap import build_application_state
from .config import AppConfig, load_config


def create_app(
    *,
    config: AppConfig | None = None,
    config_path: str | Path | None = None,
) -> FastAPI:
    resolved_config = config or load_config(config_path)
    app = FastAPI(title="Local TTS Service", version="0.1.0")
    app.state.container = build_application_state(resolved_config, repo_root=_repo_root())
    return app


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


app = create_app()
