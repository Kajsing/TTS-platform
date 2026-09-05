from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from tts_core.models import JobStatus
from tts_service.config import AppConfig
from tts_service.errors import APIError
from tts_service.jobs import JobRecord
from tts_service.main import create_app
from tts_service.remote_gateway import is_remote_route_allowed
from tts_service.service_control import (
    MAINTENANCE_SECONDS,
    ServiceActivityMiddleware,
    ServiceControlState,
    process_resources,
)


@pytest.fixture
def service_api(tmp_path):
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"warmup_on_start": False},
                "reader": {"home_path": str(tmp_path / "reader"), "exports": {"formats": ["wav"]}},
            }
        ),
        repo_root=tmp_path,
    )
    with TestClient(app, client=("127.0.0.1", 45678)) as client:
        yield client, app, {"Authorization": "Bearer " + app.state.container.auth.token}


def test_status_is_local_native_owner_only(service_api):
    client, app, owner = service_api
    assert client.get("/v1/service/status").status_code == 401
    assert (
        client.get("/v1/service/status", headers={"Authorization": "Bearer invalid"}).status_code
        == 401
    )
    assert (
        client.get("/v1/service/status", headers=owner | {"Origin": "http://localhost"}).status_code
        == 403
    )
    with TestClient(app, client=("198.51.100.23", 50000)) as remote:
        assert remote.get("/v1/service/status", headers=owner).status_code == 403
    for method, path in (
        ("GET", "/v1/service/status"),
        ("POST", "/v1/service/maintenance"),
        ("POST", "/v1/service/maintenance/release"),
    ):
        assert not is_remote_route_allowed(method, path)


def test_status_uses_no_database_queries_and_no_private_text(service_api, monkeypatch):
    client, app, owner = service_api
    repository = app.state.container.reader.service.repository

    def forbid(*args, **kwargs):
        raise AssertionError("Service status must not scan the article database")

    monkeypatch.setattr(type(repository), "report", forbid)
    monkeypatch.setattr(type(repository), "list_export_jobs", forbid)
    result = client.get("/v1/service/status", headers=owner)
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["contract_version"] == 1
    assert payload["activity"] == {
        "active_requests": 0,
        "active_streams": 0,
        "content_leases": 0,
        "pending_exports": 0,
        "pending_jobs": 0,
    }
    assert payload["resources"]["scope"] == "service_process"
    assert payload["resources"]["process_id"] > 0
    assert payload["uptime_s"] >= 0
    assert not {"documents", "titles", "token", "startup_error", "reservation"} & payload.keys()
    app.state.container.backend_ready = False
    assert client.get("/v1/service/status", headers=owner).json()["backend_ready"] is False


def test_reservation_blocks_new_http_and_websocket_work_until_released(service_api):
    client, app, owner = service_api
    instance = app.state.container.service_control.instance_id
    result = client.post("/v1/service/maintenance", headers=owner, json={"instance_id": instance})
    assert result.status_code == 200, result.text
    reservation = result.json()["reservation"]
    assert client.get("/v1/service/status", headers=owner).json()["maintenance"] is True
    blocked = client.post(
        "/v1/reader/documents", headers=owner, json={"title": "Private", "text": "Never created"}
    )
    assert blocked.status_code == 503
    assert blocked.headers["retry-after"] == str(MAINTENANCE_SECONDS)
    assert blocked.json()["error"]["type"] == "service_maintenance"
    assert client.get("/v1/health").status_code == 200
    with pytest.raises(WebSocketDisconnect) as disconnected:
        with client.websocket_connect("/v1/reader/stream", headers=owner):
            pass
    assert disconnected.value.code == 1013
    for invalid in ("wrong", "not-a-reservation-😀"):
        assert (
            client.post(
                "/v1/service/maintenance/release", headers=owner, json={"reservation": invalid}
            ).json()["released"]
            is False
        )
    assert (
        client.post(
            "/v1/service/maintenance", headers=owner, json={"instance_id": instance}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/v1/service/maintenance/release", headers=owner, json={"reservation": reservation}
        ).json()["released"]
        is True
    )
    assert client.get("/v1/reader/documents", headers=owner).json()["documents"] == []


