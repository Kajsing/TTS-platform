from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_v1_readiness.py"


def test_v1_readiness_check_passes_repo_state() -> None:
    check_module = _load_v1_readiness_module()

    summary = check_module.check_v1_readiness(repo_root=REPO_ROOT)

    assert summary["manual_gates_documented"] is True
    assert summary["product_choices_documented"] is True
    assert summary["checked_files"] >= 20


def test_v1_readiness_check_rejects_missing_manual_gate(tmp_path: Path) -> None:
    check_module = _load_v1_readiness_module()
    _write_minimal_readiness_repo(check_module, tmp_path)
    readiness_path = tmp_path / "docs" / "v1_readiness.md"
    readiness_path.write_text("# V1 Readiness Audit\n\n## Automated Gates\n", encoding="utf-8")

    with pytest.raises(check_module.V1ReadinessError, match="## Manual Gates"):
        check_module.check_v1_readiness(repo_root=tmp_path)


def _write_minimal_readiness_repo(check_module, repo_root: Path) -> None:
    for relative_path in check_module.REQUIRED_FILES:
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    (repo_root / "docs" / "v1_readiness.md").write_text(
        "\n".join(check_module.READINESS_MARKERS),
        encoding="utf-8",
    )
    for relative_path, markers in check_module.REQUIRED_TEXT_MARKERS.items():
        (repo_root / relative_path).write_text("\n".join(markers), encoding="utf-8")


def _load_v1_readiness_module():
    spec = importlib.util.spec_from_file_location(
        "tts_platform_check_v1_readiness",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
