from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "reader_core" / "src"))

from reader_core import ReaderLibrary, SqliteReaderRepository  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a consistent Reader developer-preview SQLite snapshot."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/reader-preview/reader-preview.db"),
    )
    parser.add_argument(
        "--source-db",
        type=Path,
        help="Back up an explicitly selected Reader database instead of seeded preview data.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _seed_preview(repository: SqliteReaderRepository) -> int:
    library = ReaderLibrary(repository)
    library.create_plain_text_document(
        title="Reader developer preview",
        language_hint="en-US",
        text=(
            "Welcome to TTS Platform Reader.\n\n"
            "This local preview demonstrates bounded streaming, durable resume, "
            "source highlighting, and direct text correction.\n\n"
            "Pause playback before editing this document."
        ),
    )
    library.create_plain_text_document(
        title="Dansk prøve med Unicode",
        language_hint="da-DK",
        text=(
            "Dette er en dansk prøve med æ, ø og å.\n\n"
            "Emoji-offsets gemmes som UTF-16: 😀.\n\n"
            "Dokumentet kan redigeres, og hver gemt rettelse kan fortrydes."
        ),
    )
    return 2


def main() -> int:
    args = _parser().parse_args()
    output = args.output.resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="tts-reader-preview-") as temporary:
            if args.source_db is not None:
                source_path = args.source_db.resolve()
                if not source_path.is_file():
                    raise FileNotFoundError(f"Reader source database was not found: {source_path}")
                repository = SqliteReaderRepository(source_path, initialize=False)
                document_count: int | None = None
                source = "explicit-database"
            else:
                repository = SqliteReaderRepository(Path(temporary) / "reader.db")
                document_count = _seed_preview(repository)
                source = "seeded-preview"

            backup = repository.backup_to(output, overwrite=args.overwrite)
            report = SqliteReaderRepository(backup, initialize=False).report()
        print(
            json.dumps(
                {
                    "snapshot": str(backup),
                    "source": source,
                    "document_count": document_count,
                    "schema_version": report.schema_version,
                    "integrity_ok": report.integrity_ok,
                    "journal_mode": report.journal_mode,
                },
                indent=2,
            )
        )
        return 0
    except (FileExistsError, FileNotFoundError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
