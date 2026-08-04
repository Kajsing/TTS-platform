from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from document_import import ImportOptions, ImportSource
from fastapi.testclient import TestClient
from reader_core import (
    BlockKind,
    ReaderBlock,
    ReaderLibrary,
    RuleScope,
    RuleStage,
    RuleType,
    SqliteReaderRepository,
)
from speech_rules import RuleContext
from tts_core.text import ChunkPlanner, SentenceSegmenter, TextNormalizer
from tts_service.config import AppConfig, ReaderConfig
from tts_service.main import create_app
from tts_service.observability import ObservabilityState
from tts_service.reader_service import (
    ReaderApplicationService,
    ReaderDocumentLockedError,
)
from tts_service.reader_streaming import (
    ReaderBlockSlice,
    ReaderSpeechCompiler,
    ReaderStreamWindowBuilder,
)


def _service(tmp_path: Path) -> ReaderApplicationService:
    return ReaderApplicationService(
        SqliteReaderRepository(tmp_path / "reader.db"),
        config=ReaderConfig(home_path=str(tmp_path)),
        observability=ObservabilityState(
            enabled=False,
            logger=logging.getLogger("reader-stream-test"),
        ),
    )


def _builder(service: ReaderApplicationService) -> ReaderStreamWindowBuilder:
    return ReaderStreamWindowBuilder(
        service,
        ReaderSpeechCompiler(
            TextNormalizer(),
            SentenceSegmenter(),
            ChunkPlanner(),
        ),
    )


def _api_bundle(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    app = create_app(
        config=AppConfig.from_mapping(
            {
                "tts": {"warmup_on_start": False},
                "backend": {"mode": "stub"},
                "reader": {"home_path": str(tmp_path / "reader-api")},
                "limits": {"requests_per_minute": 1000},
            }
        ),
        repo_root=tmp_path,
    )
    headers = {"Authorization": f"Bearer {app.state.container.auth.token}"}
    return TestClient(app), headers


def _api_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    text: str,
) -> dict[str, object]:
    response = client.post(
        "/v1/reader/documents",
        headers=headers,
        json={"title": "Stream test", "source_type": "plain_text", "text": text},
    )
    assert response.status_code == 201
    return response.json()


def _next_message(websocket) -> tuple[str, object]:
    message = websocket.receive()
    if message.get("bytes") is not None:
        return "bytes", message["bytes"]
    if message.get("text") is not None:
        return "json", json.loads(message["text"])
    return "other", message


def test_window_is_bounded_and_returns_stable_continuation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    document = ReaderLibrary(service.repository).create_plain_text_document(
        title="Long document",
        text="\n\n".join(f"Paragraph {index}." for index in range(1000)),
    )

    window = _builder(service).build(
        document.id,
        block_ordinal=0,
        character_offset_utf16=0,
        block_id=None,
        content_revision=document.content_revision,
        max_blocks=3,
        max_source_characters=10_000,
    )

    assert len(window.blocks) == 3
    assert window.next_cursor is not None
    assert window.next_cursor.block_ordinal == 3
    assert window.document_complete is False
    assert window.source_character_count < 10_000


def test_window_normalizes_start_cursor_after_an_exhausted_block(tmp_path: Path) -> None:
    service = _service(tmp_path)
    document = ReaderLibrary(service.repository).create_plain_text_document(
        title="Resume boundary",
        text="Finished block.\n\nNext block.",
    )
    first_block = service.list_blocks(document.id, after_ordinal=-1, limit=1)[0]

    window = _builder(service).build(
        document.id,
        block_ordinal=first_block.ordinal,
        character_offset_utf16=len(first_block.text),
        block_id=first_block.id,
        content_revision=document.content_revision,
        max_blocks=1,
        max_source_characters=32_000,
    )

    assert len(window.blocks) == 1
    assert window.blocks[0].block.ordinal == 1
    assert window.start_cursor.block_id == window.blocks[0].block.id
    assert window.start_cursor.block_ordinal == 1
    assert window.start_cursor.character_offset == 0


def test_window_clips_inside_a_block_at_the_source_character_limit(tmp_path: Path) -> None:
    service = _service(tmp_path)
    document = ReaderLibrary(service.repository).create_plain_text_document(
        title="One block",
        text="A😀BCDEF",
    )

    window = _builder(service).build(
        document.id,
        block_ordinal=0,
        character_offset_utf16=1,
        block_id=None,
        content_revision=1,
        max_blocks=64,
        max_source_characters=2,
    )

    assert window.blocks[0].text == "😀B"
    assert window.next_cursor is not None
    assert window.next_cursor.block_ordinal == 0
    assert window.next_cursor.character_offset == 3
    assert window.next_cursor.api_payload(window.blocks[0].block.text)[
        "character_offset"
    ] == 4


