"""Transactional managed imports composed from the existing scoped M1 operations.

Preparation stores bounded chapter fingerprints and part metadata, never chapter
bodies. Each delivery commits creation (if needed), append, receipt, assignment
and progress together. Leases are acquired by the application before calling the
write; the target is checked again inside the transaction to fence races.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict

from ..agent_access import AgentConflictError, AgentUnauthorizedError, ChapterDelivery, bounded_text
from ..agent_parts import PartPolicy, normalized_wrapper, plan_parts
from ..errors import ReaderConflictError, ReaderValidationError
from ..models import utc_now

MAX_FOLDER_IMPORT_PLANS = 256


class AgentImportsMixin:
    def preview_import(
        self,
        credential: str,
        *,
        title: str,
        intro: str,
        chapters: tuple[ChapterDelivery, ...],
        retry_key: str,
        policy: PartPolicy,
    ) -> dict[str, object]:
        bounded_text(retry_key, "retry_key", 200)
        parts = plan_parts(title, intro, chapters, policy)
        wrapper = normalized_wrapper(title, intro)
        story_key = chapters[0].story_key
        manifest = [
            {
                "chapter_key": chapter.chapter_key,
                "retry_key": chapter.retry_key,
                "fingerprint": chapter.fingerprint(),
            }
            for chapter in chapters
        ]
        payload_hash = _hash(
            {"title": title, "wrapper": wrapper, "manifest": manifest, "policy": asdict(policy)}
        )
        with self._scope(credential, "create") as (bound, connection, grant):
            _permission(grant, "deliver")
            _permission(grant, "list")
            previous = connection.execute(
                "SELECT * FROM reader_agent_import_plans WHERE folder_id = ? AND retry_key = ?",
                (grant.folder_id, retry_key),
            ).fetchone()
            if previous is not None:
                _story_scope(connection, grant.folder_id, previous["story_key"])
                if previous["payload_hash"] != payload_hash:
                    raise AgentConflictError("Import preparation identity has a different payload.")
                return _preview(previous, "already_prepared")
            count = connection.execute(
                "SELECT COUNT(*) FROM reader_agent_import_plans WHERE folder_id = ?",
                (grant.folder_id,),
            ).fetchone()[0]
            if count >= MAX_FOLDER_IMPORT_PLANS:
                raise ReaderValidationError("The folder has reached its 256 managed import plans")
            connection.execute(
                "INSERT OR IGNORE INTO reader_agent_stories VALUES (?, ?, 0)",
                (grant.folder_id, story_key),
            )
            _story_scope(connection, grant.folder_id, story_key)
            for chapter in chapters:
                _no_duplicate(connection, grant.folder_id, chapter)
            base_version = _story_version(connection, grant.folder_id, story_key)
            maximum = connection.execute(
                "SELECT COALESCE(MAX(part_number), 0) FROM reader_agent_import_parts "
                "WHERE folder_id = ? AND story_key = ?",
                (grant.folder_id, story_key),
            ).fetchone()[0]
            legacy_count = connection.execute(
                "SELECT COUNT(DISTINCT chapter.document_id) FROM reader_agent_chapters AS chapter "
                "JOIN reader_documents AS document ON document.id = chapter.document_id "
                "WHERE document.folder_id = ? AND document.deleted_at IS NULL "
                "AND chapter.story_key = ? AND NOT EXISTS "
                "(SELECT 1 FROM reader_agent_import_parts AS part "
                "WHERE part.document_id = document.id)",
                (grant.folder_id, story_key),
            ).fetchone()[0]
            start = max(int(maximum), int(legacy_count))
            if start + len(parts) > 999_999:
                raise ReaderValidationError("The story has reached its managed part-number limit")
            planned_parts = []
            for part in parts:
                values = asdict(part)
                values["number"] = start + part.number
                values["title"] = f"{title} - Part {start + part.number:02d}"
                planned_parts.append(values)
            identifier = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO reader_agent_import_plans VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    identifier,
                    grant.folder_id,
                    story_key,
                    retry_key,
                    payload_hash,
                    wrapper,
                    title,
                    _json(asdict(policy)),
                    _json(manifest),
                    _json(planned_parts),
                    base_version,
                    utc_now().isoformat(),
                ),
            )
            return _preview(_plan(connection, grant.folder_id, identifier), "prepared")

    def import_target(self, credential: str, plan_id: str, chapter_key: str) -> str | None:
        bounded_text(plan_id, "plan_id", 100)
        bounded_text(chapter_key, "chapter_key", 200)
        with self._scope(credential, "deliver") as (_, connection, grant):
            _permission(grant, "create")
            _permission(grant, "list")
            plan = _plan(connection, grant.folder_id, plan_id)
            _story_scope(connection, grant.folder_id, plan["story_key"])
            assignment = connection.execute(
                "SELECT chapter.document_id FROM reader_agent_import_assignments AS assignment "
                "JOIN reader_agent_chapters AS chapter ON chapter.id = assignment.receipt_id "
                "WHERE assignment.plan_id = ? AND assignment.chapter_key = ?",
                (plan_id, chapter_key),
            ).fetchone()
            if assignment is not None:
                return str(assignment["document_id"])
            _, part_index, _ = _manifest_target(plan, chapter_key)
            part = connection.execute(
                "SELECT document_id FROM reader_agent_import_parts "
                "WHERE plan_id = ? AND plan_part_number = ?",
                (plan_id, part_index),
            ).fetchone()
            return None if part is None else str(part["document_id"])

    def deliver_import_chapter(
        self,
        credential: str,
        *,
        plan_id: str,
        delivery: ChapterDelivery,
        lease_document_id: str | None,
    ) -> dict[str, object]:
        bounded_text(plan_id, "plan_id", 100)
        with self._scope(credential, "deliver") as (bound, connection, grant):
            _permission(grant, "create")
            _permission(grant, "list")
            plan = _plan(connection, grant.folder_id, plan_id)
            _story_scope(connection, grant.folder_id, plan["story_key"])
            index, part_index, part_spec = _manifest_target(plan, delivery.chapter_key)
            manifest = json.loads(plan["manifest_json"])
            entry = manifest[index]
            if (
                delivery.story_key != plan["story_key"]
                or delivery.fingerprint() != entry["fingerprint"]
                or delivery.retry_key != entry["retry_key"]
            ):
                raise AgentConflictError("Chapter payload does not match the prepared import.")
            previous = connection.execute(
                "SELECT chapter.* FROM reader_agent_import_assignments AS assignment "
                "JOIN reader_agent_chapters AS chapter ON chapter.id = assignment.receipt_id "
                "WHERE assignment.plan_id = ? AND assignment.chapter_index = ?",
                (plan_id, index),
            ).fetchone()
            if previous is not None:
                return _delivery_result(plan, previous, part_spec["number"], "already_imported")
            if index < plan["next_index"]:
                # A physically removed receipt/part cannot become a fresh import.
                raise AgentUnauthorizedError()
            if index != plan["next_index"]:
                raise AgentConflictError("Import chapters must follow the prepared order.")
            if _story_version(connection, grant.folder_id, plan["story_key"]) != (
                plan["base_story_version"] + index
            ):
                raise AgentConflictError("The story changed after import preparation.")
            _no_duplicate(connection, grant.folder_id, delivery)
            part = connection.execute(
                "SELECT * FROM reader_agent_import_parts "
                "WHERE plan_id = ? AND plan_part_number = ?",
                (plan_id, part_index),
            ).fetchone()
            # Nested M1 calls share the private transaction-bound repository,
            # repeat authorization and never open/commit a second connection.
            from .agent_repository import SqliteReaderAgentRepository

            nested = SqliteReaderAgentRepository(bound)
            if part is None:
                if lease_document_id is not None:
                    raise AgentConflictError("The prepared part target changed before delivery.")
                document = nested.create_article(
                    credential,
                    title=part_spec["title"],
                    text=plan["wrapper"],
                )
            else:
                if lease_document_id != part["document_id"]:
                    raise AgentConflictError("The prepared part target changed before delivery.")
                document = bound.get_document(part["document_id"])
                if document.row_version != part["last_row_version"]:
                    raise ReaderConflictError(
                        document.id,
                        expected=part["last_row_version"],
                        actual=document.row_version,
                    )
            receipt = nested.deliver_chapter(
                credential,
                document.id,
                delivery,
                expected_row_version=document.row_version,
            )
            document = bound.get_document(document.id)
            self._validate_part_after_append(connection, document, plan, part_spec, index)
            if part is None:
                connection.execute(
                    "INSERT INTO reader_agent_import_parts VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        grant.folder_id,
                        plan["story_key"],
                        part_spec["number"],
                        plan_id,
                        part_index,
                        document.id,
                        document.row_version,
                    ),
                )
            else:
                connection.execute(
                    "UPDATE reader_agent_import_parts SET last_row_version = ? "
                    "WHERE plan_id = ? AND plan_part_number = ?",
                    (document.row_version, plan_id, part_index),
                )
            connection.execute(
                "INSERT INTO reader_agent_import_assignments VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    grant.folder_id,
                    plan["story_key"],
                    delivery.chapter_key,
                    plan_id,
                    index,
                    receipt.id,
                    part_spec["number"],
                ),
            )
            connection.execute(
                "UPDATE reader_agent_import_plans SET next_index = next_index + 1 WHERE id = ?",
                (plan_id,),
            )
            updated = _plan(connection, grant.folder_id, plan_id)
            return _delivery_result(updated, asdict(receipt), part_spec["number"], receipt.outcome)

    @staticmethod
    def _validate_part_after_append(connection, document, plan, part_spec, chapter_index):
        policy = PartPolicy(**json.loads(plan["policy_json"]))
        codepoints = document.total_characters + max(0, document.total_blocks - 1) * 2
        if codepoints > policy.max_characters or document.total_blocks > policy.max_blocks:
            raise AgentConflictError("The actual part exceeds its prepared size policy.")
        digest = hashlib.sha256()
        utf16 = 0
        for index, row in enumerate(
            connection.execute(
                "SELECT text FROM reader_blocks WHERE document_id = ? ORDER BY ordinal",
                (document.id,),
            )
        ):
            text = ("\n\n" if index else "") + row["text"]
            utf16 += len(text.encode("utf-16-le")) // 2
            digest.update(text.encode("utf-8"))
        if utf16 > policy.max_characters:
            raise AgentConflictError("The actual part exceeds its UTF-16 size policy.")
        manifest = json.loads(plan["manifest_json"])
        if manifest[chapter_index]["chapter_key"] == part_spec["chapter_keys"][-1] and (
            codepoints != part_spec["codepoints"]
            or utf16 != part_spec["utf16_units"]
            or document.total_blocks != part_spec["blocks"]
            or digest.hexdigest() != part_spec["text_sha256"]
        ):
            raise AgentConflictError("The actual completed part differs from its preview.")

    def story_status(
        self,
        credential: str,
        *,
        story_key: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, object]:
        bounded_text(story_key, "story_key", 200)
        if (
            type(offset) is not int
            or not 0 <= offset <= 2**31 - 1
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise ReaderValidationError("Invalid story status page")
        with self._scope(credential, "chapters") as (_, connection, grant):
            _permission(grant, "list")
            _story_scope(connection, grant.folder_id, story_key)
            rows = connection.execute(
                "SELECT chapter.*, document.title AS article_title, "
                "document.row_version AS article_row_version, "
                "document.content_revision AS article_content_revision, "
                "assignment.part_number AS managed_part_number "
                "FROM reader_agent_chapters AS chapter "
                "JOIN reader_documents AS document ON document.id = chapter.document_id "
                "LEFT JOIN reader_agent_import_assignments AS assignment "
                "ON assignment.receipt_id = chapter.id "
                "WHERE document.folder_id = ? AND document.deleted_at IS NULL "
                "AND chapter.story_key = ? ORDER BY chapter.imported_at, chapter.id "
                "LIMIT ? OFFSET ?",
                (grant.folder_id, story_key, limit + 1, offset),
            ).fetchall()
            items = []
            discontinuities = []
            previous_order = None
            if offset:
                preceding = connection.execute(
                    "SELECT chapter.order_index FROM reader_agent_chapters AS chapter "
                    "JOIN reader_documents AS document ON document.id = chapter.document_id "
                    "WHERE document.folder_id = ? AND document.deleted_at IS NULL "
                    "AND chapter.story_key = ? ORDER BY chapter.imported_at, chapter.id "
                    "LIMIT 1 OFFSET ?",
                    (grant.folder_id, story_key, offset - 1),
                ).fetchone()
                previous_order = None if preceding is None else preceding["order_index"]
            for row in rows[:limit]:
                order = row["order_index"]
                if previous_order is not None and order is not None and order != previous_order + 1:
                    discontinuities.append(
                        {"previous_order_index": previous_order, "order_index": order}
                    )
                previous_order = order
                items.append(
                    {
                        "receipt": _receipt_fields(row),
                        "article": {
                            "id": row["document_id"],
                            "title": row["article_title"],
                            "row_version": row["article_row_version"],
                            "content_revision": row["article_content_revision"],
                        },
                        "managed": row["managed_part_number"] is not None,
                        "part_number": row["managed_part_number"],
                    }
                )
            return {
                "story_key": story_key,
                "story_version": _story_version(connection, grant.folder_id, story_key),
                "items": items,
                "next_offset": offset + limit if len(rows) > limit else None,
                "append_only_receipts": True,
                "current_text_verified": False,
                "discontinuities": discontinuities,
            }


def _permission(grant, operation):
    if operation not in grant.operations:
        raise AgentUnauthorizedError()


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _plan(connection, folder_id, plan_id):
    row = connection.execute(
        "SELECT * FROM reader_agent_import_plans WHERE id = ? AND folder_id = ?",
        (plan_id, folder_id),
    ).fetchone()
    if row is None:
        raise AgentUnauthorizedError()
    return row


def _story_scope(connection, folder_id, story_key):
    hidden = connection.execute(
        "SELECT 1 FROM reader_agent_import_parts AS part "
        "JOIN reader_documents AS document ON document.id = part.document_id "
        "WHERE part.folder_id = ? AND part.story_key = ? "
        "AND (document.folder_id IS NULL OR document.folder_id != ? "
        "OR document.deleted_at IS NOT NULL) LIMIT 1",
        (folder_id, story_key, folder_id),
    ).fetchone()
    if hidden is not None:
        raise AgentUnauthorizedError()
    missing = connection.execute(
        "SELECT 1 FROM reader_agent_import_plans AS plan "
        "WHERE plan.folder_id = ? AND plan.story_key = ? AND plan.next_index != "
        "(SELECT COUNT(*) FROM reader_agent_import_assignments AS assignment "
        "WHERE assignment.plan_id = plan.id) LIMIT 1",
        (folder_id, story_key),
    ).fetchone()
    if missing is not None:
        # Physical owner deletion can cascade part/receipt/assignment rows.
        # Durable plan progress remains the tombstone: never recreate a partial
        # replacement or import those identities into a different fresh plan.
        raise AgentUnauthorizedError()


def _story_version(connection, folder_id, story_key):
    row = connection.execute(
        "SELECT version FROM reader_agent_stories WHERE folder_id = ? AND story_key = ?",
        (folder_id, story_key),
    ).fetchone()
    return 0 if row is None else row["version"]


def _no_duplicate(connection, folder_id, chapter):
    existing = connection.execute(
        "SELECT 1 FROM reader_agent_chapters AS chapter "
        "JOIN reader_documents AS document ON document.id = chapter.document_id "
        "WHERE document.folder_id = ? "
        "AND chapter.story_key = ? AND chapter.chapter_key = ? LIMIT 1",
        (folder_id, chapter.story_key, chapter.chapter_key),
    ).fetchone()
    if existing is not None:
        raise AgentConflictError("This chapter already has a delivery in the story workspace.")


def _manifest_target(plan, chapter_key):
    manifest = json.loads(plan["manifest_json"])
    index = next((i for i, item in enumerate(manifest) if item["chapter_key"] == chapter_key), None)
    if index is None:
        raise AgentConflictError("Chapter identity is not in the prepared import.")
    for part_index, part in enumerate(json.loads(plan["parts_json"]), start=1):
        if chapter_key in part["chapter_keys"]:
            return index, part_index, part
    raise AgentConflictError("Chapter assignment is missing from the prepared import.")


def _preview(plan, outcome):
    return {
        "plan_id": plan["id"],
        "story_key": plan["story_key"],
        "base_story_version": plan["base_story_version"],
        "next_index": plan["next_index"],
        "chapter_count": len(json.loads(plan["manifest_json"])),
        "policy": json.loads(plan["policy_json"]),
        "parts": json.loads(plan["parts_json"]),
        "outcome": outcome,
    }


def _receipt_fields(receipt):
    fields = (
        "id",
        "document_id",
        "story_key",
        "chapter_key",
        "source_url",
        "title",
        "order_label",
        "order_index",
        "order_warning",
        "imported_at",
        "result_row_version",
        "result_content_revision",
    )
    values = {key: receipt[key] for key in fields}
    if hasattr(values["imported_at"], "isoformat"):
        values["imported_at"] = values["imported_at"].isoformat()
    return values


def _delivery_result(plan, receipt, part_number, outcome):
    next_index = plan["next_index"]
    count = len(json.loads(plan["manifest_json"]))
    return {
        "plan_id": plan["id"],
        "story_key": plan["story_key"],
        "chapter_key": receipt["chapter_key"],
        "document_id": receipt["document_id"],
        "part_number": part_number,
        "next_index": next_index,
        "chapter_count": count,
        "complete": next_index == count,
        "receipt": _receipt_fields(receipt) | {"outcome": outcome},
        "outcome": outcome,
    }
