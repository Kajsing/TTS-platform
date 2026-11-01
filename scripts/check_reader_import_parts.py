"""Verify desktop part review and exact source readback in an isolated Windows Reader."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path

import httpx
from check_reader_agent import desktop, service


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reader-exe", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="reader-import-parts-") as directory:
        root = Path(directory)
        (root / "isolated-reader-agent-smoke").touch()
        with service(root) as (url, app):
            with httpx.Client(
                base_url=url,
                trust_env=False,
                timeout=20,
                headers={"Authorization": "Bearer " + app.state.container.auth.token},
            ) as owner:
                folder_response = owner.post(
                    "v1/reader/folders", json={"name": "Import preview test"}
                )
                folder_response.raise_for_status()
                folder = folder_response.json()
                result = desktop(
                    args.reader_exe.resolve(),
                    root,
                    service_url=url,
                    python=sys.executable,
                    phase="import-parts",
                    folder_id=folder["id"],
                )
                assert result["parts"] == 3 and result["preview_before_save"]
                text_parts = []
                for identifier in result.pop("document_ids"):
                    response = owner.get(
                        f"v1/reader/documents/{identifier}/blocks", params={"limit": 100}
                    )
                    response.raise_for_status()
                    payload = response.json()
                    assert payload["next_after_ordinal"] is None
                    text_parts.append("\n\n".join(block["text"] for block in payload["blocks"]))
                expected = "\n\n".join(
                    f"Chapter {number}\n\n" + ("A chapter sentence. " * 4).strip()
                    for number in range(1, 4)
                )
                assert "\n\n".join(text_parts) == expected
                assert all(len(text) <= 160 for text in text_parts)
                result["exact_complete_readback"] = True
                result["source_characters"] = len(expected)
                assert result["batch_parts"] == 6
                batch_text = {}
                for identifier in result.pop("batch_document_ids"):
                    metadata = owner.get(f"v1/reader/documents/{identifier}").json()
                    response = owner.get(
                        f"v1/reader/documents/{identifier}/blocks", params={"limit": 100}
                    )
                    response.raise_for_status()
                    content = "\n\n".join(block["text"] for block in response.json()["blocks"])
                    batch_text.setdefault(metadata["source_name"], []).append(content)
                for filename, parts in batch_text.items():
                    word = "Batch one" if filename == "batch-one.md" else "Batch two"
                    assert "\n\n".join(parts) == expected.replace("A chapter", word)
                assert len(batch_text) == 2
                result["batch_exact_complete_readback"] = True
        args.artifacts.mkdir(parents=True, exist_ok=True)
        for name in (
            "import-parts-preview.png",
            "import-parts-reader.png",
            "batch-parts-preview.png",
        ):
            shutil.copyfile(root / name, args.artifacts / name)
        (args.artifacts / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
