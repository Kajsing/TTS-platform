from __future__ import annotations

import json

import pytest
from reader_core import BoundedReaderBlockPage, FolderDocumentVersion, ReaderLibrary
from test_reader_api import build_reader_bundle
from tts_service import reader_routes
from tts_service.config import AppConfig
from tts_service.errors import APIError
from tts_service.reader_block_pages import bounded_block_page_response
from tts_service.reader_privacy import PRIVACY_SESSION_HEADER
from tts_service.reader_schemas import ReaderBlockPageResponse, ReaderBlockResponse


@pytest.mark.parametrize("text", ["Plain text " * 20, "é😀" * 120, '\\"\x01' * 150])
def test_exact_serialized_boundary_includes_unicode_and_json_escaping(tmp_path, text):
    _, _, app = build_reader_bundle(tmp_path)
    repository = app.state.container.reader.service.repository
    document = ReaderLibrary(repository).create_plain_text_document(title="Boundary", text=text)
    blocks = repository.list_blocks(document.id)
    expected = (
        ReaderBlockPageResponse(
            blocks=[ReaderBlockResponse.from_domain(block) for block in blocks],
            next_after_ordinal=None,
        )
        .model_dump_json()
        .encode()
    )
    page = BoundedReaderBlockPage(blocks, None)
    response = bounded_block_page_response(page, len(expected))
    assert response.body == expected
    with pytest.raises(APIError) as refused:
        bounded_block_page_response(page, len(expected) - 1)
    assert refused.value.status_code == 413
    assert refused.value.error.type == "reader_block_too_large"


def test_http_pages_never_exceed_cap_and_recombine_exact_source(tmp_path):
    maximum = 1800
    client, headers, app = build_reader_bundle(
        tmp_path, reader_config={"max_block_page_bytes": maximum}
    )
    repository = app.state.container.reader.service.repository
    document = ReaderLibrary(repository).create_plain_text_document(
        title="Many complete blocks",
        text="\n\n".join(f"Block {i}: " + '\\"\x01😀' * 20 for i in range(17)),
    )
    expected = repository.list_blocks(document.id)
    after = -1
    actual = []
    for _ in range(20):
        response = client.get(
            f"/v1/reader/documents/{document.id}/blocks?after_ordinal={after}&limit=10",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert len(response.content) <= maximum
        page = response.json()
        actual.extend(page["blocks"])
        if page["next_after_ordinal"] is None:
            break
        assert page["next_after_ordinal"] > after
        after = page["next_after_ordinal"]
    else:
        pytest.fail("Byte-limited page did not advance to completion")
    assert [block["id"] for block in actual] == [block.id for block in expected]
    assert [block["text"] for block in actual] == [block.text for block in expected]
    assert all(block["character_count"] == len(block["text"]) for block in actual)


def test_public_error_preserves_source_and_does_not_leak_text(tmp_path):
    client, headers, app = build_reader_bundle(
        tmp_path, reader_config={"max_block_page_bytes": 1000}
    )
    repository = app.state.container.reader.service.repository
    text = "PRIVATE source " * 200
    document = ReaderLibrary(repository).create_plain_text_document(title="Private", text=text)
    url = f"/v1/reader/documents/{document.id}/blocks"
    assert client.get(url).status_code == 401
    response = client.get(url, headers=headers)
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["type"] == "reader_block_too_large"
    assert error["details"]["max_block_page_bytes"] == 1000
    assert error["details"]["block_ordinal"] == 0
    assert "PRIVATE source" not in response.text
    assert repository.list_blocks(document.id)[0].text == text.strip()


@pytest.mark.parametrize("privacy_change", ["relock", "move"])
def test_threaded_block_response_rechecks_privacy_after_serialization(
    tmp_path, monkeypatch, privacy_change
):
    client, headers, app = build_reader_bundle(tmp_path)
    service = app.state.container.reader.service
    document = ReaderLibrary(service.repository).create_plain_text_document(
        title="Private response fence", text="PRIVATE block response source."
    )
    folder = service.create_folder("Private response fence")
    if privacy_change == "relock":
        service.move_documents(
            (FolderDocumentVersion(document.id, document.row_version),), folder_id=folder.id
        )
    privacy = service.privacy.setup(
        folder.id, code="correct code", expected_row_version=folder.row_version
    )
    request_headers = (
        {**headers, PRIVACY_SESSION_HEADER: privacy.session.token}
        if privacy_change == "relock"
        else headers
    )
    original_response = reader_routes.bounded_block_page_response

    def change_privacy_after_serialization(*args, **kwargs):
        response = original_response(*args, **kwargs)
        if privacy_change == "relock":
            service.privacy.relock(folder.id, (privacy.session.token,))
        else:
            service.move_documents(
                (FolderDocumentVersion(document.id, document.row_version),), folder_id=folder.id
            )
        return response

    monkeypatch.setattr(
        reader_routes, "bounded_block_page_response", change_privacy_after_serialization
    )
    response = client.get(
        f"/v1/reader/documents/{document.id}/blocks", headers=request_headers
    )
    assert response.status_code == 423, response.text
    assert response.json()["error"]["type"] == "reader_privacy_locked"
    assert "PRIVATE block response source." not in response.text


def test_metadata_and_escape_expansion_are_part_of_actual_response_cap(tmp_path):
    client, headers, app = build_reader_bundle(
        tmp_path, reader_config={"max_block_page_bytes": 1000}
    )
    repository = app.state.container.reader.service.repository
    document = ReaderLibrary(repository).create_plain_text_document(title="Metadata", text="Safe.")
    with repository._write() as connection:
        connection.execute(
            "UPDATE reader_blocks SET metadata_json = ? WHERE document_id = ?",
            (json.dumps({"quote": '\\"' * 200}), document.id),
        )
    response = client.get(f"/v1/reader/documents/{document.id}/blocks", headers=headers)
    assert response.status_code == 413
    assert response.json()["error"]["type"] == "reader_block_too_large"


def test_capability_reports_page_bytes_and_character_bound(tmp_path):
    client, headers, _ = build_reader_bundle(
        tmp_path, reader_config={"max_block_page_bytes": 12345}
    )
    capability = client.get("/v1/reader/capabilities", headers=headers).json()["block_pages"]
    assert capability == {
        "max_response_bytes": 12345,
        "max_block_characters": 1_000_000,
        "whole_blocks_only": True,
    }


@pytest.mark.parametrize("maximum", [0, -1])
def test_block_page_byte_limit_must_be_positive(maximum):
    with pytest.raises(ValueError, match="max_block_page_bytes"):
        AppConfig.from_mapping({"reader": {"max_block_page_bytes": maximum}})
