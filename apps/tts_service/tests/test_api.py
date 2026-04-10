from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from tts_service.config import AppConfig
from tts_service.main import _build_synthesis_service, create_app
from tts_service.schemas import SynthesizeRequestPayload


def build_fake_sherpa_onnx_module(sample_rate: int = 16000) -> object:
    class OfflineTtsVitsModelConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class OfflineTtsMatchaModelConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class OfflineTtsKokoroModelConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class OfflineTtsKittenModelConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class OfflineTtsModelConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class OfflineTtsConfig:
        def __init__(self, *, model, rule_fsts: str, max_num_sentences: int) -> None:
            self.model = model
            self.rule_fsts = rule_fsts
            self.max_num_sentences = max_num_sentences

        def validate(self) -> bool:
            return True

    class GenerationConfig:
        def __init__(self) -> None:
            self.sid = 0
            self.speed = 1.0
            self.silence_scale = 0.0

    class OfflineTts:
        def __init__(self, config) -> None:
            self.config = config

        def generate(self, text: str, generation_config) -> object:
            frame_count = max(48, len(text) * 8)
            samples = [0.3 if index % 2 == 0 else -0.3 for index in range(frame_count)]
            return SimpleNamespace(
                samples=samples,
                sample_rate=sample_rate,
                sid=generation_config.sid,
            )

    return SimpleNamespace(
        OfflineTts=OfflineTts,
        OfflineTtsConfig=OfflineTtsConfig,
        OfflineTtsKittenModelConfig=OfflineTtsKittenModelConfig,
        OfflineTtsKokoroModelConfig=OfflineTtsKokoroModelConfig,
        OfflineTtsMatchaModelConfig=OfflineTtsMatchaModelConfig,
        OfflineTtsModelConfig=OfflineTtsModelConfig,
        OfflineTtsVitsModelConfig=OfflineTtsVitsModelConfig,
        GenerationConfig=GenerationConfig,
    )


def build_test_bundle(
    tmp_path: Path,
    *,
    config_data: dict | None = None,
) -> tuple[TestClient, dict[str, str], object]:
    _write_manifest(tmp_path)
    base_config = {
        "tts": {"default_voice": "manifest-voice"},
    }
    if config_data:
        base_config.update(config_data)
    app = create_app(config=AppConfig.from_mapping(base_config), repo_root=tmp_path)
    auth_headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    return TestClient(app), auth_headers, app


