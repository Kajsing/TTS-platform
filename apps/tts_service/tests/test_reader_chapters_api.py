from pathlib import Path

from reader_core.chapters import CHAPTER_KEY
from test_reader_api import build_reader_bundle, create_document


def test_chapter_api_utf16_version_history_and_append(tmp_path: Path) -> None:
    client, headers, _ = build_reader_bundle(tmp_path)
    document = create_document(client, headers, text="A😀BCD.\n\nNext paragraph.")
    base = f"/v1/reader/documents/{document['id']}"
    blocks = client.get(base + "/blocks", headers=headers).json()["blocks"]
    request = {
        "expected_row_version": document["row_version"],
        "action": "add",
        "title": "Second",
        "block_id": blocks[0]["id"],
        "character_offset": 3,
    }
    assert client.post(base + "/chapters", json=request).status_code == 401
    invalid = client.post(
        base + "/chapters", headers=headers, json={**request, "character_offset": 2}
    )
    assert invalid.status_code == 400
    created = client.post(base + "/chapters", headers=headers, json=request)
    assert created.status_code == 200, created.text
    updated = created.json()["document"]
    markers = updated["metadata"][CHAPTER_KEY]
    assert len(markers) == 2
    assert markers[1]["codepoint_offset"] == 2
    assert markers[1]["title"] == "Second"
    assert client.get(base + "/blocks", headers=headers).json()["blocks"] == blocks
    stale = client.post(base + "/chapters", headers=headers, json=request)
    assert stale.status_code == 409
    undone = client.post(
        base + "/undo", headers=headers, json={"expected_row_version": updated["row_version"]}
    )
    assert undone.status_code == 200, undone.text
    assert len(undone.json()["document"]["metadata"][CHAPTER_KEY]) == 1
    redone = client.post(
        base + "/redo",
        headers=headers,
        json={"expected_row_version": undone.json()["document"]["row_version"]},
    )
    assert redone.status_code == 200, redone.text
    updated = redone.json()["document"]
    assert updated["metadata"][CHAPTER_KEY] == markers
    for new_chapter, expected in ((True, 3), (False, 3)):
        appended = client.post(
            base + "/append",
            headers=headers,
            json={
                "expected_row_version": updated["row_version"],
                "text": "Another chapter.",
                "new_chapter": new_chapter,
            },
        )
        assert appended.status_code == 200, appended.text
        updated = appended.json()["document"]
        assert len(updated["metadata"][CHAPTER_KEY]) == expected


def test_chapter_mutations_respect_playback_lease(tmp_path: Path) -> None:
    client, headers, app = build_reader_bundle(tmp_path)
    document = create_document(client, headers)
    base = f"/v1/reader/documents/{document['id']}"
    with app.state.container.reader.service.content_lease(document["id"], "test-chapter"):
        response = client.post(
            base + "/chapters",
            headers=headers,
            json={
                "expected_row_version": document["row_version"],
                "action": "rename",
                "chapter_id": "root",
                "title": "Not while reading",
            },
        )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["type"] == "reader_document_locked"
    assert client.get(base, headers=headers).json() == document
