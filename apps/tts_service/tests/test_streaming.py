from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import tts_service.main as main_module
from fastapi.testclient import TestClient
from tts_service.config import AppConfig
from tts_service.main import create_app


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
            frame_count = max(64, len(text) * 8)
            samples = [0.2 if index % 2 == 0 else -0.2 for index in range(frame_count)]
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
                "supports_streaming": true,
                "supports_multi_speaker": false
              }
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    base_config = {"tts": {"default_voice": "manifest-voice"}}
    if config_data:
        base_config.update(config_data)
    app = create_app(config=AppConfig.from_mapping(base_config), repo_root=tmp_path)
    auth_headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    return TestClient(app), auth_headers, app


def _read_next_message(websocket):
    message = websocket.receive()
    if message.get("bytes") is not None:
        return ("bytes", message["bytes"])
    if message.get("text") is not None:
        return ("json", json.loads(message["text"]))
    return ("other", message)


def test_websocket_stream_requires_auth(tmp_path: Path) -> None:
    client, _, _ = build_test_bundle(tmp_path)

    with client.websocket_connect("/v1/tts/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "text": "Missing auth should fail.",
                    "voice": "manifest-voice",
                },
            }
        )
        message_type, payload = _read_next_message(websocket)

    assert message_type == "json"
    assert payload["type"] == "error"
    assert payload["error"]["type"] == "unauthorized"


def test_websocket_stream_returns_audio_frames_and_done_event(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "text": "Hello streaming world.",
                    "voice": "manifest-voice",
                },
            }
        )

        started = websocket.receive_json()
        assert started["type"] == "started"
        assert started["job_id"]
        assert started["progress"]["text_chunk_count"] >= 1
        assert started["progress"]["percent"] == 0.0

        binary_frames = 0
        mark_events = 0
        done_payload = None
        for _ in range(64):
            message_type, payload = _read_next_message(websocket)
            if message_type == "json" and payload["type"] == "mark":
                mark_events += 1
                assert payload["chunk_index"] >= 0
                assert payload["duration_ms"] >= 1
                assert payload["progress"]["text_chunk_index"] >= 0
                assert payload["progress"]["text_chunk_count"] >= 1
                continue
            if message_type == "bytes":
                binary_frames += 1
                assert payload
                continue
            if message_type == "json" and payload["type"] == "done":
                done_payload = payload
                break

        assert binary_frames > 0
        assert mark_events == binary_frames
        assert done_payload is not None
        assert done_payload["chunks_sent"] == binary_frames
        assert done_payload["progress"]["percent"] == 1.0

    health_response = client.get("/v1/health")
    streaming_metrics = health_response.json()["streaming"]
    assert streaming_metrics["total_streams"] >= 1
    assert streaming_metrics["completed_streams"] >= 1
    assert streaming_metrics["active_streams"] == 0


def test_websocket_stream_accepts_auth_token_in_start_event(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)
    token = auth_headers["Authorization"].split(" ", maxsplit=1)[1]

    with client.websocket_connect("/v1/tts/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "auth_token": token,
                "payload": {
                    "text": "Hello extension streaming world.",
                    "voice": "manifest-voice",
                },
            }
        )

        started = websocket.receive_json()
        assert started["type"] == "started"
        assert started["job_id"]


def test_websocket_stream_rejects_oversized_start_event_before_auth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(main_module, "WEBSOCKET_START_MESSAGE_OVERHEAD_CHARS", 16)
    client, _, _ = build_test_bundle(
        tmp_path,
        config_data={
            "tts": {
                "default_voice": "manifest-voice",
                "max_chars_per_request": 80,
                "max_chars_per_stream": 120,
            }
        },
    )

    raw_start_event = json.dumps(
        {
            "type": "start",
            "payload": {
                "text": "Oversized pre-auth stream frame. " * 8,
                "voice": "manifest-voice",
            },
        }
    )

    with client.websocket_connect("/v1/tts/stream") as websocket:
        websocket.send_text(raw_start_event)
        error_payload = websocket.receive_json()

    assert error_payload["type"] == "error"
    assert error_payload["error"]["type"] == "invalid_request"
    assert error_payload["error"]["param"] == "payload"
    assert error_payload["error"]["details"]["max_start_message_chars"] == 136