def test_compiler_maps_normalized_danish_and_emoji_to_original_utf16_span(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    document = ReaderLibrary(service.repository).create_plain_text_document(
        title="Mapped",
        text="fx. & 😀.",
        language_hint="da",
    )

    window = _builder(service).build(
        document.id,
        block_ordinal=0,
        character_offset_utf16=0,
        block_id=None,
        content_revision=1,
        max_blocks=64,
        max_source_characters=32_000,
    )

    fragment = window.fragments[0]
    block_text = window.blocks[0].block.text
    assert fragment.spoken_text == "for eksempel og 😀."
    assert fragment.source_spans[0].api_payload(block_text) == {
        "block_id": window.blocks[0].block.id,
        "block_ordinal": 0,
        "start_offset": 0,
        "end_offset": 9,
    }
    assert fragment.cursor_end.api_payload(block_text)["character_offset"] == 9


def test_compiler_maps_a_chunk_joined_across_adjacent_segments(tmp_path: Path) -> None:
    service = _service(tmp_path)
    document = ReaderLibrary(service.repository).create_plain_text_document(
        title="Joined",
        text="Edited through .NET \U0001f600",
    )

    window = _builder(service).build(
        document.id,
        block_ordinal=0,
        character_offset_utf16=0,
        block_id=None,
        content_revision=1,
        max_blocks=64,
        max_source_characters=32_000,
    )

    assert len(window.fragments) == 1
    assert window.fragments[0].spoken_text == "Edited through. NET \U0001f600"
    assert window.fragments[0].source_spans[0].start_offset == 0
    assert window.fragments[0].source_spans[0].end_offset == len("Edited through .NET \U0001f600")


def test_compiler_speaks_visible_markdown_fenced_text_blocks(tmp_path: Path) -> None:
    service = _service(tmp_path)
    document = service.import_source(
        source=ImportSource(
            filename="chapter.md",
            content_type="text/markdown",
            data=(
                b"Before.\n\n```text\n"
                b"[IDENTITY RESOLUTION FAILED]\n\n"
                b"No valid regional record.\n"
                b"Recovery authority: unavailable.\n"
                b"Local continuity protection: partial.\n"
                b"```\n\n```python\nprint('not spoken')\n```\n\nAfter."
            ),
        ),
        options=ImportOptions(language_hint="en"),
        copy_source_file=False,
        allow_duplicate=False,
    )

    window = _builder(service).build(
        document.id,
        block_ordinal=0,
        character_offset_utf16=0,
        block_id=None,
        content_revision=document.content_revision,
        max_blocks=64,
        max_source_characters=32_000,
    )

    blocks = service.list_blocks(document.id, after_ordinal=-1, limit=64)
    assert [block.kind.value for block in blocks] == [
        "paragraph",
        "code",
        "code",
        "paragraph",
    ]
    assert blocks[1].metadata == {"markdown_fence_language": "text"}
    assert blocks[2].metadata == {"markdown_fence_language": "python"}
    spoken = " ".join(fragment.spoken_text for fragment in window.fragments)
    assert "[IDENTITY RESOLUTION FAILED]" in spoken
    assert "No valid regional record." in spoken
    assert "Recovery authority: unavailable." in spoken
    assert "Local continuity protection: partial." in spoken
    assert "not spoken" not in spoken


def test_compiler_speaks_legacy_bracketed_notification_code_blocks() -> None:
    text = (
        "[ROUTE CONTINUITY DEGRADED]\n\n"
        "Traveller identity: unresolved.\n"
        "Segment history: conflicting.\n"
        "Load compensation: suspended."
    )
    block = ReaderBlock(
        id="00000000-0000-0000-0000-000000000001",
        document_id="00000000-0000-0000-0000-000000000002",
        section_id=None,
        ordinal=0,
        kind=BlockKind.CODE,
        text=text,
        character_count=len(text),
        content_sha256="legacy",
    )
    compiler = ReaderSpeechCompiler(TextNormalizer(), SentenceSegmenter(), ChunkPlanner())

    fragments = compiler.compile_slices(
        (ReaderBlockSlice(block=block, start_offset=0, end_offset=len(text)),),
        content_revision=1,
        language_hint="en",
    )

    spoken = " ".join(fragment.spoken_text for fragment in fragments)
    assert "[ROUTE CONTINUITY DEGRADED]" in spoken
    assert "Load compensation: suspended." in spoken


def test_speech_rules_compile_into_stream_with_original_source_spans(tmp_path: Path) -> None:
    service = _service(tmp_path)
    document = ReaderLibrary(service.repository).create_plain_text_document(
        title="Rules",
        text="API secret.",
        language_hint="en",
    )
    rule_set = service.create_rule_set(
        name="Global",
        description="",
        scope=RuleScope.GLOBAL,
    )
    service.create_rule(
        rule_set_id=rule_set.id,
        name="Expand API",
        stage=RuleStage.PRONUNCIATION,
        rule_type=RuleType.LITERAL_REPLACE,
        pattern="API",
        replacement="A P I",
    )
    service.create_rule(
        rule_set_id=rule_set.id,
        name="Skip secret",
        stage=RuleStage.CLEANUP,
        rule_type=RuleType.SKIP,
        pattern="secret",
        replacement="",
    )
    compiler = ReaderSpeechCompiler(
        TextNormalizer(),
        SentenceSegmenter(),
        ChunkPlanner(),
        rule_engine=service.rule_engine(),
        rules=service.ordered_rules(()),
        rule_context=RuleContext(language="en", document_id=document.id),
    )

    window = ReaderStreamWindowBuilder(service, compiler).build(
        document.id,
        block_ordinal=0,
        character_offset_utf16=0,
        block_id=None,
        content_revision=1,
        max_blocks=64,
        max_source_characters=32_000,
        rules_version=service.repository.get_rules_version(),
    )

    assert window.fragments[0].spoken_text == "A P I."
    assert window.fragments[0].source_spans[0].start_offset == 0
    assert window.fragments[0].source_spans[0].end_offset == len("API secret.")
    assert window.rules_version > 1


def test_content_lease_rejects_mutation_until_all_streams_release(tmp_path: Path) -> None:
    service = _service(tmp_path)
    document = ReaderLibrary(service.repository).create_plain_text_document(
        title="Locked",
        text="Original.",
    )

    with service.content_lease(document.id, "stream-one"):
        with service.content_lease(document.id, "stream-two"):
            assert service.content_leases.active_lease_count() == 2
            with pytest.raises(ReaderDocumentLockedError):
                with service.content_mutation(document.id):
                    pass
        assert service.content_leases.is_locked(document.id) is True
    assert service.content_leases.is_locked(document.id) is False
    with service.content_mutation(document.id):
        updated, _ = service.repository.append_text(
            document.id,
            "Now allowed.",
            expected_row_version=document.row_version,
        )
    assert updated.total_blocks == 2


def test_reader_websocket_pairs_marks_and_pcm_with_utf16_source_spans(
    tmp_path: Path,
) -> None:
    client, headers = _api_bundle(tmp_path)
    document = _api_document(client, headers, text="Læs 😀 højt.")

    with client.websocket_connect("/v1/reader/stream", headers=headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "document_id": document["id"],
                    "cursor": {"block_ordinal": 0, "character_offset": 0},
                },
            }
        )
        started = websocket.receive_json()
        assert started["type"] == "started"
        assert started["source_offset_encoding"] == "utf-16"
        assert started["sample_format"] == "pcm16le"

        pending_mark = None
        chunks = 0
        done = None
        for _ in range(256):
            message_type, payload = _next_message(websocket)
            if message_type == "json" and payload["type"] == "mark":
                assert pending_mark is None
                pending_mark = payload
                assert payload["stream_id"] == started["stream_id"]
                assert payload["document_id"] == document["id"]
                assert payload["source_spans"][0]["end_offset"] == 12
                continue
            if message_type == "bytes":
                assert pending_mark is not None
                assert len(payload) == pending_mark["pcm_byte_count"]
                pending_mark = None
                chunks += 1
                continue
            if message_type == "json" and payload["type"] == "done":
                done = payload
                websocket.send_json(
                    {"type": "release", "stream_id": started["stream_id"]}
                )
                break

        assert pending_mark is None
        assert chunks > 0
        assert done is not None
        assert done["document_complete"] is True
        assert done["next_window_available"] is False
        assert done["chunks_sent"] == chunks


