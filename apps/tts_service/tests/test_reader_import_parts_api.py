from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from reader_core import ReaderValidationError
from reader_core.chapters import CHAPTER_KEY
from reader_core.sqlite.transactions import TransactionRepository
from tts_service.config import AppConfig
from tts_service.main import create_app
from tts_service.reader_privacy import PRIVACY_SESSION_HEADER

ROOT = "/v1/reader"
SOURCE = b"# One\n\nabcd\n\n# Two\n\nefgh\n\n# Three\n\nijkl"


@pytest.fixture
def parts_api(tmp_path):
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"warmup_on_start": False},
                "reader": {"home_path": str(tmp_path / "reader"), "exports": {"formats": ["wav"]}},
            }
        ),
        repo_root=tmp_path,
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + app.state.container.auth.token}
    yield client, headers, app.state.container.reader.service
    client.close()


def upload(client, headers, source=SOURCE, *, copy=False):
    response = client.post(
        ROOT + "/imports/preview",
        headers=headers,
        files={"file": ("book.md", source, "text/markdown")},
        data={"title": "Book", "copy_source_file": str(copy).lower()},
    )
    assert response.status_code == 200, response.text
    return response.json()["preview_id"]


def preview(client, headers, preview_id, **changes):
    response = client.post(
        ROOT + f"/imports/{preview_id}/parts-preview",
        headers=headers,
        json={"max_characters": 20, "heading_level": 1} | changes,
    )
    assert response.status_code == 200, response.text
    return response.json()


def commit(client, headers, preview_id, plan, **changes):
    return client.post(
        ROOT + f"/imports/{preview_id}/parts-commit",
        headers=headers,
        json={
            "plan_key": plan["plan_key"],
            "max_characters": plan["max_characters"],
            "heading_level": plan["heading_level"],
        }
        | changes,
    )


def test_parts_preview_writes_nothing_then_atomic_commit_preserves_source_and_chapters(parts_api):
    client, headers, service = parts_api
    preview_id = upload(client, headers, copy=True)
    plan = preview(client, headers, preview_id)
    assert plan["can_commit"] and plan["issues"] == []
    assert plan["chapter_count"] == 3 and len(plan["parts"]) == 2
    assert service.repository.list_documents().items == ()
    assert not list(service.managed_files_path.glob("*"))
    response = commit(client, headers, preview_id, plan)
    assert response.status_code == 201, response.text
    documents = response.json()["documents"]
    assert [item["title"] for item in documents] == [
        "Book - Part 01 (Chapters 1-2)",
        "Book - Part 02 (Chapters 3-3)",
    ]
    text_parts = []
    for document, part in zip(documents, plan["parts"], strict=True):
        bundle = service.repository.get_document_bundle(document["id"])
        text = "\n\n".join(block.text for block in bundle.blocks)
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == part["text_sha256"]
        assert len(text) == part["codepoints"] <= 20
        assert len(text.encode("utf-16-le")) // 2 == part["utf16_units"] <= 20
        assert all(block.kind.value in {"heading", "paragraph"} for block in bundle.blocks)
        assert (
            len(bundle.document.metadata[CHAPTER_KEY])
            == part["last_chapter"] - part["first_chapter"] + 1
        )
        assert document["source_sha256"] == hashlib.sha256(SOURCE).hexdigest()
        text_parts.append(text)
    assert "\n\n".join(text_parts) == "One\n\nabcd\n\nTwo\n\nefgh\n\nThree\n\nijkl"
    assert len({item["source_uri"] for item in documents}) == 1
    source_files = list(service.managed_files_path.glob("*.md"))
    assert len(source_files) == 1 and source_files[0].read_bytes() == SOURCE
    assert commit(client, headers, preview_id, plan).status_code == 404


def test_selected_heading_level_default_policy_and_oversized_whole_chapter(parts_api):
    client, headers, service = parts_api
    preview_id = upload(client, headers)
    normal = client.post(ROOT + f"/imports/{preview_id}/parts-preview", headers=headers, json={})
    assert normal.status_code == 200 and normal.json()["max_characters"] == 900_000
    assert len(normal.json()["parts"]) == 1
    no_boundaries = preview(client, headers, preview_id, heading_level=9)
    assert no_boundaries["chapter_count"] == 1 and not no_boundaries["can_commit"]
    assert "whole" in no_boundaries["issues"][0]
    assert commit(client, headers, preview_id, no_boundaries).status_code == 400
    assert service.repository.list_documents().items == ()


def test_stale_plan_key_and_changed_policy_are_rejected_without_consuming_preview(parts_api):
    client, headers, service = parts_api
    preview_id = upload(client, headers)
    plan = preview(client, headers, preview_id)
    assert commit(client, headers, preview_id, plan, plan_key="0" * 64).status_code == 400
    assert commit(client, headers, preview_id, plan, max_characters=30).status_code == 400
    assert service.repository.list_documents().items == ()
    assert commit(client, headers, preview_id, plan).status_code == 201


def test_changed_cached_source_rejects_previously_previewed_key(parts_api):
    client, headers, service = parts_api
    preview_id = upload(client, headers)
    plan = preview(client, headers, preview_id)
    cached = service._import_previews[preview_id]
    changed = replace(cached.imported, metadata={"changed": True})
    service._import_previews[preview_id] = replace(cached, imported=changed)
    assert commit(client, headers, preview_id, plan).status_code == 400
    assert service.repository.list_documents().items == ()


def test_expired_preview_and_cancelled_preview_cannot_commit(parts_api):
    client, headers, service = parts_api
    preview_id = upload(client, headers)
    plan = preview(client, headers, preview_id)
    cached = service._import_previews[preview_id]
    service._import_previews[preview_id] = replace(cached, created_at_monotonic=-1000)
    assert commit(client, headers, preview_id, plan).status_code == 404
    other = upload(client, headers)
    other_plan = preview(client, headers, other)
    assert client.delete(ROOT + f"/imports/{other}", headers=headers).status_code == 204
    assert commit(client, headers, other, other_plan).status_code == 404
    assert service.repository.list_documents().items == ()