def test_websocket_stream_accepts_text_above_http_request_limit(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(
        tmp_path,
        config_data={
            "tts": {
                "default_voice": "manifest-voice",
                "max_chars_per_request": 80,
                "max_chars_per_stream": 2000,
            },
            "streaming": {"audio_frame_ms": 1000},
        },
    )
    long_text = " ".join(
        f"Sentence {index} has enough readable words for streaming."
        for index in range(20)
    )
    assert len(long_text) > 80
    assert len(long_text) < 2000

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "text": long_text,
                    "voice": "manifest-voice",
                },
            }
        )

        started = websocket.receive_json()
        assert started["type"] == "started"
        assert started["progress"]["text_chunk_count"] > 1

        binary_frames = 0
        done_payload = None
        for _ in range(256):
            message_type, payload = _read_next_message(websocket)
            if message_type == "bytes":
                binary_frames += 1
                continue
            if message_type == "json" and payload["type"] == "done":
                done_payload = payload
                break

    assert binary_frames > 0
    assert done_payload is not None
    assert done_payload["progress"]["percent"] == 1.0


def test_websocket_stream_rejects_text_above_stream_limit(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(
        tmp_path,
        config_data={
            "tts": {
                "default_voice": "manifest-voice",
                "max_chars_per_request": 80,
                "max_chars_per_stream": 120,
            }
        },
    )

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "text": "Long streaming input. " * 8,
                    "voice": "manifest-voice",
                },
            }
        )
        error_payload = websocket.receive_json()

    assert error_payload["type"] == "error"
    assert error_payload["error"]["type"] == "invalid_request"
    assert error_payload["error"]["param"] == "text"
    assert error_payload["error"]["details"]["max_chars_per_stream"] == 120


def test_websocket_stream_can_start_from_text_chunk_index(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(
        tmp_path,
        config_data={"streaming": {"audio_frame_ms": 1000}},
    )
    long_sentence = (
        "Alpha clause introduces the topic with concrete examples, "
        "beta clause adds more context about timing and workflow, "
        "gamma clause expands on reliability, observability, and safety, "
        "delta clause closes the idea with a practical takeaway."
    )

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "start_text_chunk_index": 1,
                "payload": {
                    "text": long_sentence,
                    "voice": "manifest-voice",
                },
            }
        )

        started = websocket.receive_json()
        assert started["type"] == "started"
        assert started["progress"]["text_chunk_index"] == 1
        assert started["progress"]["text_chunk_count"] == 2
        assert started["progress"]["completed_text_chars"] > 0

        first_mark_payload = None
        done_payload = None
        for _ in range(64):
            message_type, payload = _read_next_message(websocket)
            if message_type == "json" and payload["type"] == "mark":
                first_mark_payload = payload
                continue
            if message_type == "json" and payload["type"] == "done":
                done_payload = payload
                break

    assert first_mark_payload is not None
    assert first_mark_payload["progress"]["text_chunk_index"] == 1
    assert done_payload is not None
    assert done_payload["progress"]["percent"] == 1.0


def test_websocket_stream_rejects_start_text_chunk_index_outside_plan(
    tmp_path: Path,
) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "start_text_chunk_index": 99,
                "payload": {
                    "text": "Hello streaming world.",
                    "voice": "manifest-voice",
                },
            }
        )
        error_payload = websocket.receive_json()

    assert error_payload["type"] == "error"
    assert error_payload["error"]["type"] == "invalid_request"
    assert error_payload["error"]["param"] == "start_text_chunk_index"
    assert error_payload["error"]["details"]["text_chunk_count"] == 1