def test_reader_websocket_continues_by_stable_cursor_without_loading_all_blocks(
    tmp_path: Path,
) -> None:
    client, headers = _api_bundle(tmp_path)
    document = _api_document(client, headers, text="One.\n\nTwo.\n\nThree.")

    with client.websocket_connect("/v1/reader/stream", headers=headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "document_id": document["id"],
                    "cursor": {"block_ordinal": 0, "character_offset": 0},
                    "window": {"max_blocks": 1, "max_source_characters": 100},
                },
            }
        )
        started = websocket.receive_json()
        done = None
        for _ in range(128):
            message_type, payload = _next_message(websocket)
            if message_type == "json" and payload["type"] == "done":
                done = payload
                websocket.send_json(
                    {"type": "release", "stream_id": started["stream_id"]}
                )
                break

        assert done is not None
        assert done["document_complete"] is False
        assert done["next_window_available"] is True
        assert done["cursor"]["block_ordinal"] == 1
        assert done["cursor"]["character_offset"] == 0


def test_reader_websocket_resumes_from_the_end_of_a_block(tmp_path: Path) -> None:
    client, headers = _api_bundle(tmp_path)
    document = _api_document(client, headers, text="Finished block.\n\nNext block.")
    blocks = client.get(
        f"/v1/reader/documents/{document['id']}/blocks",
        headers=headers,
    ).json()["blocks"]
    first_block = blocks[0]

    with client.websocket_connect("/v1/reader/stream", headers=headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "document_id": document["id"],
                    "cursor": {
                        "block_id": first_block["id"],
                        "block_ordinal": first_block["ordinal"],
                        "character_offset": first_block["character_count"],
                        "content_revision": document["content_revision"],
                    },
                },
            }
        )
        started = websocket.receive_json()
        assert started["type"] == "started"
        assert started["cursor"]["block_id"] == blocks[1]["id"]
        assert started["cursor"]["block_ordinal"] == 1
        assert started["cursor"]["character_offset"] == 0

        done = None
        for _ in range(128):
            message_type, payload = _next_message(websocket)
            if message_type == "json" and payload["type"] == "done":
                done = payload
                websocket.send_json(
                    {"type": "release", "stream_id": started["stream_id"]}
                )
                break

        assert done is not None
        assert done["document_complete"] is True


