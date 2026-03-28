from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from .bootstrap import build_application_state
from .config import AppConfig, load_config
from .errors import APIError
from .schemas import SynthesizeRequestPayload
from .synthesis import SynthesisService


def create_app(
    *,
    config: AppConfig | None = None,
    config_path: str | Path | None = None,
    repo_root: Path | None = None,
) -> FastAPI:
    resolved_config = config or load_config(config_path)
    app = FastAPI(title="Local TTS Service", version="0.1.0")
    app.state.container = build_application_state(
        resolved_config,
        repo_root=repo_root or _repo_root(),
    )
    _register_exception_handlers(app)
    _register_routes(app)
    return app


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def handle_api_error(_, exc: APIError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_response())


def _register_routes(app: FastAPI) -> None:
    @app.get("/v1/health")
    async def health() -> dict[str, object]:
        container = app.state.container
        uptime_seconds = int(
            (datetime.now(timezone.utc) - container.started_at).total_seconds()
        )
        default_voice = container.voice_registry.default_voice
        return {
            "status": "ok",
            "version": app.version,
            "uptime_s": uptime_seconds,
            "default_voice": default_voice.id if default_voice is not None else None,
        }

    @app.get("/v1/voices")
    async def voices() -> dict[str, object]:
        container = app.state.container
        return {
            "voices": [asdict(voice) for voice in container.voice_registry.list()],
            "default_voice": container.config.tts.default_voice,
        }

    @app.post("/v1/tts")
    async def synthesize(payload: SynthesizeRequestPayload) -> Response:
        container = app.state.container
        synthesis_service = SynthesisService(
            voice_registry=container.voice_registry,
            text_pipeline=container.text_pipeline,
            backend=container.backend,
            default_voice_id=container.config.tts.default_voice,
            max_chars_per_request=container.config.tts.max_chars_per_request,
        )
        result = synthesis_service.synthesize(payload)
        return Response(content=result.audio_bytes, media_type="audio/wav")


app = create_app()