def test_websocket_stream_can_be_cancelled(tmp_path: Path, monkeypatch) -> None:
    client, auth_headers, app = build_test_bundle(tmp_path)
    original_stream = app.state.container.backend.synthesize_stream

    def delayed_stream(self, request):
        for index, chunk in enumerate(original_stream(request)):
            yield chunk
            if index == 0:
                time.sleep(0.05)

    monkeypatch.setattr(type(app.state.container.backend), "synthesize_stream", delayed_stream)

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "text": "Hello streaming world.",
                    "voice": "manifest-voice",
                },
            }
        )

        started = websocket.receive_json()
        assert started["type"] == "started"

        first_mark_type, first_mark_payload = _read_next_message(websocket)
        assert first_mark_type == "json"
        assert first_mark_payload["type"] == "mark"

        first_message_type, first_payload = _read_next_message(websocket)
        assert first_message_type == "bytes"
        assert first_payload

        websocket.send_json({"type": "cancel"})

        cancelled_payload = None
        for _ in range(32):
            message_type, payload = _read_next_message(websocket)
            if message_type == "json" and payload["type"] == "cancelled":
                cancelled_payload = payload
                break

        assert cancelled_payload is not None
        assert cancelled_payload["chunks_sent"] >= 1
        assert cancelled_payload["progress"]["text_chunk_count"] >= 1

    health_response = client.get("/v1/health")
    streaming_metrics = health_response.json()["streaming"]
    assert streaming_metrics["cancelled_streams"] >= 1


def test_websocket_stream_rejects_invalid_first_event(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        websocket.send_json({"type": "ping"})
        error_payload = websocket.receive_json()

    assert error_payload["type"] == "error"
    assert error_payload["error"]["type"] == "invalid_request"
    assert error_payload["error"]["param"] == "type"


def test_websocket_stream_times_out_waiting_for_initial_start_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(main_module, "WEBSOCKET_START_TIMEOUT_SECONDS", 0.05)
    client, auth_headers, _ = build_test_bundle(tmp_path)

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        error_payload = websocket.receive_json()

    assert error_payload["type"] == "error"
    assert error_payload["error"]["type"] == "invalid_request"
    assert error_payload["error"]["param"] == "type"


def test_websocket_stream_rejects_invalid_payload(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(tmp_path)
    raw_text = "sensitive browser page text"

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "text": [raw_text],
                    "voice": "manifest-voice",
                },
            }
        )
        error_payload = websocket.receive_json()

    assert error_payload["type"] == "error"
    assert error_payload["error"]["type"] == "invalid_request"
    assert error_payload["error"]["details"]["issues"]
    assert error_payload["error"]["param"] == "text"
    serialized_payload = json.dumps(error_payload)
    assert raw_text not in serialized_payload
    assert "input" not in serialized_payload


def test_websocket_stream_blocks_unapproved_origin(tmp_path: Path) -> None:
    client, auth_headers, _ = build_test_bundle(
        tmp_path,
        config_data={
            "security": {
                "allowed_origins": ["chrome-extension://approved-extension"],
            }
        },
    )

    with client.websocket_connect(
        "/v1/tts/stream",
        headers={
            **auth_headers,
            "Origin": "chrome-extension://other-extension",
        },
    ) as websocket:
        error_payload = websocket.receive_json()

    assert error_payload["type"] == "error"
    assert error_payload["error"]["type"] == "forbidden_origin"


def test_websocket_stream_can_use_real_backend_runtime(
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
              "capabilities": {
                "supports_pitch": false,
                "supports_streaming": true,
                "supports_multi_speaker": false
              },
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

    with client.websocket_connect("/v1/tts/stream", headers=auth_headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "text": "Hello real streaming runtime.",
                    "voice": "manifest-voice",
                },
            }
        )

        started = websocket.receive_json()
        assert started["type"] == "started"
        assert started["sample_rate_hz"] == 22050

        binary_frames = 0
        done_payload = None
        for _ in range(64):
            message_type, payload = _read_next_message(websocket)
            if message_type == "bytes":
                binary_frames += 1
                assert payload
                continue
            if message_type == "json" and payload["type"] == "done":
                done_payload = payload
                break

        assert binary_frames > 0
        assert done_payload is not None