def _write_manifest(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "voices").mkdir()
    (models_dir / "MANIFEST.json").write_text(
        """
        {
          "version": 1,
          "voices": [
            {
              "id": "manifest-voice",
              "name": "Manifest Voice",
              "engine": "sherpa_onnx",
              "language": "en",
              "sample_rate_hz": 22050,
              "license": "Apache-2.0",
              "source": "models/voices/manifest-voice",
              "tags": ["manifest"],
              "capabilities": {
                "supports_pitch": false,
                "supports_streaming": false,
                "supports_multi_speaker": false
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )


def test_health_endpoint_returns_service_status(tmp_path: Path) -> None:
    client, _, _ = build_test_bundle(tmp_path)

    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["default_voice"] == "manifest-voice"
    assert response.json()["checks"]["backend_ready"] is True
    assert response.json()["checks"]["default_voice_loaded"] is True
    assert response.json()["startup_error"] is None
    assert response.json()["auth_enabled"] is True
    assert response.json()["backend"]["runtime_mode"] == "auto"
    assert response.json()["backend"]["configured_real_voices"] == 0


def test_voices_endpoint_returns_registry(tmp_path: Path) -> None:
    client, _, _ = build_test_bundle(tmp_path)

    response = client.get("/v1/voices")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_voice"] == "manifest-voice"
    assert payload["voices"][0]["id"] == "manifest-voice"


def test_tts_endpoint_requires_bearer_token(tmp_path: Path) -> None:
    client, _, _ = build_test_bundle(tmp_path)

    response = client.post(
        "/v1/tts",
        json={
            "text": "Hello world",
            "voice": "manifest-voice",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "unauthorized"


def test_tts_endpoint_rejects_invalid_bearer_format(tmp_path: Path) -> None:
    client, _, _ = build_test_bundle(tmp_path)

    response = client.post(
        "/v1/tts",
        headers={"Authorization": "Token not-a-bearer-token"},
        json={
            "text": "Hello world",
            "voice": "manifest-voice",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "unauthorized"


def test_tts_endpoint_returns_wav_audio(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    response = client.post(
        "/v1/tts",
        headers=auth_headers,
        json={
            "text": "Dr. Smith says hello.",
            "voice": "manifest-voice",
            "format": "wav",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"


def test_prepare_request_uses_clause_aware_chunk_planning(tmp_path: Path) -> None:
    _, _, app = build_test_bundle(tmp_path)
    synthesis_service = _build_synthesis_service(app.state.container)
    long_sentence = (
        "Alpha clause introduces the topic with concrete examples, "
        "beta clause adds more context about timing and workflow, "
        "gamma clause expands on reliability, observability, and safety, "
        "delta clause closes the idea with a practical takeaway."
    )

    execution = synthesis_service.prepare_request(
        SynthesizeRequestPayload(
            text=long_sentence,
            voice="manifest-voice",
            prosody={"sentence_pause_ms": 150, "comma_pause_ms": 50},
        )
    )

    assert execution.segments == (long_sentence,)
    assert [chunk.text for chunk in execution.chunk_plan.chunks] == [
        (
            "Alpha clause introduces the topic with concrete examples, "
            "beta clause adds more context about timing and workflow, "
            "gamma clause expands on reliability, observability, and safety,"
        ),
        "delta clause closes the idea with a practical takeaway.",
    ]
    assert [chunk.pause_ms_hint for chunk in execution.chunk_plan.chunks] == [50, 150]


def test_tts_endpoint_can_use_real_backend_runtime_when_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    voice_dir = models_dir / "voices" / "manifest-voice"
    voice_dir.mkdir(parents=True)
    (voice_dir / "model.onnx").write_text("fake-model", encoding="utf-8")
    (voice_dir / "tokens.txt").write_text("fake-tokens", encoding="utf-8")
    (models_dir / "MANIFEST.json").write_text(
        """
        {
          "version": 1,
          "voices": [
            {
              "id": "manifest-voice",
              "name": "Manifest Voice",
              "engine": "sherpa_onnx",
              "language": "en",
              "sample_rate_hz": 22050,
              "license": "Apache-2.0",
              "source": "models/voices/manifest-voice",
              "backend": {
                "model_type": "vits",
                "model": "models/voices/manifest-voice/model.onnx",
                "tokens": "models/voices/manifest-voice/tokens.txt"
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setitem(sys.modules, "sherpa_onnx", build_fake_sherpa_onnx_module())
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"default_voice": "manifest-voice"},
                "backend": {"mode": "real"},
            }
        ),
        repo_root=tmp_path,
    )
    auth_headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    client = TestClient(app)

    health_response = client.get("/v1/health")

    assert health_response.status_code == 200
    assert health_response.json()["checks"]["backend_ready"] is True
    assert health_response.json()["backend"]["runtime_mode"] == "real"
    assert health_response.json()["backend"]["configured_real_voices"] == 1
    assert health_response.json()["backend"]["loaded_real_voices"] == ["manifest-voice"]

    response = client.post(
        "/v1/tts",
        headers=auth_headers,
        json={
            "text": "Hello real runtime",
            "voice": "manifest-voice",
            "format": "wav",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"


def test_tts_endpoint_returns_structured_error_for_unknown_voice(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    response = client.post(
        "/v1/tts",
        headers=auth_headers,
        json={
            "text": "Hello world",
            "voice": "missing-voice",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["type"] == "invalid_request"
    assert payload["error"]["param"] == "voice"


def test_tts_endpoint_rejects_empty_text(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    response = client.post(
        "/v1/tts",
        headers=auth_headers,
        json={
            "text": "   ",
            "voice": "manifest-voice",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["type"] == "invalid_request"
    assert payload["error"]["param"] == "text"


def test_tts_endpoint_rejects_oversized_text(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(
        tmp_path,
        config_data={
            "tts": {
                "default_voice": "manifest-voice",
                "max_chars_per_request": 10,
            }
        },
    )

    response = client.post(
        "/v1/tts",
        headers=auth_headers,
        json={
            "text": "This text is definitely too long.",
            "voice": "manifest-voice",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["param"] == "text"
    assert payload["error"]["details"]["max_chars_per_request"] == 10


def test_tts_endpoint_rejects_invalid_format(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    response = client.post(
        "/v1/tts",
        headers=auth_headers,
        json={
            "text": "Hello world",
            "voice": "manifest-voice",
            "format": "mp3",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["param"] == "format"
    assert payload["error"]["details"]["supported_formats"] == ["wav"]


def test_tts_endpoint_uses_structured_error_for_invalid_payload(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    response = client.post(
        "/v1/tts",
        headers=auth_headers,
        json={
            "voice": "manifest-voice",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["type"] == "invalid_request"
    assert payload["error"]["param"] == "text"
    assert payload["error"]["details"]["issues"]


def test_origin_policy_blocks_unapproved_origins(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(
        tmp_path,
        config_data={
            "security": {
                "allowed_origins": ["chrome-extension://approved-extension"],
            }
        },
    )

    response = client.post(
        "/v1/tts",
        headers={
            **auth_headers,
            "Origin": "chrome-extension://other-extension",
        },
        json={
            "text": "Hello world",
            "voice": "manifest-voice",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["type"] == "forbidden_origin"


def test_rate_limiter_rejects_repeated_write_requests(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(
        tmp_path,
        config_data={
            "limits": {
                "requests_per_minute": 1,
            }
        },
    )

    first = client.post(
        "/v1/tts",
        headers=auth_headers,
        json={"text": "Hello world", "voice": "manifest-voice"},
    )
    second = client.post(
        "/v1/tts",
        headers=auth_headers,
        json={"text": "Hello world again", "voice": "manifest-voice"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["type"] == "rate_limited"


def test_rate_limiter_applies_to_job_endpoints(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(
        tmp_path,
        config_data={
            "limits": {
                "requests_per_minute": 1,
            }
        },
    )

    first = client.post(
        "/v1/tts/jobs",
        headers=auth_headers,
        json={"text": "Hello world", "voice": "manifest-voice"},
    )
    second = client.post(
        "/v1/tts/jobs",
        headers=auth_headers,
        json={"text": "Hello again", "voice": "manifest-voice"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["type"] == "rate_limited"


def test_tts_jobs_flow_returns_completed_status(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    create_response = client.post(
        "/v1/tts/jobs",
        headers=auth_headers,
        json={"text": "Hello world", "voice": "manifest-voice"},
    )

    assert create_response.status_code == 200
    assert create_response.json()["status"] == "queued"
    job_id = create_response.json()["job_id"]

    status_payload = {}
    for _ in range(25):
        status_response = client.get(f"/v1/tts/jobs/{job_id}", headers=auth_headers)
        assert status_response.status_code == 200
        status_payload = status_response.json()
        if status_payload["status"] == "completed":
            break
        time.sleep(0.02)

    assert status_payload["job_id"] == job_id
    assert status_payload["status"] == "completed"
    assert status_payload["result_available"] is True
    assert status_payload["result_format"] == "wav"


def test_tts_jobs_flow_can_use_real_backend_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    voice_dir = models_dir / "voices" / "manifest-voice"
    voice_dir.mkdir(parents=True)
    (voice_dir / "model.onnx").write_text("fake-model", encoding="utf-8")
    (voice_dir / "tokens.txt").write_text("fake-tokens", encoding="utf-8")
    (models_dir / "MANIFEST.json").write_text(
        """
        {
          "version": 1,
          "voices": [
            {
              "id": "manifest-voice",
              "name": "Manifest Voice",
              "engine": "sherpa_onnx",
              "language": "en",
              "sample_rate_hz": 22050,
              "license": "Apache-2.0",
              "source": "models/voices/manifest-voice",
              "backend": {
                "model_type": "vits",
                "model": "models/voices/manifest-voice/model.onnx",
                "tokens": "models/voices/manifest-voice/tokens.txt"
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setitem(sys.modules, "sherpa_onnx", build_fake_sherpa_onnx_module())
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"default_voice": "manifest-voice"},
                "backend": {"mode": "real"},
            }
        ),
        repo_root=tmp_path,
    )
    auth_headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    client = TestClient(app)

    create_response = client.post(
        "/v1/tts/jobs",
        headers=auth_headers,
        json={"text": "Hello real backend job", "voice": "manifest-voice"},
    )

    assert create_response.status_code == 200
    job_id = create_response.json()["job_id"]

    status_payload = {}
    for _ in range(25):
        status_response = client.get(f"/v1/tts/jobs/{job_id}", headers=auth_headers)
        assert status_response.status_code == 200
        status_payload = status_response.json()
        if status_payload["status"] == "completed":
            break
        time.sleep(0.02)

    assert status_payload["status"] == "completed"
    result_response = client.get(f"/v1/tts/jobs/{job_id}/result", headers=auth_headers)
    assert result_response.status_code == 200
    assert result_response.content[:4] == b"RIFF"


def test_tts_job_result_endpoint_returns_audio(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    create_response = client.post(
        "/v1/tts/jobs",
        headers=auth_headers,
        json={"text": "Hello world", "voice": "manifest-voice"},
    )
    job_id = create_response.json()["job_id"]

    for _ in range(25):
        status_response = client.get(f"/v1/tts/jobs/{job_id}", headers=auth_headers)
        if status_response.json()["status"] == "completed":
            break
        time.sleep(0.02)

    result_response = client.get(f"/v1/tts/jobs/{job_id}/result", headers=auth_headers)

    assert result_response.status_code == 200
    assert result_response.headers["content-type"] == "audio/wav"
    assert result_response.content[:4] == b"RIFF"


def test_job_status_endpoint_returns_not_found_for_unknown_job(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    response = client.get("/v1/tts/jobs/missing-job-id", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["error"]["type"] == "not_found"


def test_job_result_endpoint_returns_conflict_until_ready(tmp_path: Path, monkeypatch) -> None:
    client, auth_headers, app = build_test_bundle(tmp_path)
    original_synthesize = app.state.container.backend.synthesize

    def delayed_synthesize(self, request):
        time.sleep(0.15)
        return original_synthesize(request)

    monkeypatch.setattr(type(app.state.container.backend), "synthesize", delayed_synthesize)

    create_response = client.post(
        "/v1/tts/jobs",
        headers=auth_headers,
        json={"text": "Hello world", "voice": "manifest-voice"},
    )
    job_id = create_response.json()["job_id"]

    result_response = client.get(f"/v1/tts/jobs/{job_id}/result", headers=auth_headers)

    assert result_response.status_code == 409
    assert result_response.json()["error"]["type"] == "conflict"


def test_tts_jobs_can_cancel_a_queued_job(tmp_path: Path, monkeypatch) -> None:
    client, auth_headers, app = build_test_bundle(
        tmp_path,
        config_data={
            "limits": {
                "max_concurrent_jobs": 1,
                "requests_per_minute": 20,
            }
        },
    )
    original_synthesize = app.state.container.backend.synthesize

    def delayed_synthesize(self, request):
        time.sleep(0.2)
        return original_synthesize(request)

    monkeypatch.setattr(type(app.state.container.backend), "synthesize", delayed_synthesize)

    first_response = client.post(
        "/v1/tts/jobs",
        headers=auth_headers,
        json={"text": "First job", "voice": "manifest-voice"},
    )
    second_response = client.post(
        "/v1/tts/jobs",
        headers=auth_headers,
        json={"text": "Second job", "voice": "manifest-voice"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    second_job_id = second_response.json()["job_id"]

    cancel_response = client.delete(
        f"/v1/tts/jobs/{second_job_id}",
        headers=auth_headers,
    )

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"


def test_completed_jobs_are_cleaned_up_after_ttl(tmp_path: Path) -> None:
    client, auth_headers, app = build_test_bundle(
        tmp_path,
        config_data={
            "limits": {
                "requests_per_minute": 20,
                "completed_job_ttl_seconds": 1,
            }
        },
    )

    create_response = client.post(
        "/v1/tts/jobs",
        headers=auth_headers,
        json={"text": "Hello world", "voice": "manifest-voice"},
    )
    job_id = create_response.json()["job_id"]

    for _ in range(25):
        status_response = client.get(f"/v1/tts/jobs/{job_id}", headers=auth_headers)
        if status_response.json()["status"] == "completed":
            break
        time.sleep(0.02)

    app.state.container.job_manager._jobs[job_id].updated_at = (
        app.state.container.job_manager._jobs[job_id].updated_at.replace(year=2020)
    )

    client.post(
        "/v1/tts/jobs",
        headers=auth_headers,
        json={"text": "Trigger cleanup", "voice": "manifest-voice"},
    )
    missing_response = client.get(f"/v1/tts/jobs/{job_id}", headers=auth_headers)

    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["type"] == "not_found"


def test_auth_rotate_endpoint_replaces_token(tmp_path: Path) -> None:
    client, auth_headers, app = build_test_bundle(tmp_path)
    old_token = app.state.container.auth.token

    rotate_response = client.post("/v1/auth/rotate", headers=auth_headers)

    assert rotate_response.status_code == 200
    new_token = rotate_response.json()["token"]
    assert new_token != old_token
    assert Path(rotate_response.json()["token_file"]).exists()

    old_token_response = client.post(
        "/v1/tts",
        headers=auth_headers,
        json={"text": "Hello world", "voice": "manifest-voice"},
    )
    new_token_response = client.post(
        "/v1/tts",
        headers={"Authorization": f"Bearer {new_token}"},
        json={"text": "Hello world", "voice": "manifest-voice"},
    )

    assert old_token_response.status_code == 401
    assert new_token_response.status_code == 200
