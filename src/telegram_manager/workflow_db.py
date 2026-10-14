"""Persistent one-item submission workflow and publication bookkeeping."""

from contextlib import closing
import json
import secrets

from telegram_manager.catalog_db import _duplicate_content, _now
from telegram_manager.database import connect
from telegram_manager.validation import (
    DuplicateContentError, clean_label, label_key, payload_identity,
)


class WorkflowDB:
    def __init__(self, path) -> None:
        self.path = path

    @staticmethod
    def _draft(row) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        result["source_payload"] = json.loads(result["source_payload"])
        return result

    def active(self, user_id: int) -> dict | None:
        with closing(connect(self.path)) as db:
            return self._draft(db.execute(
                "SELECT * FROM submission_drafts WHERE telegram_user_id = ? "
                "AND state IN ('draft', 'ready') ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone())

    def start(self, user_id: int, source_chat_id: int, source_message_id: int,
              payload: dict) -> dict:
        if source_chat_id <= 0 or source_message_id <= 0:
            raise ValueError("Invalid source message")
        with closing(connect(self.path)) as db, db:
            approved = db.execute(
                "SELECT 1 FROM users WHERE telegram_user_id = ? AND status = 'approved'",
                (user_id,),
            ).fetchone()
            if approved is None:
                raise PermissionError("Approval required")
            existing = db.execute(
                "SELECT id FROM submission_drafts WHERE source_chat_id = ? "
                "AND source_message_ids = ?",
                (source_chat_id, json.dumps([source_message_id])),
            ).fetchone()
            if existing is not None:
                raise ValueError("Source message was already submitted")
            db.execute(
                "UPDATE submission_drafts SET state = 'cancelled', updated_at = ? "
                "WHERE telegram_user_id = ? AND state IN ('draft', 'ready')",
                (_now(), user_id),
            )
            cursor = db.execute(
                "INSERT INTO submission_drafts "
                "(telegram_user_id, source_chat_id, source_message_ids, source_payload, "
                "step, created_at, updated_at) VALUES (?, ?, ?, ?, 'title', ?, ?)",
                (user_id, source_chat_id, json.dumps([source_message_id]),
                 json.dumps(payload, ensure_ascii=False), _now(), _now()),
            )
            return self._draft(db.execute(
                "SELECT * FROM submission_drafts WHERE id = ?", (cursor.lastrowid,)
            ).fetchone())

    def set_title(self, user_id: int, title: str) -> dict:
        title = clean_label(title, 150)
        with closing(connect(self.path)) as db, db:
            cursor = db.execute(
                "UPDATE submission_drafts SET title = ?, step = 'topic', updated_at = ? "
                "WHERE id = (SELECT id FROM submission_drafts "
                "WHERE telegram_user_id = ? AND state = 'draft' "
                "AND step IN ('title', 'topic') "
                "ORDER BY id DESC LIMIT 1)", (title, _now(), user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("No draft can accept a title")
            return self._draft(db.execute(
                "SELECT * FROM submission_drafts WHERE telegram_user_id = ? "
                "AND state = 'draft' ORDER BY id DESC LIMIT 1", (user_id,)
            ).fetchone())

    def set_topic(self, user_id: int, draft_id: int, project_id: int,
                  destination_id: int) -> dict:
        with closing(connect(self.path)) as db, db:
            cursor = db.execute(
                "UPDATE submission_drafts SET project_id = ?, destination_id = ?, "
                "step = 'review', state = 'ready', updated_at = ? "
                "WHERE id = ? AND telegram_user_id = ? AND state = 'draft' "
                "AND step = 'topic' AND title IS NOT NULL",
                (project_id, destination_id, _now(), draft_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Draft is no longer waiting for a topic")
            return self._draft(db.execute(
                "SELECT * FROM submission_drafts WHERE id = ?", (draft_id,)
            ).fetchone())

    def cancel(self, user_id: int) -> bool:
        with closing(connect(self.path)) as db, db:
            cursor = db.execute(
                "UPDATE submission_drafts SET state = 'cancelled', updated_at = ? "
                "WHERE telegram_user_id = ? AND state IN ('draft', 'ready')",
                (_now(), user_id),
            )
            return cursor.rowcount > 0

    def return_ready_to_topic(self, user_id: int, draft_id: int) -> None:
        """Allow a new title when a duplicate appeared after preview."""
        with closing(connect(self.path)) as db, db:
            cursor = db.execute(
                "UPDATE submission_drafts SET project_id = NULL, destination_id = NULL, "
                "step = 'topic', state = 'draft', updated_at = ? "
                "WHERE id = ? AND telegram_user_id = ? AND state = 'ready'",
                (_now(), draft_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Ready draft not found")

    def begin_publish(self, user_id: int, draft_id: int) -> tuple[dict, str]:
        with closing(connect(self.path)) as db:
            db.execute("BEGIN IMMEDIATE")
            draft = db.execute(
                "SELECT * FROM submission_drafts WHERE id = ? AND telegram_user_id = ? "
                "AND state = 'ready'", (draft_id, user_id),
            ).fetchone()
            approved = db.execute(
                "SELECT 1 FROM users WHERE telegram_user_id = ? AND status = 'approved'",
                (user_id,),
            ).fetchone()
            if draft is None or approved is None:
                db.rollback()
                raise PermissionError("Draft is unavailable or user is not approved")
            topic = db.execute(
                "SELECT chat_id, topic_id FROM destinations WHERE id = ? "
                "AND active = 1 AND deleted_from_group = 0",
                (draft["destination_id"],),
            ).fetchone()
            if topic is None:
                db.rollback()
                raise ValueError("Destination is no longer available")
            payload = json.loads(draft["source_payload"])
            duplicate = _duplicate_content(
                db, topic["chat_id"], topic["topic_id"], draft["title"], payload
            )
            if duplicate is not None:
                db.rollback()
                raise duplicate
            identity = payload_identity(payload)
            for pending in db.execute(
                "SELECT d.title, d.source_payload, t.chat_id, t.topic_id, "
                "j.reserved_content_id FROM submission_drafts d "
                "JOIN destinations t ON t.id = d.destination_id "
                "JOIN publication_jobs j ON j.draft_id = d.id "
                "WHERE d.id != ? AND t.chat_id = ? "
                "AND (d.state = 'publishing' OR "
                "(d.state = 'failed' AND j.sent_message_ids != '[]'))",
                (draft_id, topic["chat_id"]),
            ):
                if pending["topic_id"] == topic["topic_id"] and label_key(pending["title"]) == label_key(draft["title"]):
                    db.rollback()
                    raise DuplicateContentError("pending", pending["reserved_content_id"])
                if identity is not None and identity == payload_identity(json.loads(pending["source_payload"])):
                    db.rollback()
                    raise DuplicateContentError("pending", pending["reserved_content_id"])
            while True:
                content_id = "CNT_" + secrets.token_hex(5).upper()
                occupied = db.execute(
                    "SELECT 1 FROM content_items WHERE id = ? UNION "
                    "SELECT 1 FROM publication_jobs WHERE reserved_content_id = ?",
                    (content_id, content_id),
                ).fetchone()
                if occupied is None:
                    break
            db.execute(
                "INSERT INTO publication_jobs "
                "(draft_id, reserved_content_id, state, attempt_count, updated_at) "
                "VALUES (?, ?, 'publishing', 1, ?)",
                (draft_id, content_id, _now()),
            )
            db.execute(
                "UPDATE submission_drafts SET state = 'publishing', updated_at = ? "
                "WHERE id = ?", (_now(), draft_id),
            )
            db.commit()
            return self._draft(draft), content_id

    def record_sent(self, draft_id: int, role: str, message_id: int) -> None:
        if role not in ("summary", "attachment", "text") or message_id <= 0:
            raise ValueError("Invalid published message")
        with closing(connect(self.path)) as db, db:
            job = db.execute(
                "SELECT sent_message_ids FROM publication_jobs WHERE draft_id = ? "
                "AND state = 'publishing'", (draft_id,),
            ).fetchone()
            if job is None:
                raise ValueError("Publication job is unavailable")
            sent = json.loads(job["sent_message_ids"])
            sent.append({"role": role, "message_id": message_id})
            db.execute(
                "UPDATE publication_jobs SET sent_message_ids = ?, updated_at = ? "
                "WHERE draft_id = ?", (json.dumps(sent), _now(), draft_id),
            )

    def sent(self, draft_id: int) -> list[dict]:
        with closing(connect(self.path)) as db:
            row = db.execute(
                "SELECT sent_message_ids FROM publication_jobs WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            return json.loads(row["sent_message_ids"]) if row else []

    def finish(self, draft_id: int) -> None:
        with closing(connect(self.path)) as db, db:
            db.execute(
                "UPDATE publication_jobs SET state = 'indexed', updated_at = ? "
                "WHERE draft_id = ? AND state = 'publishing'", (_now(), draft_id),
            )
            db.execute(
                "UPDATE submission_drafts SET state = 'completed', updated_at = ? "
                "WHERE id = ? AND state = 'publishing'", (_now(), draft_id),
            )

    def needs_review(self, draft_id: int, reason: str) -> None:
        with closing(connect(self.path)) as db, db:
            db.execute(
                "UPDATE publication_jobs SET state = 'needs_review', last_error = ?, "
                "updated_at = ? WHERE draft_id = ? AND state = 'publishing'",
                (reason[:500], _now(), draft_id),
            )
            db.execute(
                "UPDATE submission_drafts SET state = 'failed', updated_at = ? "
                "WHERE id = ? AND state = 'publishing'", (_now(), draft_id),
            )

    def reset_invalid_topic(self, draft_id: int) -> None:
        """Return a draft to topic selection if no group message was sent."""
        with closing(connect(self.path)) as db, db:
            job = db.execute(
                "SELECT state, sent_message_ids FROM publication_jobs WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            if job is None or job["state"] != "publishing" or json.loads(job["sent_message_ids"]):
                raise ValueError("Publication may already have sent messages")
            db.execute("DELETE FROM publication_jobs WHERE draft_id = ?", (draft_id,))
            db.execute(
                "UPDATE submission_drafts SET project_id = NULL, destination_id = NULL, "
                "step = 'topic', state = 'draft', updated_at = ? "
                "WHERE id = ? AND state = 'publishing'",
                (_now(), draft_id),
            )
