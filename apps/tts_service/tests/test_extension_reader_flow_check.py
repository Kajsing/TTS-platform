from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_extension_reader_flow.py"


def test_extension_reader_flow_contract_and_fixture_are_long_page_ready() -> None:
    check_module = _load_check_module()

    contract = check_module._verify_extension_reader_contract()
    fixture_summary = check_module._summarize_article_fixture(
        check_module._build_long_article_fixture()
    )

    assert contract == {
        "checked_files": 5,
        "popup_actions": 5,
        "page_capture_metadata": True,
        "resume_and_section_navigation": True,
        "automatic_truncated_text_continuation": True,
        "truncated_text_continuation": True,
        "truncated_section_continuation": True,
        "stop_restart_recovery": True,
        "popup_reopen_state": True,
        "raw_page_text_persistence": False,
    }
    assert fixture_summary["word_count"] >= 1000
    assert fixture_summary["section_count"] >= 4
    assert fixture_summary["chars"] > 10000


def test_extension_reader_flow_check_orchestrates_service_stream_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    calls: list[str] = []
    token_file = tmp_path / "repo" / "config" / "token.txt"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("token", encoding="utf-8")

    monkeypatch.setattr(check_module, "_verify_extension_reader_contract", lambda: {"ok": True})
    monkeypatch.setattr(
        check_module,
        "_build_long_article_fixture",
        lambda: " ".join(["word"] * 1200)
        + "\n\n"
        + "\n\n".join(["Reader Flow Check"] * 4),
    )
    monkeypatch.setattr(
        check_module.service_bootstrap,
        "_seed_temp_repo",
        lambda repo_root: calls.append("seed"),
    )
    monkeypatch.setattr(check_module.service_bootstrap, "_source_env", lambda: {})
    monkeypatch.setattr(check_module.service_bootstrap, "_reserve_loopback_port", lambda: 7778)
    monkeypatch.setattr(
        check_module.service_bootstrap,
        "_wait_for_health",
        lambda **kwargs: calls.append("health"),
    )
    monkeypatch.setattr(
        check_module.service_bootstrap,
        "_stop_process",
        lambda process: calls.append("stop"),
    )

    def fake_run_json_command(
        command: list[str],
        *,
        env: dict[str, str],
        timeout_s: float,
    ) -> dict[str, object]:
        if "setup-local" in command:
            calls.append("setup")
            return {"token_file": str(token_file)}
        calls.append("smoke")
        return {
            "health": {"status": "ok"},
            "voice": "sherpa-en-debug",
            "input": {"stream_text_chars": 6000},
            "stream": {
                "frames": 12,
                "marks": 12,
                "text_chunk_count": 8,
                "text_chars": 6000,
            },
            "job": {"status": "completed"},
        }

    class FakeProcess:
        pass

    monkeypatch.setattr(
        check_module.service_bootstrap,
        "_run_json_command",
        fake_run_json_command,
    )
    monkeypatch.setattr(check_module.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    summary = check_module.check_extension_reader_flow(
        python_executable="python-test",
        min_stream_text_chunks=8,
    )

    assert calls == ["seed", "setup", "health", "smoke", "stop"]
    assert summary["reader_contract"] == {"ok": True}
    assert summary["article_fixture"]["word_count"] >= 1000
    assert summary["service_stream"]["stream_text_chunk_count"] == 8
    assert summary["service_stream"]["job_status"] == "completed"


def test_extension_reader_flow_check_rejects_short_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_module = _load_check_module()
    monkeypatch.setattr(check_module, "_verify_extension_reader_contract", lambda: {})
    monkeypatch.setattr(check_module, "_build_long_article_fixture", lambda: "too short")

    with pytest.raises(check_module.ExtensionReaderFlowError, match="at least 1000 words"):
        check_module.check_extension_reader_flow(python_executable="python-test")


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_extension_reader_flow",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
