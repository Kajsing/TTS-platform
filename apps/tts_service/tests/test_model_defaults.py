from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from tts_service import model_defaults, model_manager
from tts_service.model_installation import ModelInstallCancelled, ModelInstallControl


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("ending", [True, False])
def test_only_default_scalar_changes_preserving_comments_unicode_and_newlines(newline, ending):
    original = newline.join(
        [
            "# private-token-comment æøå",
            "[other]",
            'value = "keep"',
            "[tts] # synthesis",
            "  default_voice = 'old'  # my choice",
            "speed = 1.0",
            "[custom]",
            'content = "unchanged"',
        ]
    ) + (newline if ending else "")
    actual = model_defaults.default_config_bytes(original.encode(), "next")
    assert actual == original.replace("'old'", '"next"').encode()


@pytest.mark.parametrize("original", ["[tts]", "[tts]\n", "[tts]\nspeed=1.0\n[custom]\nvalue=2"])
def test_missing_default_is_inserted_without_other_semantic_changes(original):
    parsed = model_defaults.tomllib.loads(
        model_defaults.default_config_bytes(original.encode(), "next").decode()
    )
    assert parsed["tts"]["default_voice"] == "next"


@pytest.mark.parametrize(
    "original",
    [
        'tts = {default_voice="old"}',
        'tts.default_voice="old"',
        '[tts]\ndefault_voice="""old"""',
        'content="""\n[tts]\ndefault_voice="old"\n"""\n[tts]\ndefault_voice="old"',
    ],
)
def test_unusual_or_misleading_layout_is_refused(original):
    with pytest.raises(ValueError):
        model_defaults.default_config_bytes(original.encode(), "next")


def installed_library(root: Path):
    models = root / "models"
    models.mkdir()
    assets = models / "voices" / "next"
    assets.mkdir(parents=True)
    (assets / "model.onnx").write_bytes(b"synthetic model, never loaded")
    (assets / "tokens.txt").write_text("synthetic tokens")
    manifest = models / "MANIFEST.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "custom": "preserve",
                "voices": [
                    {
                        "id": "next",
                        "name": "Next",
                        "language": "en-US",
                        "engine": "sherpa_onnx",
                        "source": "models/voices/next",
                        "backend": {
                            "model_type": "vits",
                            "model": "model.onnx",
                            "tokens": "tokens.txt",
                        },
                    }
                ],
            }
        )
    )
    config = root / "config" / "config.toml"
    config.parent.mkdir()
    config.write_bytes(b'[tts]\r\ndefault_voice = "old" # keep\r\n# secret-marker\r\n')
    return manifest, config, model_manager.inventory(root)


def select(root, inventory, control=None):
    return model_manager.set_default_voice(
        root,
        "next",
        inventory["manifest_fingerprint"],
        inventory["config_fingerprint"],
        control or ModelInstallControl(),
    )


def test_default_is_deferred_and_manifest_untouched(tmp_path):
    manifest, config, inventory = installed_library(tmp_path)
    before = manifest.read_bytes()
    assert inventory["installed_voices"][0]["assets_present"]
    assert select(tmp_path, inventory) == {"voice_id": "next", "activation": "restart_required"}
    assert manifest.read_bytes() == before
    assert config.read_bytes() == b'[tts]\r\ndefault_voice = "next" # keep\r\n# secret-marker\r\n'
    after = model_manager.inventory(tmp_path)
    assert after["configured_default"] == "next"
    assert after["config_fingerprint"] != inventory["config_fingerprint"]
    assert "secret-marker" not in json.dumps(after)
    assert not list(config.parent.glob("*.tmp"))
    assert not list(config.parent.glob("*.recovery"))


@pytest.mark.parametrize(
    "fault", ["manifest", "config", "missing-assets", "cancel", "invalid-config"]
)
def test_stale_intent_missing_assets_and_cancel_preserve_settings(tmp_path, fault):
    manifest, config, inventory = installed_library(tmp_path)
    if fault == "manifest":
        manifest.write_text(manifest.read_text() + " ")
    if fault == "config":
        config.write_bytes(config.read_bytes() + b"# other editor\n")
    if fault == "invalid-config":
        config.write_bytes(b"invalid = [")
        inventory["config_fingerprint"] = model_manager.fingerprint(config.read_bytes())
    if fault == "missing-assets":
        (tmp_path / "models" / "voices" / "next" / "tokens.txt").unlink()
    before = config.read_bytes()
    with pytest.raises((ValueError, ModelInstallCancelled)):
        select(tmp_path, inventory, ModelInstallControl(cancelled=lambda: fault == "cancel"))
    assert config.read_bytes() == before


