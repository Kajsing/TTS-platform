from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = REPO_ROOT / "contracts" / "reader"
for source_root in (
    REPO_ROOT / "packages" / "reader_core" / "src",
    REPO_ROOT / "packages" / "speech_rules" / "src",
    REPO_ROOT / "apps" / "tts_service" / "src",
):
    sys.path.insert(0, str(source_root))

from tts_service.reader_schemas import (  # noqa: E402
    CreateReaderBrowserCaptureRequest,
    CreateReaderDocumentRequest,
    CreateReaderExportRequest,
    MoveReaderDocumentsRequest,
    ReaderBrowserCaptureResponse,
    ReaderCapabilitiesResponse,
    ReaderDesktopOpenRequestResponse,
    ReaderDocumentResponse,
    ReaderErrorResponse,
    ReaderExportJobResponse,
    ReaderFolderDeleteResponse,
    ReaderFolderPageResponse,
    ReaderHighlighterResponse,
    ReaderImportPreviewResponse,
    ReaderMutationResponse,
    ReaderPrivacyLockResponse,
    ReaderPrivacySessionResponse,
    ReaderRulePreviewResponse,
    ReplaceReaderHighlighterRequest,
    SaveReaderPositionRequest,
)

FIXTURES = {
    "browser_capture.request.json": CreateReaderBrowserCaptureRequest,
    "browser_capture.response.json": ReaderBrowserCaptureResponse,
    "capabilities.response.json": ReaderCapabilitiesResponse,
    "create_document.request.json": CreateReaderDocumentRequest,
    "create_export.request.json": CreateReaderExportRequest,
    "desktop_open_request.response.json": ReaderDesktopOpenRequestResponse,
    "document.response.json": ReaderDocumentResponse,
    "position.request.json": SaveReaderPositionRequest,
    "mutation.response.json": ReaderMutationResponse,
    "privacy_lock.response.json": ReaderPrivacyLockResponse,
    "privacy_session.response.json": ReaderPrivacySessionResponse,
    "error.response.json": ReaderErrorResponse,
    "export_job.response.json": ReaderExportJobResponse,
    "folders.response.json": ReaderFolderPageResponse,
    "move_documents.request.json": MoveReaderDocumentsRequest,
    "folder_delete.response.json": ReaderFolderDeleteResponse,
    "import_preview.response.json": ReaderImportPreviewResponse,
    "highlighter.request.json": ReplaceReaderHighlighterRequest,
    "highlighter.response.json": ReaderHighlighterResponse,
    "rule_preview.response.json": ReaderRulePreviewResponse,
}


def main() -> None:
    missing = sorted(set(FIXTURES) - {path.name for path in CONTRACT_ROOT.glob("*.json")})
    if missing:
        raise SystemExit(f"Missing Reader contract fixtures: {missing}")

    validated: list[str] = []
    for filename, model_type in FIXTURES.items():
        path = CONTRACT_ROOT / filename
        raw = json.loads(path.read_text(encoding="utf-8"))
        model = model_type.model_validate(raw)
        normalized = model.model_dump(mode="json", exclude_none=False)
        if normalized != raw:
            raise SystemExit(f"Reader contract fixture does not round-trip exactly: {filename}")
        validated.append(filename)

    print(
        json.dumps(
            {
                "contract_version": 1,
                "fixtures_validated": len(validated),
                "fixtures": validated,
                "status": "ready",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
