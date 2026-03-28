from __future__ import annotations

from tts_service.errors import internal_error, invalid_request


def test_invalid_request_matches_error_contract() -> None:
    error = invalid_request("Unknown voice id", param="voice")

    payload = error.to_response()

    assert error.status_code == 400
    assert payload["error"]["type"] == "invalid_request"
    assert payload["error"]["message"] == "Unknown voice id"
    assert payload["error"]["param"] == "voice"
    assert isinstance(payload["error"]["request_id"], str)
    assert payload["error"]["details"] == {}


def test_internal_error_uses_common_shape() -> None:
    error = internal_error(details={"backend": "sherpa_onnx"})

    payload = error.to_response()

    assert error.status_code == 500
    assert payload["error"]["type"] == "internal_error"
    assert payload["error"]["details"] == {"backend": "sherpa_onnx"}
