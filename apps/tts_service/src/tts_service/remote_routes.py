from __future__ import annotations

import ipaddress

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .reader_errors import reader_api_error
from .remote_access import RemoteAccessError, RemoteAccessManager


class RemoteSetupRequest(BaseModel):
    bind_host: str = Field(min_length=1, max_length=64)
    port: int = Field(default=7790, ge=1024, le=65535)
    server_name: str | None = Field(default=None, max_length=253)
    firewall_mode: str = Field(default="wireguard", max_length=16)
    firewall_remote_address: str = Field(min_length=1, max_length=64)
    firewall_interface_alias: str | None = Field(default=None, max_length=128)
    firewall_profile: str = Field(default="Public", max_length=16)
    start: bool = False


class RemoteInvitationRequest(BaseModel):
    pass


def build_remote_admin_router() -> APIRouter:
    router = APIRouter(prefix="/v1/reader/remote", tags=["reader-remote-admin"])

    @router.get("/status")
    async def remote_status(request: Request) -> dict[str, object]:
        return _manager(request).status_payload()

    @router.post("/setup")
    async def setup_remote(
        request: Request,
        payload: RemoteSetupRequest,
    ) -> dict[str, object]:
        manager = _manager(request)
        try:
            await run_in_threadpool(
                manager.configure,
                bind_host=payload.bind_host,
                port=payload.port,
                server_name=payload.server_name,
                firewall_mode=payload.firewall_mode,
                firewall_remote_address=payload.firewall_remote_address,
                firewall_interface_alias=payload.firewall_interface_alias,
                firewall_profile=payload.firewall_profile,
                start=payload.start,
            )
        except RemoteAccessError as exc:
            raise _remote_error("reader_remote_setup_failed", 400, str(exc)) from exc
        return manager.status_payload()

    @router.post("/invitations", status_code=status.HTTP_201_CREATED)
    async def create_invitation(
        request: Request,
        _: RemoteInvitationRequest,
    ) -> dict[str, object]:
        manager = _manager(request)
        try:
            profile = manager.load_profile()
            if profile is None or not profile.enabled:
                raise RemoteAccessError("Remote access is not configured and enabled.")
            return manager.store.create_invitation(profile)
        except RemoteAccessError as exc:
            raise _remote_error("reader_remote_not_ready", 409, str(exc)) from exc

    @router.get("/devices")
    async def list_devices(request: Request) -> dict[str, object]:
        devices = _manager(request).store.list_devices()
        return {"devices": [device.to_payload() for device in devices]}

    @router.delete("/devices/{device_id}")
    async def revoke_device(request: Request, device_id: str) -> dict[str, object]:
        try:
            device = _manager(request).store.revoke_device(device_id)
        except RemoteAccessError as exc:
            raise _remote_error("reader_remote_device_not_found", 404, str(exc)) from exc
        return {"device": device.to_payload(), "revoked": True}

    @router.post("/disable")
    async def disable_remote(request: Request) -> dict[str, object]:
        manager = _manager(request)
        try:
            return await run_in_threadpool(manager.disable)
        except RemoteAccessError as exc:
            raise _remote_error("reader_remote_disable_failed", 500, str(exc)) from exc

    return router


def _manager(request: Request) -> RemoteAccessManager:
    if request.headers.get("origin"):
        raise _remote_error(
            "reader_remote_admin_local_only",
            403,
            "Remote access administration is available only to the native local Reader.",
        )
    client_host = request.client.host if request.client is not None else ""
    try:
        is_loopback = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise _remote_error(
            "reader_remote_admin_local_only",
            403,
            "Remote access administration is available only on this computer.",
        )
    manager = request.app.state.container.remote_access
    if manager is None:
        raise _remote_error(
            "reader_remote_unavailable",
            503,
            "Reader remote access is unavailable because the Reader library is not ready.",
        )
    return manager


def _remote_error(error_type: str, status_code: int, message: str):
    return reader_api_error(error_type, status_code=status_code, message=message)
