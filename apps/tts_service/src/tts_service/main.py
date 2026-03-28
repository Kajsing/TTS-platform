from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from .bootstrap import build_application_state
from .config import AppConfig, load_config
from .errors import APIError, invalid_request
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

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(_, exc: RequestValidationError) -> JSONResponse:
        issues = []
        first_param: str | None = None
        for issue in exc.errors():
            location = issue.get("loc", ())
            path = ".".join(str(part) for part in location if part != "body")
            if first_param is None and path:
                first_param = path
            issues.append(
                {
                    "param": path or None,
                    "message": issue.get("msg", "Invalid request body."),
                    "type": issue.get("type"),
                }
            )
        api_error = invalid_request(
            "Request body validation failed.",
            param=first_param,
            details={"issues": issues},
        )
        return JSONResponse(status_code=api_error.status_code, content=api_error.to_response())


def _register_routes(app: FastAPI) -> None:
    @app.get("/v1/health")
    async def health() -> dict[str, object]:
        container = app.state.container
        uptime_seconds = int(
            (datetime.now(timezone.utc) - container.started_at).total_seconds()
        )
        default_voice = container.voice_registry.default_voice
        checks = {
            "process_running": True,
            "backend_ready": container.backend_ready,
            "default_voice_loaded": container.default_voice_loaded,
        }
        return {
            "status": "ok" if all(checks.values()) else "degraded",
            "version": app.version,
            "uptime_s": uptime_seconds,
            "default_voice": default_voice.id if default_voice is not None else None,
            "checks": checks,
            "startup_error": container.startup_error,
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