@pytest.mark.parametrize("partial", [False, True])
def test_replace_failure_preserves_or_recovers_original(tmp_path, monkeypatch, partial):
    _, config, inventory = installed_library(tmp_path)
    before = config.read_bytes()

    def fail(path, staging, backup):
        if partial:
            path.rename(backup)  # Documented ReplaceFile partial failure.
        raise PermissionError("synthetic failure, never output")

    monkeypatch.setattr(model_defaults, "_replace_private", fail)
    with pytest.raises(PermissionError):
        select(tmp_path, inventory)
    assert config.read_bytes() == before
    assert not list(config.parent.glob("*.tmp"))


def test_concurrent_config_edit_is_not_overwritten(tmp_path, monkeypatch):
    _, config, inventory = installed_library(tmp_path)
    original = model_defaults._copy_private
    changed = config.read_bytes() + b"# concurrent edit\n"

    def edit(source, destination):
        original(source, destination)
        config.write_bytes(changed)

    monkeypatch.setattr(model_defaults, "_copy_private", edit)
    with pytest.raises(ValueError, match="changed"):
        select(tmp_path, inventory)
    assert config.read_bytes() == changed


def test_default_helper_uses_explicit_verb_and_sanitizes_failures(tmp_path, capsys, monkeypatch):
    _, config, inventory = installed_library(tmp_path)
    events = []
    model_manager.run(
        argparse.Namespace(
            command="set-default",
            repo_root=str(tmp_path),
            voice_id="next",
            manifest_fingerprint=inventory["manifest_fingerprint"],
            config_fingerprint=inventory["config_fingerprint"],
        ),
        events.append,
        threading.Event(),
    )
    assert events == [
        {"event": "result", "data": {"voice_id": "next", "activation": "restart_required"}}
    ]
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"cancel":true}\n'))
    result = model_manager.main(
        [
            "set-default",
            "--repo-root",
            str(tmp_path),
            "--voice-id",
            "next",
            "--manifest-fingerprint",
            inventory["manifest_fingerprint"],
            "--config-fingerprint",
            inventory["config_fingerprint"],
        ]
    )
    assert result == 1  # The old reviewed fingerprint is stale, never blindly retried.
    assert "secret-marker" not in capsys.readouterr().out


@pytest.mark.skipif(os.name != "nt", reason="Windows DACL preservation")
def test_windows_custom_acl_is_preserved_on_staging_and_final_config(tmp_path, monkeypatch):
    _, config, inventory = installed_library(tmp_path)
    environment = dict(os.environ, TTS_FIXTURE_PATH=str(config))
    script = """
    $p = $env:TTS_FIXTURE_PATH
    $acl = [System.IO.File]::GetAccessControl($p)
    $acl.SetAccessRuleProtection($true, $false)
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'Allow')
    $acl.SetAccessRule($rule)
    [System.IO.File]::SetAccessControl($p, $acl)
    [System.IO.File]::GetAccessControl($p).GetSecurityDescriptorSddlForm('All')
    """

    def sddl(
        path,
        command="[System.IO.File]::GetAccessControl($env:TTS_FIXTURE_PATH).GetSecurityDescriptorSddlForm('All')",
    ):
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            env=dict(environment, TTS_FIXTURE_PATH=str(path)),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    expected = sddl(config, script)
    replace = model_defaults._replace_private

    def verify(path, staging, backup):
        # AI records past automatic inheritance, not an access grant. Setting a
        # protected DACL on a new file need not retain that historical flag.
        assert sddl(staging).replace("D:PAI", "D:P") == expected.replace("D:PAI", "D:P")
        replace(path, staging, backup)

    monkeypatch.setattr(model_defaults, "_replace_private", verify)
    select(tmp_path, inventory)
    assert sddl(config) == expected