def test_duplicate_check_uses_original_whole_file_hash_once_and_needs_explicit_override(parts_api):
    client, headers, service = parts_api
    first = upload(client, headers)
    assert commit(client, headers, first, preview(client, headers, first)).status_code == 201
    second = upload(client, headers)
    plan = preview(client, headers, second)
    duplicate = commit(client, headers, second, plan)
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["type"] == "reader_duplicate_document"
    assert len(service.repository.list_documents().items) == 2
    assert commit(client, headers, second, plan, allow_duplicate=True).status_code == 201
    assert len(service.repository.list_documents().items) == 4


def test_second_part_failure_rolls_back_every_document_and_one_copied_source(
    parts_api, monkeypatch
):
    client, headers, service = parts_api
    preview_id = upload(client, headers, copy=True)
    plan = preview(client, headers, preview_id)
    original = TransactionRepository.create_document
    created = 0

    def fail_second(self, bundle):
        nonlocal created
        created += 1
        if created == 2:
            raise ReaderValidationError("Injected second-part failure")
        return original(self, bundle)

    monkeypatch.setattr(TransactionRepository, "create_document", fail_second)
    failed = commit(client, headers, preview_id, plan)
    assert failed.status_code == 400, failed.text
    assert service.repository.list_documents().items == ()
    assert not list(service.managed_files_path.glob("*"))
    assert preview_id in service._import_previews
    monkeypatch.setattr(TransactionRepository, "create_document", original)
    assert commit(client, headers, preview_id, plan).status_code == 201
    assert len(list(service.managed_files_path.glob("*.md"))) == 1


def test_folder_privacy_rechecked_at_commit_and_valid_session_can_import(parts_api):
    client, headers, service = parts_api
    folder = service.create_folder("Private")
    preview_id = upload(client, headers)
    plan = preview(client, headers, preview_id)
    lock = service.privacy.setup(folder.id, code="123456", expected_row_version=1)
    denied = commit(client, headers, preview_id, plan, folder_id=folder.id)
    assert denied.status_code == 423 and denied.json()["error"]["type"] == "reader_privacy_locked"
    assert service.repository.list_documents(unlocked_folder_ids=(folder.id,)).items == ()
    unlocked = headers | {PRIVACY_SESSION_HEADER: lock.session.token}
    allowed = commit(client, unlocked, preview_id, plan, folder_id=folder.id)
    assert allowed.status_code == 201, allowed.text
    assert all(document["folder_id"] == folder.id for document in allowed.json()["documents"])


def test_expired_privacy_session_is_not_trusted_from_earlier_preview(parts_api):
    client, headers, service = parts_api
    folder = service.create_folder("Private")
    lock = service.privacy.setup(folder.id, code="123456", expected_row_version=1)
    unlocked = headers | {PRIVACY_SESSION_HEADER: lock.session.token}
    preview_id = upload(client, unlocked)
    plan = preview(client, unlocked, preview_id)
    service.privacy.relock(folder.id, (lock.session.token,))
    assert commit(client, unlocked, preview_id, plan, folder_id=folder.id).status_code == 423
    assert preview_id in service._import_previews


@pytest.mark.parametrize(
    "payload",
    [
        {"max_characters": 0},
        {"max_characters": True},
        {"max_characters": "900000"},
        {"max_characters": 1_000_001},
        {"heading_level": 0},
        {"heading_level": 10},
        {"heading_level": "1"},
        {"extra": True},
    ],
)
def test_part_preview_payload_is_strict_and_bounded(parts_api, payload):
    client, headers, _ = parts_api
    preview_id = upload(client, headers)
    response = client.post(
        ROOT + f"/imports/{preview_id}/parts-preview", headers=headers, json=payload
    )
    assert response.status_code == 400, response.text


def test_owner_auth_required_for_part_preview_and_commit(parts_api):
    client, headers, service = parts_api
    preview_id = upload(client, headers)
    plan = preview(client, headers, preview_id)
    assert client.post(ROOT + f"/imports/{preview_id}/parts-preview", json={}).status_code == 401
    assert commit(client, {}, preview_id, plan).status_code == 401
    folder = service.create_folder("Agent")
    _, secret = service.agents.store.provision(folder.id, "Agent")
    agent = {"Authorization": "Bearer " + secret}
    assert (
        client.post(
            ROOT + f"/imports/{preview_id}/parts-preview", headers=agent, json={}
        ).status_code
        == 401
    )
    assert commit(client, agent, preview_id, plan).status_code == 401


def test_retained_source_copy_bytes_are_aggregate_bounded_and_cancel_releases_budget(parts_api):
    client, headers, service = parts_api
    service.config = replace(
        service.config,
        imports=replace(
            service.config.imports,
            max_file_bytes=len(SOURCE) + 1,
        ),
    )
    first = upload(client, headers, copy=True)
    denied = client.post(
        ROOT + "/imports/preview",
        headers=headers,
        files={"file": ("book.md", SOURCE, "text/markdown")},
        data={"copy_source_file": "true"},
    )
    assert denied.status_code == 409, denied.text
    assert first in service._import_previews and len(service._import_previews) == 1
    # An uncopied preview consumes character budget but retains no raw source.
    second = upload(client, headers, copy=False)
    assert service._import_previews[second].source_data is None
    assert client.delete(ROOT + f"/imports/{first}", headers=headers).status_code == 204
    third = upload(client, headers, copy=True)
    assert service._import_previews[third].source_data == SOURCE
