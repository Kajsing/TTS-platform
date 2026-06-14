from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_SCRIPT_PATH = REPO_ROOT / "scripts" / "demo_real_voice.py"


def test_seed_demo_root_copies_public_inputs_without_local_secrets(tmp_path: Path) -> None:
    demo_module = _load_demo_module()
    demo_root = tmp_path / "demo"

    summary = demo_module._seed_demo_root(demo_root)

    assert summary["copied_files"] == [
        "config/config.example.toml",
        "models/catalog.json",
        "models/MANIFEST.json",
    ]
    assert (demo_root / "config" / "config.example.toml").is_file()
    assert (demo_root / "models" / "catalog.json").is_file()
    assert (demo_root / "models" / "MANIFEST.json").is_file()
    assert not (demo_root / "config" / "token.txt").exists()
    assert not (demo_root / "models" / "voices").exists()


def test_real_voice_demo_orchestrates_install_smoke_and_wav(
    tmp_path: Path,
    monkeypatch,
) -> None:
    demo_module = _load_demo_module()
    demo_root = tmp_path / "demo"
    commands: list[list[str]] = []
    events: list[str] = []
    stopped_processes: list[object] = []
    model_check_calls = 0

    class FakeProcess:
        pid = 12345
        returncode = None

        def poll(self):
            return None

    def fake_run_json_command(command, *, env, timeout_s):
        nonlocal model_check_calls
        commands.append(command)
        if "setup-local" in command:
            events.append("setup")
            token_file = demo_root / "config" / "token.txt"
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text("demo-token", encoding="utf-8")
            return {
                "config_created": True,
                "token_created": True,
                "default_voice": "sherpa-en-debug",
                "token_file": str(token_file),
                "runtime": {"sherpa_onnx_installed": True},
                "next_steps": ["tts model-install vits-piper-en_US-lessac-medium --activate"],
            }
        if "model-check" in command:
            model_check_calls += 1
            ready = model_check_calls > 1
            return {
                "ready": ready,
                "config": {"default_voice": "vits-piper-en_US-lessac-medium"},
                "runtime": {"sherpa_onnx_installed": True, "numpy_installed": True},
                "backend": {"assets_ready": ready},
            }
        if "model-install" in command:
            return {
                "installed_model": "vits-piper-en_US-lessac-medium",
                "activated_model": "vits-piper-en_US-lessac-medium",
                "checksum_verified": True,
                "files_installed": 359,
            }
        if "smoke_service.py" in " ".join(command):
            return {
                "voice": "vits-piper-en_US-lessac-medium",
                "health": {"status": "ok"},
                "http": {"bytes": 100},
                "stream": {"text_chunk_count": 2},
                "job": {"status": "completed"},
            }
        raise AssertionError(f"Unexpected command: {command}")

    def fake_install_real_runtime_dependencies(**kwargs):
        events.append("runtime")
        return {"performed": True, "command": 'python -m pip install -e ".[real]"'}

    monkeypatch.setattr(
        demo_module,
        "_install_real_runtime_dependencies",
        fake_install_real_runtime_dependencies,
    )
    monkeypatch.setattr(demo_module, "_run_json_command", fake_run_json_command)
    monkeypatch.setattr(demo_module, "_reserve_loopback_port", lambda: 45678)
    monkeypatch.setattr(
        demo_module,
        "_start_service",
        lambda **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        demo_module,
        "_wait_for_health",
        lambda **kwargs: {
            "status": "ok",
            "default_voice": "vits-piper-en_US-lessac-medium",
            "checks": {"backend_ready": True, "default_voice_loaded": True},
        },
    )
    monkeypatch.setattr(
        demo_module,
        "_write_demo_wav",
        lambda **kwargs: {
            "path": str(kwargs["out_path"]),
            "bytes": 379314,
            "duration_ms": 8600,
            "sample_rate_hz": 22050,
            "channels": 1,
        },
    )
    monkeypatch.setattr(demo_module, "_stop_process_tree", stopped_processes.append)

    summary = demo_module.run_real_voice_demo(
        python_executable="python",
        demo_root=demo_root,
        model_id="vits-piper-en_US-lessac-medium",
        out_path=None,
        text="Hello real voice.",
        port=0,
        startup_timeout_s=1,
        command_timeout_s=1,
        stream_text_repeat=2,
        min_stream_text_chunks=2,
        skip_smoke=False,
        force_install=False,
        install_real_runtime=True,
    )

    assert events[:2] == ["runtime", "setup"]
    smoke_commands = [command for command in commands if "smoke_service.py" in " ".join(command)]
    assert smoke_commands
    assert "--token-file" in smoke_commands[0]
    assert "--token" not in smoke_commands[0]
    assert summary["runtime_install"]["performed"] is True
    assert summary["install"]["performed"] is True
    assert summary["model_check"]["ready"] is True
    assert summary["service"]["base_url"] == "http://127.0.0.1:45678"
    assert summary["wav"]["sample_rate_hz"] == 22050
    assert len(stopped_processes) == 1


def _load_demo_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_demo_real_voice",
        DEMO_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