@pytest.mark.parametrize("source", ["request", "export", "job", "stream"])
def test_busy_work_refuses_reservation_including_cancelled_worker(service_api, source):
    client, app, owner = service_api
    container = app.state.container
    future = Future()
    if source == "request":
        assert container.service_control.enter()
    elif source == "export":
        container.reader_exports._futures["private-export"] = future
    elif source == "job":
        container.job_manager._jobs["private-job"] = JobRecord("private-job", JobStatus.CANCELLED)
        container.job_manager._futures["private-job"] = future
    else:
        container.streaming_metrics.mark_started()
    try:
        result = client.post(
            "/v1/service/maintenance",
            headers=owner,
            json={"instance_id": container.service_control.instance_id},
        )
        assert result.status_code == 409, result.text
        assert result.json()["error"]["type"] == "service_busy"
        assert "private" not in result.text
    finally:
        future.set_result(None)
        if source == "request":
            container.service_control.leave()
        elif source == "stream":
            container.streaming_metrics.mark_completed()


def test_reservation_expiry_stale_instance_and_request_race():
    now = [1.0]
    state = ServiceControlState(lambda: now[0])
    with pytest.raises(APIError) as error:
        state.reserve("previous-instance", lambda: False)
    assert error.value.error.type == "service_instance_changed"
    assert state.enter()
    with pytest.raises(APIError):
        state.reserve(state.instance_id, lambda: False)
    state.leave()
    reservation = state.reserve(state.instance_id, lambda: False)
    assert not state.enter()
    now[0] += MAINTENANCE_SECONDS + 1
    assert state.enter()
    assert not state.release(reservation)
    state.leave()
    assert state.snapshot() == {"active_requests": 0, "maintenance": False}


def test_request_tracking_releases_on_failure_and_covers_full_websocket_lifetime():
    async def scenario():
        state = ServiceControlState()

        async def failing(scope, receive, send):
            assert state.snapshot()["active_requests"] == 1
            with pytest.raises(APIError):
                state.reserve(state.instance_id, lambda: False)
            raise RuntimeError("Synthetic failure")

        middleware = ServiceActivityMiddleware(failing, state)
        for kind in ("http", "websocket"):
            with pytest.raises(RuntimeError):
                await middleware({"type": kind, "path": "/v1/tts/stream"}, None, None)
            assert state.snapshot()["active_requests"] == 0

    asyncio.run(scenario())


def test_current_process_resources_are_measured_not_invented():
    first = process_resources()
    second = process_resources()
    assert second["cpu_seconds"] >= first["cpu_seconds"] >= 0
    assert second["sample_monotonic_s"] >= first["sample_monotonic_s"]
    assert second["working_set_bytes"] is None or second["working_set_bytes"] > 0


def test_service_center_unavailable_when_local_auth_is_disabled(tmp_path):
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "auth": {"enabled": False},
                "tts": {"warmup_on_start": False},
                "reader": {"home_path": str(tmp_path / "reader"), "exports": {"formats": ["wav"]}},
            }
        ),
        repo_root=tmp_path,
    )
    with TestClient(app, client=("127.0.0.1", 40000)) as client:
        assert client.get("/v1/service/status").status_code == 503
        assert (
            client.post("/v1/service/maintenance", json={"instance_id": "test"}).status_code == 503
        )


def test_cancelled_worker_is_busy_even_after_public_job_history_expires(service_api, monkeypatch):
    client, app, owner = service_api
    release_worker = threading.Event()
    worker_started = threading.Event()
    manager = app.state.container.job_manager

    def run_worker(*args):
        worker_started.set()
        release_worker.wait(10)

    monkeypatch.setattr(type(manager), "_run_job", run_worker)
    result = client.post("/v1/tts/jobs", headers=owner, json={"text": "Synthetic worker test."})
    assert result.status_code == 200, result.text
    job_id = result.json()["job_id"]
    future = manager._futures[job_id]
    try:
        assert worker_started.wait(3)
        assert client.delete(f"/v1/tts/jobs/{job_id}", headers=owner).status_code == 200
        manager._jobs[job_id].updated_at -= timedelta(seconds=manager.completed_job_ttl_seconds + 1)
        with pytest.raises(APIError):
            manager.get_job(job_id)
        assert job_id not in manager._futures
        assert manager.active_count() == 1
        refused = client.post(
            "/v1/service/maintenance",
            headers=owner,
            json={"instance_id": app.state.container.service_control.instance_id},
        )
        assert refused.status_code == 409
    finally:
        release_worker.set()
        future.result(timeout=5)
    assert manager.active_count() == 0