def test_reader_websocket_holds_content_lease_until_release(tmp_path: Path) -> None:
    client, headers = _api_bundle(tmp_path)
    document = _api_document(client, headers, text="Locked during playback.")

    with client.websocket_connect("/v1/reader/stream", headers=headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "document_id": document["id"],
                    "cursor": {"block_ordinal": 0, "character_offset": 0},
                },
            }
        )
        started = websocket.receive_json()
        locked = client.post(
            f"/v1/reader/documents/{document['id']}/append",
            headers=headers,
            json={"expected_row_version": 1, "text": "Wait."},
        )
        websocket.send_json({"type": "cancel", "stream_id": started["stream_id"]})

    allowed = client.post(
        f"/v1/reader/documents/{document['id']}/append",
        headers=headers,
        json={"expected_row_version": 1, "text": "Now."},
    )
    streaming = client.get("/v1/health").json()["streaming"]

    assert locked.status_code == 409
    assert locked.json()["error"]["type"] == "reader_document_locked"
    assert allowed.status_code == 200
    assert streaming["active_streams"] == 0
    assert streaming["cancelled_streams"] == 1
    assert streaming["failed_streams"] == 0


def test_reader_websocket_requires_authentication(tmp_path: Path) -> None:
    client, headers = _api_bundle(tmp_path)
    document = _api_document(client, headers, text="Private.")

    with client.websocket_connect("/v1/reader/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "document_id": document["id"],
                    "cursor": {"block_ordinal": 0, "character_offset": 0},
                },
            }
        )
        payload = websocket.receive_json()

    assert payload["type"] == "error"
    assert payload["error"]["type"] == "unauthorized"


def test_reader_websocket_returns_a_typed_error_for_invalid_utf16_cursor(
    tmp_path: Path,
) -> None:
    client, headers = _api_bundle(tmp_path)
    document = _api_document(client, headers, text="A\U0001f600B")

    with client.websocket_connect("/v1/reader/stream", headers=headers) as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "document_id": document["id"],
                    "cursor": {"block_ordinal": 0, "character_offset": 2},
                },
            }
        )
        payload = websocket.receive_json()

    assert payload["type"] == "error"
    assert payload["error"]["type"] == "reader_invalid_cursor"
