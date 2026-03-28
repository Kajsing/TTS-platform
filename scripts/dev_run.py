from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = REPO_ROOT / "apps" / "tts_service" / "src"
CORE_SRC = REPO_ROOT / "packages" / "tts_core" / "src"

for path in (SERVICE_SRC, CORE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tts_service.main import create_app  # noqa: E402


def main() -> None:
    config_path = REPO_ROOT / "config" / "config.toml"
    app = create_app(config_path=config_path if config_path.exists() else None)
    uvicorn.run(app, host="127.0.0.1", port=7777, reload=False)


if __name__ == "__main__":
    main()
