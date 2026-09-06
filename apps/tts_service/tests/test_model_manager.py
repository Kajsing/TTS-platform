from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import httpx
import pytest
from tts_service import cli, model_manager
from tts_service.model_installation import ModelInstallControl


def library(root: Path) -> tuple[Path, Path, bytes]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("model.onnx", "synthetic model")
        archive.writestr("tokens.txt", "synthetic tokens")
    content = buffer.getvalue()
    models = root / "models"
    models.mkdir()
    catalog = models / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "fixture",
                        "name": "Synthetic Danish voice",
                        "language": "da-DK",
                        "license": "Synthetic test fixture only",
                        "license_url": "https://models.example.test/license",
                        "source_url": "https://models.example.test/source",
                        "artifact_url": "https://models.example.test/model.zip",
                        "artifact_size_bytes": len(content),
                        "artifact_sha256": hashlib.sha256(content).hexdigest(),
                        "backend": {
                            "model_type": "vits",
                            "model": "model.onnx",
                            "tokens": "tokens.txt",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = models / "MANIFEST.json"
    manifest.write_text('{"version":1,"voices":[],"custom":"keep"}', encoding="utf-8")
    config = root / "config"
    config.mkdir()
    (config / "config.toml").write_text(
        '[tts]\ndefault_voice="fixture"\n# secret-marker-never-output\n', encoding="utf-8"
    )
    return catalog, manifest, content


def transport(
    monkeypatch: pytest.MonkeyPatch, content: bytes, *, status: int = 200, fail: bool = False
) -> list[str]:
    requests: list[str] = []
    original_client = httpx.Client

    def response(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if fail:
            raise httpx.ReadTimeout("secret-signed-url", request=request)
        return httpx.Response(status, content=content, request=request)

    monkeypatch.setattr(
        cli.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(
        cli.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(response), **kwargs),
    )
    return requests


def test_inventory_is_read_only_and_distinguishes_files_from_service_readiness(tmp_path: Path):
    catalog, manifest, content = library(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = model_manager.inventory(tmp_path)
    package = result["packages"][0]
    assert package["can_install"] is True
    assert package["language"] == "da-DK"
    assert package["size_bytes"] == len(content)
    assert package["family"] == "vits"
    assert package["license_url"] == "https://models.example.test/license"
    assert result["installed_voices"] == []
    assert result["configured_default"] == "fixture"
    assert "secret-marker" not in json.dumps(result)
    assert "ready" not in package
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert result["catalog_fingerprint"] == model_manager.fingerprint(catalog.read_bytes())
    assert result["manifest_fingerprint"] == model_manager.fingerprint(manifest.read_bytes())


@pytest.mark.parametrize(
    "field,value",
    [
        ("license", "unknown"),
        ("license_url", "file:///private"),
        ("source_url", "https://user:password@example.test"),
        ("artifact_sha256", "wrong"),
        ("artifact_url", "C:/private/model.zip"),
        ("backend", {"model_type": "unsupported"}),
        ("id", "../unsafe"),
    ],
)
def test_unreviewable_packages_cannot_be_installed(tmp_path: Path, field: str, value: object):
    catalog, _, _ = library(tmp_path)
    payload = json.loads(catalog.read_bytes())
    payload["models"][0][field] = value
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    package = model_manager.inventory(tmp_path)["packages"][0]
    assert package["can_install"] is False
    assert package["unavailable_reason"]


@pytest.mark.parametrize("accepted,digest", [(False, "current"), (True, "stale")])
def test_license_and_catalog_review_are_required_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accepted: bool, digest: str
):
    _, manifest, content = library(tmp_path)
    original = manifest.read_bytes()
    requests = transport(monkeypatch, content)
    current = model_manager.inventory(tmp_path)["catalog_fingerprint"]
    with pytest.raises(ValueError, match="license|catalog changed"):
        model_manager.install_package(
            tmp_path,
            "fixture",
            current if digest == "current" else digest,
            accepted,
            ModelInstallControl(),
        )
    assert not requests
    assert manifest.read_bytes() == original


def test_install_uses_reviewed_catalog_then_reports_restart_not_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    catalog, manifest, content = library(tmp_path)
    requests = transport(monkeypatch, content)
    inventory = model_manager.inventory(tmp_path)
    original_config = (tmp_path / "config" / "config.toml").read_bytes()
    events = []

    def progress(event):
        events.append(event)
        if event["phase"] == "resolving":
            catalog.write_text("changed after snapshot", encoding="utf-8")

    result = model_manager.install_package(
        tmp_path,
        "fixture",
        inventory["catalog_fingerprint"],
        True,
        ModelInstallControl(progress=progress),
    )
    assert requests == ["https://models.example.test/model.zip"]
    assert result == {
        "package_id": "fixture",
        "voice_ids": ["fixture"],
        "checksum_verified": True,
        "activation": "restart_required",
    }
    assert {event["phase"] for event in events} == {
        "resolving",
        "downloading",
        "verifying",
        "extracting",
        "committing",
        "completed",
    }
    assert json.loads(manifest.read_bytes())["custom"] == "keep"
    assert (tmp_path / "config" / "config.toml").read_bytes() == original_config


@pytest.mark.parametrize("failure", ["checksum", "download", "extraction", "timeout"])
def test_failed_install_preserves_registry_and_reports_no_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
):
    catalog, manifest, content = library(tmp_path)
    original = manifest.read_bytes()
    if failure == "checksum":
        content = b"wrong bytes"
    if failure == "extraction":
        content = b"not an archive"
        payload = json.loads(catalog.read_bytes())
        payload["models"][0]["artifact_sha256"] = hashlib.sha256(content).hexdigest()
        payload["models"][0]["artifact_size_bytes"] = len(content)
        catalog.write_text(json.dumps(payload), encoding="utf-8")
    transport(
        monkeypatch,
        content,
        status=503 if failure == "download" else 200,
        fail=failure == "timeout",
    )
    with pytest.raises((SystemExit, httpx.HTTPError)):
        model_manager.install_package(
            tmp_path,
            "fixture",
            model_manager.inventory(tmp_path)["catalog_fingerprint"],
            True,
            ModelInstallControl(),
        )
    assert manifest.read_bytes() == original
    voices = tmp_path / "models" / "voices"
    assert not voices.exists() or list(voices.iterdir()) == []


def test_installed_voice_can_be_inspected_but_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _, manifest, content = library(tmp_path)
    transport(monkeypatch, content)
    digest = model_manager.inventory(tmp_path)["catalog_fingerprint"]
    model_manager.install_package(tmp_path, "fixture", digest, True, ModelInstallControl())
    state = model_manager.inventory(tmp_path)
    assert state["packages"][0]["installed"] is True
    assert state["packages"][0]["can_install"] is False
    assert state["installed_voices"][0]["assets_present"] is True
    assert state["installed_voices"][0]["is_configured_default"] is True
    before = manifest.read_bytes()
    with pytest.raises(ValueError, match="replacing existing data"):
        model_manager.install_package(tmp_path, "fixture", digest, True, ModelInstallControl())
    assert manifest.read_bytes() == before


@pytest.mark.parametrize("message", ['{"cancel":true}\n', "", "invalid", "x" * 4097])
def test_cancel_protocol_handles_request_eof_invalid_and_oversized_input(message: str):
    cancelled = threading.Event()
    model_manager.watch_cancel(io.StringIO(message), cancelled)
    assert cancelled.is_set()


def test_subprocess_list_contract_and_sanitized_failure(tmp_path: Path):
    _, manifest, _ = library(tmp_path)
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    command = [
        sys.executable,
        "-m",
        "tts_service.model_manager",
        "list",
        "--repo-root",
        str(tmp_path),
    ]
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    event = json.loads(result.stdout)
    assert event["contract_version"] == 1
    assert event["event"] == "result"
    assert "secret-marker" not in result.stdout + result.stderr
    manifest.write_text("secret-marker-invalid-manifest", encoding="utf-8")
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode == 1
    event = json.loads(result.stdout)
    assert event["event"] == "failed"
    assert "secret-marker" not in result.stdout + result.stderr


def test_metadata_size_limit_is_read_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "oversized.json"
    path.write_text('{"long":"' + "x" * 100 + '"}', encoding="utf-8")
    monkeypatch.setattr(model_manager, "MAX_METADATA_BYTES", 16)
    with pytest.raises(ValueError, match="size limit"):
        model_manager.metadata(path)


def test_error_events_do_not_echo_downloader_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    def fail(args, send, cancelled):
        send({"event": "progress", "phase": "downloading"})
        raise OSError("secret-signed-url")

    monkeypatch.setattr(model_manager, "run", fail)
    assert model_manager.main(["list", "--repo-root", str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert "secret-signed-url" not in output.out + output.err
    events = [json.loads(line) for line in output.out.splitlines()]
    assert events[-1]["event"] == "failed"
    assert events[-1]["phase"] == "downloading"


@pytest.mark.parametrize("cancel_message", ['{"cancel":true}\n', ""])
def test_real_helper_pipe_cancels_cooperatively_without_forcing_process_exit(
    tmp_path: Path, cancel_message: str
):
    # A synthetic install waits for the real JSON-lines/stdin protocol; no model
    # download, live service, user manifest or native engine is involved.
    code = """
import sys
from tts_service import model_manager
def synthetic_install(root, package, digest, accepted, control):
    control.report('downloading', force=True)
    event = control.cancelled.__self__
    if not event.wait(5):
        raise RuntimeError('The owner did not send cancellation')
    control.check()
model_manager.install_package = synthetic_install
raise SystemExit(model_manager.main(['install', '--repo-root', sys.argv[1]]))
"""
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env=environment,
        input=cancel_message,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 2, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1]["event"] == "cancelled"
    assert all(event["contract_version"] == 1 for event in events)
    assert not list(tmp_path.iterdir())
