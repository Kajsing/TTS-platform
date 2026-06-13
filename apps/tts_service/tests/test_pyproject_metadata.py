from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_pyproject_exposes_real_runtime_extra() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    real_extra = pyproject["project"]["optional-dependencies"]["real"]

    assert "numpy>=1.26.0,<3.0.0" in real_extra
    assert "sherpa-onnx>=1.13.0,<2.0.0" in real_extra
