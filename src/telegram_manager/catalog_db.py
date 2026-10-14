"""Database operations for approved users and organized topic content.

All user-facing reads and writes enforce owner approval here.
The Telegram layer must separately verify that the configured owner is a group
administrator before calling ``activate_owner``.
"""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
import sqlite3

from telegram_manager.database import connect, initialize
from telegram_manager.validation import (
    DuplicateContentError, clean_label, label_key, payload_identity,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duplicate_content(connection: sqlite3.Connection, chat_id: int, topic_id: int,
                       title: str, payload: dict) -> DuplicateContentError | None:
    """Find a published item with the same topic title or identical payload."""
    identity = payload_identity(payload)
    seen: set[str] = set()
    for row in connection.execute(
        "SELECT ci.id, ci.title, ci.original_text, pm.topic_id, "
        "a.media_type, a.file_id, a.file_unique_id "
        "FROM content_items ci JOIN published_messages pm ON pm.content_id = ci.id "
        "LEFT JOIN attachments a ON a.content_id = ci.id "
        "WHERE ci.status IN ('published', 'archived') AND pm.chat_id = ?",
        (chat_id,),
    ):
        if row["id"] not in seen:
            seen.add(row["id"])
            if row["topic_id"] == topic_id and label_key(row["title"]) == label_key(title):
                return DuplicateContentError("title", row["id"])
        existing = payload_identity({
            "media_type": row["media_type"] or "text",
            "file_unique_id": row["file_unique_id"],
            "file_id": row["file_id"],
            "text": row["original_text"],
        })
        if identity is not None and identity == existing:
            return DuplicateContentError("content", row["id"])
    return None


@dataclass(frozen=True)
class AttachmentInput:
    media_type: str
    file_id: str
    filename: str | None = None
    file_unique_id: str | None = None


@dataclass(frozen=True)
class PublishedMessageInput:
    chat_id: int
    topic_id: int
    message_id: int
    role: str


class CatalogDB:
    def __init__(self, path: Path, owner_user_id: int) -> None:
        if owner_user_id <= 0:
            raise ValueError("owner_user_id must be positive")
        self.path = path
        self.owner_user_id = owner_user_id
        initialize(path)

    def _approved(self, connection: sqlite3.Connection, user_id: int) -> bool:
        row = connection.execute(
            "SELECT status FROM users WHERE telegram_user_id = ?", (user_id,)
        ).fetchone()
        return row is not None and row["status"] == "approved"

    def _require_owner(self, connection: sqlite3.Connection, actor_id: int) -> None:
        if actor_id != self.owner_user_id or not self._approved(connection, actor_id):
            raise PermissionError("Owner access required")

    def _has_project_permission(
        self, connection: sqlite3.Connection, user_id: int, project_id: int, action: str
    ) -> bool:
        return self._approved(connection, user_id)

    def activate_owner(self, verified_telegram_user_id: int) -> None:
        """Call only after Telegram confirms this ID is a managed-group admin."""
        if verified_telegram_user_id != self.owner_user_id:
            raise PermissionError("Configured owner ID does not match verified admin")
        with closing(connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT INTO users (telegram_user_id, status, decided_at) "
                "VALUES (?, 'approved', ?) ON CONFLICT(telegram_user_id) "
                "DO UPDATE SET status = 'approved', decided_at = excluded.decided_at",
                (verified_telegram_user_id, _now()),
            )

    def request_access(
        self, user_id: int, display_name: str | None = None,
        username: str | None = None, explanation: str | None = None,
    ) -> int:
        if user_id <= 0:
            raise ValueError("user_id must be positive")
        with closing(connect(self.path)) as connection, connection:
            current = connection.execute(
                "SELECT status FROM users WHERE telegram_user_id = ?", (user_id,)
            ).fetchone()
            if current and current["status"] in ("approved", "revoked"):
                raise PermissionError("Access request is not available for this user")
            pending = connection.execute(
                "SELECT id FROM access_requests WHERE telegram_user_id = ? "
                "AND status = 'pending' ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if pending:
                return pending["id"]
            connection.execute(
                "INSERT INTO users (telegram_user_id, display_name, username, status) "
                "VALUES (?, ?, ?, 'pending') ON CONFLICT(telegram_user_id) "
                "DO UPDATE SET display_name = excluded.display_name, "
                "username = excluded.username, status = 'pending'",
                (user_id, display_name, username),
            )
            cursor = connection.execute(
                "INSERT INTO access_requests (telegram_user_id, explanation, requested_at) "
                "VALUES (?, ?, ?)",
                (user_id, explanation, _now()),
            )
            return int(cursor.lastrowid)

    def user_status(self, user_id: int) -> str | None:
        with closing(connect(self.path)) as connection:
            row = connection.execute(
                "SELECT status FROM users WHERE telegram_user_id = ?", (user_id,)
            ).fetchone()
            return row["status"] if row else None

    def pending_requests(self, actor_id: int) -> list[dict]:
        with closing(connect(self.path)) as connection:
            self._require_owner(connection, actor_id)
            return [dict(row) for row in connection.execute(
                "SELECT ar.id, ar.telegram_user_id, ar.explanation, ar.requested_at, "
                "u.display_name, u.username FROM access_requests ar "
                "JOIN users u ON u.telegram_user_id = ar.telegram_user_id "
                "WHERE ar.status = 'pending' ORDER BY ar.requested_at, ar.id"
            )]

    def decide_access(self, actor_id: int, request_id: int, approve: bool) -> None:
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            request = connection.execute(
                "SELECT telegram_user_id FROM access_requests WHERE id = ? AND status = 'pending'",
                (request_id,),
            ).fetchone()
            if request is None:
                raise ValueError("Pending access request not found")
            status = "approved" if approve else "rejected"
            decided_at = _now()
            connection.execute(
                "UPDATE access_requests SET status = ?, decided_at = ?, decided_by = ? "
                "WHERE id = ?",
                (status, decided_at, actor_id, request_id),
            )
            connection.execute(
                "UPDATE users SET status = ?, approved_by = ?, decided_at = ? "
                "WHERE telegram_user_id = ?",
                (status, actor_id, decided_at, request["telegram_user_id"]),
            )

    def revoke_user(self, actor_id: int, user_id: int) -> None:
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            if user_id == self.owner_user_id:
                raise ValueError("The configured owner cannot be revoked here")
            cursor = connection.execute(
                "UPDATE users SET status = 'revoked', approved_by = ?, decided_at = ? "
                "WHERE telegram_user_id = ? AND status = 'approved'",
                (actor_id, _now(), user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Approved user not found")
            # Old grants must not return if this user is approved again later.
            connection.execute(
                "DELETE FROM project_permissions WHERE telegram_user_id = ?", (user_id,)
            )
            connection.execute(
                "DELETE FROM item_allowlists WHERE telegram_user_id = ?", (user_id,)
            )

    def approved_users(
        self, actor_id: int, *, limit: int = 11, offset: int = 0
    ) -> list[dict]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid user page")
        with closing(connect(self.path)) as connection:
            self._require_owner(connection, actor_id)
            return [dict(row) for row in connection.execute(
                "SELECT telegram_user_id, display_name, username "
                "FROM users WHERE status = 'approved' AND telegram_user_id != ? "
                "ORDER BY telegram_user_id LIMIT ? OFFSET ?",
                (self.owner_user_id, limit, offset),
            )]

    def approved_user(self, actor_id: int, user_id: int) -> dict | None:
        with closing(connect(self.path)) as connection:
            self._require_owner(connection, actor_id)
            row = connection.execute(
                "SELECT telegram_user_id, display_name, username FROM users "
                "WHERE telegram_user_id = ? AND status = 'approved' "
                "AND telegram_user_id != ?",
                (user_id, self.owner_user_id),
            ).fetchone()
            return dict(row) if row else None

    def create_project(self, actor_id: int, name: str, description: str = "") -> int:
        if not name.strip():
            raise ValueError("Project name is required")
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            cursor = connection.execute(
                "INSERT INTO projects (name, description) VALUES (?, ?)",
                (name.strip(), description.strip()),
            )
            return int(cursor.lastrowid)

    def create_category(self, actor_id: int, name: str) -> int:
        if not name.strip():
            raise ValueError("Category name is required")
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            cursor = connection.execute(
                "INSERT INTO categories (name) VALUES (?)", (name.strip(),)
            )
            return int(cursor.lastrowid)

    def register_destination(
        self, actor_id: int, project_id: int, chat_id: int,
        topic_id: int, name: str, is_default: bool = False,
    ) -> int:
        if topic_id <= 0:
            raise ValueError("Destination name and positive topic ID are required")
        name = clean_label(name, 100)
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            for row in connection.execute(
                "SELECT topic_id, name FROM destinations WHERE chat_id = ? "
                "AND active = 1 AND deleted_from_group = 0", (chat_id,),
            ):
                if row["topic_id"] != topic_id and label_key(row["name"]) == label_key(name):
                    raise ValueError("Topic name already registered in this group")
            if is_default:
                connection.execute(
                    "UPDATE project_destinations SET is_default = 0 WHERE project_id = ?",
                    (project_id,),
                )
            connection.execute(
                "INSERT INTO destinations (chat_id, topic_id, name) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id, topic_id) DO UPDATE SET name = excluded.name",
                (chat_id, topic_id, name.strip()),
            )
            destination_id = connection.execute(
                "SELECT id FROM destinations WHERE chat_id = ? AND topic_id = ?",
                (chat_id, topic_id),
            ).fetchone()["id"]
            connection.execute(
                "INSERT INTO project_destinations (project_id, destination_id, is_default) "
                "VALUES (?, ?, ?) ON CONFLICT(project_id, destination_id) "
                "DO UPDATE SET is_default = excluded.is_default",
                (project_id, destination_id, int(is_default)),
            )
            return destination_id

    def register_topic(
        self, actor_id: int, chat_id: int, topic_id: int, name: str
    ) -> int:
        """Register a topic as its own project/destination, or update its label."""
        if topic_id <= 0:
            raise ValueError("Topic ID and name are required")
        name = clean_label(name, 100)
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            for row in connection.execute(
                "SELECT topic_id, name FROM destinations WHERE chat_id = ? "
                "AND active = 1 AND deleted_from_group = 0", (chat_id,),
            ):
                if row["topic_id"] != topic_id and label_key(row["name"]) == label_key(name):
                    raise ValueError("Topic name already registered in this group")
            existing = connection.execute(
                "SELECT d.id, d.active, d.deleted_from_group, pd.project_id FROM destinations d "
                "JOIN project_destinations pd ON pd.destination_id = d.id "
                "WHERE d.chat_id = ? AND d.topic_id = ? LIMIT 1",
                (chat_id, topic_id),
            ).fetchone()
            if existing:
                if existing["deleted_from_group"]:
                    raise ValueError("Deleted group topic cannot be registered again")
                if existing["active"]:
                    raise ValueError("Topic is already registered")
                connection.execute(
                    "UPDATE destinations SET name = ?, active = 1 WHERE id = ?",
                    (name, existing["id"]),
                )
                project = connection.execute(
                    "SELECT name FROM projects WHERE id = ?",
                    (existing["project_id"],),
                ).fetchone()
                suffix = f" [{abs(chat_id)}:{topic_id}]"
                if project and project["name"].endswith(suffix):
                    connection.execute(
                        "UPDATE projects SET name = ? WHERE id = ?",
                        (name + suffix, existing["project_id"]),
                    )
                return existing["id"]
            project_name = f"{name} [{abs(chat_id)}:{topic_id}]"
            project = connection.execute(
                "INSERT INTO projects (name) VALUES (?)", (project_name,)
            ).lastrowid
            destination = connection.execute(
                "INSERT INTO destinations (chat_id, topic_id, name) VALUES (?, ?, ?)",
                (chat_id, topic_id, name),
            ).lastrowid
            connection.execute(
                "INSERT INTO project_destinations (project_id, destination_id, is_default) "
                "VALUES (?, ?, 1)", (project, destination),
            )
            return int(destination)

    def ensure_topic_name_available(self, actor_id: int, chat_id: int,
                                    name: str) -> str:
        name = clean_label(name, 100)
        for topic in self.admin_topics(actor_id, chat_id):
            if topic["active"] and label_key(topic["name"]) == label_key(name):
                raise ValueError("Topic name already registered in this group")
        return name

    def list_topics(self, user_id: int, chat_id: int) -> list[dict]:
        with closing(connect(self.path)) as connection:
            if not self._approved(connection, user_id):
                return []
            return [dict(row) for row in connection.execute(
                "SELECT d.id, d.name, d.chat_id, d.topic_id, pd.project_id "
                "FROM destinations d JOIN project_destinations pd "
                "ON pd.destination_id = d.id JOIN projects p ON p.id = pd.project_id "
                "WHERE d.chat_id = ? AND d.active = 1 AND p.active = 1 "
                "ORDER BY d.name, d.id", (chat_id,),
            )]

    def disable_topic(self, actor_id: int, chat_id: int, topic_id: int) -> None:
        """Hide a destination after Telegram confirms its thread is invalid."""
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            connection.execute(
                "UPDATE destinations SET active = 0 WHERE chat_id = ? AND topic_id = ?",
                (chat_id, topic_id),
            )

    def admin_topics(self, actor_id: int, chat_id: int) -> list[dict]:
        with closing(connect(self.path)) as connection:
            self._require_owner(connection, actor_id)
            return [dict(row) for row in connection.execute(
                "SELECT d.id, d.name, d.chat_id, d.topic_id, d.active, "
                "d.deleted_from_group FROM destinations d "
                "WHERE d.chat_id = ? ORDER BY d.deleted_from_group, d.name, d.id",
                (chat_id,),
            )]

    def admin_topic(self, actor_id: int, chat_id: int, destination_id: int) -> dict | None:
        return next((row for row in self.admin_topics(actor_id, chat_id)
                     if row["id"] == destination_id), None)

    def remove_topic_from_bot(self, actor_id: int, chat_id: int,
                              destination_id: int) -> None:
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            cursor = connection.execute(
                "UPDATE destinations SET active = 0 WHERE id = ? AND chat_id = ? "
                "AND active = 1 AND deleted_from_group = 0",
                (destination_id, chat_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Active topic not found")

    def mark_topic_group_deleted(self, actor_id: int, chat_id: int,
                                 destination_id: int) -> None:
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            topic = connection.execute(
                "SELECT topic_id FROM destinations WHERE id = ? AND chat_id = ? "
                "AND deleted_from_group = 0", (destination_id, chat_id),
            ).fetchone()
            if topic is None:
                raise ValueError("Topic not found")
            connection.execute(
                "UPDATE destinations SET active = 0, deleted_from_group = 1 "
                "WHERE id = ?", (destination_id,),
            )
            connection.execute(
                "UPDATE content_items SET status = 'unavailable' WHERE id IN ("
                "SELECT content_id FROM published_messages WHERE chat_id = ? "
                "AND topic_id = ?)", (chat_id, topic["topic_id"]),
            )

    def topic(self, user_id: int, chat_id: int, destination_id: int) -> dict | None:
        return next((row for row in self.list_topics(user_id, chat_id)
                     if row["id"] == destination_id), None)

    def find_duplicate_content(self, user_id: int, chat_id: int,
                               destination_id: int, title: str,
                               payload: dict) -> DuplicateContentError | None:
        with closing(connect(self.path)) as connection:
            if not self._approved(connection, user_id):
                raise PermissionError("Approval required")
            topic = connection.execute(
                "SELECT topic_id FROM destinations WHERE id = ? AND chat_id = ? "
                "AND active = 1 AND deleted_from_group = 0",
                (destination_id, chat_id),
            ).fetchone()
            if topic is None:
                raise ValueError("Topic is unavailable")
            return _duplicate_content(connection, chat_id, topic["topic_id"],
                                      title, payload)

    def category_for_media(self, media_type: str) -> int:
        with closing(connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT INTO categories (name) VALUES (?) ON CONFLICT(name) DO NOTHING",
                (media_type,),
            )
            return int(connection.execute(
                "SELECT id FROM categories WHERE name = ?", (media_type,)
            ).fetchone()["id"])

    def set_project_permission(
        self, actor_id: int, user_id: int, project_id: int,
        *, can_read: bool, can_submit: bool,
    ) -> None:
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            if user_id == self.owner_user_id:
                raise ValueError("Owner permissions are implicit")
            if not self._approved(connection, user_id):
                raise PermissionError("User must be approved first")
            connection.execute(
                "INSERT INTO project_permissions "
                "(telegram_user_id, project_id, can_read, can_submit) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(telegram_user_id, project_id) DO UPDATE SET "
                "can_read = excluded.can_read, can_submit = excluded.can_submit",
                (user_id, project_id, int(can_read), int(can_submit)),
            )

    def can_access_project(self, user_id: int, project_id: int, action: str) -> bool:
        if action not in ("read", "submit"):
            raise ValueError("action must be 'read' or 'submit'")
        with closing(connect(self.path)) as connection:
            project = connection.execute(
                "SELECT active FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            return bool(project and project["active"]) and self._has_project_permission(
                connection, user_id, project_id, action
            )

    def list_projects(self, user_id: int, action: str) -> list[dict]:
        """Return only projects the user may read or submit to."""
        if action not in ("read", "submit"):
            raise ValueError("action must be 'read' or 'submit'")
        with closing(connect(self.path)) as connection:
            if not self._approved(connection, user_id):
                return []
            rows = connection.execute(
                "SELECT id, name, description FROM projects WHERE active = 1 ORDER BY name"
            )
            return [dict(row) for row in rows]

    def list_destinations(self, user_id: int, project_id: int) -> list[dict]:
        """Return registered posting topics after a submit permission check."""
        if not self.can_access_project(user_id, project_id, "submit"):
            return []
        with closing(connect(self.path)) as connection:
            return [dict(row) for row in connection.execute(
                "SELECT d.id, d.chat_id, d.topic_id, d.name, pd.is_default "
                "FROM destinations d JOIN project_destinations pd "
                "ON pd.destination_id = d.id WHERE pd.project_id = ? "
                "AND d.active = 1 ORDER BY pd.is_default DESC, d.name",
                (project_id,),
            )]

    def list_categories(self, user_id: int) -> list[dict]:
        if not self._is_approved_user(user_id):
            return []
        with closing(connect(self.path)) as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id, name FROM categories WHERE active = 1 ORDER BY name"
            )]

    def _is_approved_user(self, user_id: int) -> bool:
        with closing(connect(self.path)) as connection:
            return self._approved(connection, user_id)

    def record_publication(
        self, user_id: int, *, content_id: str, project_id: int,
        category_id: int, destination_id: int, title: str,
        messages: Sequence[PublishedMessageInput],
        attachments: Sequence[AttachmentInput] = (),
        description: str | None = None, original_text: str | None = None,
        tags: str | None = None, previous_version_id: str | None = None,
    ) -> None:
        """Catalog content after Telegram has returned successful send results."""
        if not content_id.strip() or not messages:
            raise ValueError("Content ID, title, and published messages are required")
        title = clean_label(title, 150)
        if any(not item.file_id or not item.media_type for item in attachments):
            raise ValueError("Each attachment needs a media type and Telegram file ID")
        if any(item.role not in ("summary", "attachment", "text") for item in messages):
            raise ValueError("Invalid published message role")
        if len({(item.chat_id, item.message_id) for item in messages}) != len(messages):
            raise ValueError("Published message IDs must be unique")
        if any(item.role == "attachment" for item in messages) and not attachments:
            raise ValueError("Attachment metadata is required")
        if any(item.role == "text" for item in messages) and not (original_text or "").strip():
            raise ValueError("Original text is required")
        with closing(connect(self.path)) as connection, connection:
            if not self._has_project_permission(connection, user_id, project_id, "submit"):
                raise PermissionError("Submit access required")
            destination = connection.execute(
                "SELECT d.chat_id, d.topic_id FROM destinations d "
                "JOIN project_destinations pd ON pd.destination_id = d.id "
                "JOIN projects p ON p.id = pd.project_id "
                "WHERE pd.project_id = ? AND d.id = ? AND d.active = 1 AND p.active = 1",
                (project_id, destination_id),
            ).fetchone()
            if destination is None:
                raise ValueError("Destination is not registered for this project")
            if any(
                item.chat_id != destination["chat_id"]
                or item.topic_id != destination["topic_id"]
                or item.message_id <= 0
                for item in messages
            ):
                raise ValueError("Published message does not match destination")
            category = connection.execute(
                "SELECT id FROM categories WHERE id = ? AND active = 1", (category_id,)
            ).fetchone()
            if category is None:
                raise ValueError("Active category not found")
            if connection.execute(
                "SELECT 1 FROM content_items WHERE id = ?", (content_id,)
            ).fetchone():
                raise sqlite3.IntegrityError("Content ID already exists")
            if attachments:
                first = attachments[0]
                payload = {"media_type": first.media_type, "file_id": first.file_id,
                           "file_unique_id": first.file_unique_id}
            else:
                payload = {"media_type": "text", "text": original_text}
            duplicate = _duplicate_content(
                connection, destination["chat_id"], destination["topic_id"],
                title, payload,
            )
            if duplicate is not None:
                raise duplicate
            now = _now()
            connection.execute(
                "INSERT INTO content_items "
                "(id, project_id, category_id, submitter_user_id, title, description, "
                "tags, original_text, previous_version_id, created_at, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (content_id, project_id, category_id, user_id, title, description,
                 tags, original_text, previous_version_id, now, now),
            )
            connection.executemany(
                "INSERT INTO attachments "
                "(content_id, position, media_type, filename, file_id, file_unique_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (content_id, position, item.media_type, item.filename,
                     item.file_id, item.file_unique_id)
                    for position, item in enumerate(attachments)
                ],
            )
            connection.executemany(
                "INSERT INTO published_messages "
                "(content_id, chat_id, topic_id, message_id, role) VALUES (?, ?, ?, ?, ?)",
                [
                    (content_id, item.chat_id, item.topic_id, item.message_id, item.role)
                    for item in messages
                ],
            )
            connection.execute(
                "INSERT INTO search_documents "
                "(content_id, searchable_text, extraction_status) VALUES (?, ?, ?)",
                (content_id, original_text,
                 "pending" if attachments else "complete"),
            )

    def update_search_text(
        self, content_id: str, text: str | None, status: str, method: str | None = None
    ) -> None:
        """Internal indexing operation; never expose directly as a user command."""
        if status not in ("pending", "complete", "unsupported", "failed"):
            raise ValueError("Invalid extraction status")
        with closing(connect(self.path)) as connection, connection:
            cursor = connection.execute(
                "UPDATE search_documents SET searchable_text = ?, "
                "extraction_status = ?, extraction_method = ? WHERE content_id = ?",
                (text, status, method, content_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Content search record not found")

    def restrict_item_to(
        self, actor_id: int, content_id: str, allowed_user_ids: Sequence[int]
    ) -> None:
        """A nonempty list restricts an item; an empty list removes restriction."""
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            if connection.execute(
                "SELECT 1 FROM content_items WHERE id = ?", (content_id,)
            ).fetchone() is None:
                raise ValueError("Content item not found")
            for user_id in allowed_user_ids:
                if not self._approved(connection, user_id):
                    raise PermissionError("Allowlisted users must be approved")
            connection.execute(
                "DELETE FROM item_allowlists WHERE content_id = ?", (content_id,)
            )
            connection.executemany(
                "INSERT INTO item_allowlists (content_id, telegram_user_id) VALUES (?, ?)",
                [(content_id, user_id) for user_id in set(allowed_user_ids)],
            )

    def _readable_item(self, connection: sqlite3.Connection, user_id: int, content_id: str):
        item = connection.execute(
            "SELECT ci.*, p.name AS project_name, c.name AS category_name "
            "FROM content_items ci JOIN projects p ON p.id = ci.project_id "
            "JOIN categories c ON c.id = ci.category_id "
            "WHERE ci.id = ? AND p.active = 1 AND ci.status = 'published'",
            (content_id,),
        ).fetchone()
        if item is None or not self._has_project_permission(
            connection, user_id, item["project_id"], "read"
        ):
            return None
        if user_id != self.owner_user_id:
            restriction = connection.execute(
                "SELECT 1 FROM item_allowlists WHERE content_id = ? LIMIT 1",
                (content_id,),
            ).fetchone()
            if restriction and connection.execute(
                "SELECT 1 FROM item_allowlists WHERE content_id = ? "
                "AND telegram_user_id = ?",
                (content_id, user_id),
            ).fetchone() is None:
                return None
        return item

    def get_content(self, user_id: int, content_id: str) -> dict | None:
        """Return the record and delivery references, or nothing if inaccessible."""
        with closing(connect(self.path)) as connection:
            item = self._readable_item(connection, user_id, content_id)
            if item is None:
                return None
            result = dict(item)
            result["attachments"] = [
                dict(row) for row in connection.execute(
                    "SELECT position, media_type, filename, file_id, file_unique_id "
                    "FROM attachments WHERE content_id = ? ORDER BY position",
                    (content_id,),
                )
            ]
            result["published_messages"] = [
                dict(row) for row in connection.execute(
                    "SELECT chat_id, topic_id, message_id, role FROM published_messages "
                    "WHERE content_id = ? ORDER BY id",
                    (content_id,),
                )
            ]
            return result

    def list_content_in_topic(
        self, user_id: int, chat_id: int, destination_id: int,
        *, limit: int = 10, offset: int = 0,
    ) -> list[dict]:
        """Browse published items in an active topic with the usual read rules."""
        if not 1 <= limit <= 50 or offset < 0:
            raise ValueError("Invalid content page")
        with closing(connect(self.path)) as connection:
            if not self._approved(connection, user_id):
                return []
            destination = connection.execute(
                "SELECT d.topic_id FROM destinations d "
                "JOIN project_destinations pd ON pd.destination_id = d.id "
                "JOIN projects p ON p.id = pd.project_id "
                "WHERE d.id = ? AND d.chat_id = ? AND d.active = 1 "
                "AND d.deleted_from_group = 0 AND p.active = 1",
                (destination_id, chat_id),
            ).fetchone()
            if destination is None:
                return []
            return [dict(row) for row in connection.execute(
                "SELECT ci.id, ci.title, ci.published_at, ci.submitter_user_id, "
                "u.display_name, u.username FROM content_items ci "
                "JOIN users u ON u.telegram_user_id = ci.submitter_user_id "
                "JOIN projects p ON p.id = ci.project_id "
                "WHERE ci.status = 'published' AND p.active = 1 "
                "AND EXISTS (SELECT 1 FROM project_destinations pd "
                "WHERE pd.project_id = ci.project_id AND pd.destination_id = ?) "
                "AND EXISTS (SELECT 1 FROM published_messages pm "
                "WHERE pm.content_id = ci.id AND pm.chat_id = ? AND pm.topic_id = ?) "
                "AND (? = ? OR NOT EXISTS (SELECT 1 FROM item_allowlists ia "
                "WHERE ia.content_id = ci.id) OR EXISTS "
                "(SELECT 1 FROM item_allowlists ia WHERE ia.content_id = ci.id "
                "AND ia.telegram_user_id = ?)) "
                "ORDER BY ci.published_at DESC, ci.id DESC LIMIT ? OFFSET ?",
                (destination_id, chat_id, destination["topic_id"],
                 user_id, self.owner_user_id, user_id, limit, offset),
            )]

    def admin_search_content(self, actor_id: int, query: str,
                             limit: int = 10) -> list[dict]:
        term = query.strip().lstrip("#")
        if not term or not 1 <= limit <= 100:
            raise ValueError("Content search requires a query")
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        with closing(connect(self.path)) as connection:
            self._require_owner(connection, actor_id)
            return [dict(row) for row in connection.execute(
                "SELECT id, title, status FROM content_items "
                "WHERE id = ? OR title LIKE ? ESCAPE '\\' "
                "ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END, published_at DESC "
                "LIMIT ?", (term, pattern, term, limit),
            )]

    def admin_content(self, actor_id: int, content_id: str) -> dict | None:
        with closing(connect(self.path)) as connection:
            self._require_owner(connection, actor_id)
            item = connection.execute(
                "SELECT id, title, status FROM content_items WHERE id = ?",
                (content_id,),
            ).fetchone()
            if item is None:
                return None
            result = dict(item)
            result["published_messages"] = [dict(row) for row in connection.execute(
                "SELECT chat_id, topic_id, message_id, role FROM published_messages "
                "WHERE content_id = ? ORDER BY id", (content_id,),
            )]
            return result

    def analyze_managed_content(self, actor_id: int, chat_id: int) -> dict:
        """Summarize only content the bot recorded as published in this group."""
        with closing(connect(self.path)) as connection:
            self._require_owner(connection, actor_id)
            topics = [dict(row) for row in connection.execute(
                "SELECT id, name, topic_id, active, deleted_from_group "
                "FROM destinations WHERE chat_id = ? ORDER BY name, id",
                (chat_id,),
            )]
            items = [dict(row) for row in connection.execute(
                "SELECT ci.id, ci.title, ci.description, ci.status, "
                "c.name AS media_type, pm.topic_id "
                "FROM content_items ci JOIN categories c ON c.id = ci.category_id "
                "JOIN (SELECT DISTINCT content_id, topic_id FROM published_messages "
                "WHERE chat_id = ?) pm ON pm.content_id = ci.id "
                "ORDER BY ci.published_at DESC, ci.id",
                (chat_id,),
            )]
            return {"topics": topics, "items": items}

    def set_content_status(self, actor_id: int, content_id: str,
                           status: str) -> None:
        if status not in ("archived", "unavailable"):
            raise ValueError("Invalid content status")
        with closing(connect(self.path)) as connection, connection:
            self._require_owner(connection, actor_id)
            cursor = connection.execute(
                "UPDATE content_items SET status = ? WHERE id = ?",
                (status, content_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Content item not found")

    def search(
        self, user_id: int, query: str, limit: int = 20,
        chat_id: int | None = None,
    ) -> list[dict]:
        """Search only readable records; callers recheck via get_content on click."""
        term = query.strip()
        if term.startswith("#"):
            term = term[1:]
        if not term or not 1 <= limit <= 100:
            raise ValueError("Search requires text and a limit between 1 and 100")
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        with closing(connect(self.path)) as connection:
            if not self._approved(connection, user_id):
                return []
            rows = connection.execute(
                "SELECT ci.id, ci.title, ci.description, ci.published_at, "
                "p.name AS project_name, c.name AS category_name "
                "FROM content_items ci "
                "JOIN projects p ON p.id = ci.project_id "
                "JOIN categories c ON c.id = ci.category_id "
                "LEFT JOIN search_documents sd ON sd.content_id = ci.id "
                "WHERE p.active = 1 AND ci.status = 'published' "
                "AND (? IS NULL OR EXISTS (SELECT 1 FROM published_messages pm "
                "WHERE pm.content_id = ci.id AND pm.chat_id = ?)) "
                "AND (? = ? OR NOT EXISTS (SELECT 1 FROM item_allowlists ia "
                "WHERE ia.content_id = ci.id) OR EXISTS "
                "(SELECT 1 FROM item_allowlists ia WHERE ia.content_id = ci.id "
                "AND ia.telegram_user_id = ?)) "
                "AND (ci.id = ? OR ci.title LIKE ? ESCAPE '\\' "
                "OR ci.description LIKE ? ESCAPE '\\' "
                "OR ci.tags LIKE ? ESCAPE '\\' "
                "OR ci.original_text LIKE ? ESCAPE '\\' "
                "OR p.name LIKE ? ESCAPE '\\' "
                "OR c.name LIKE ? ESCAPE '\\' "
                "OR sd.searchable_text LIKE ? ESCAPE '\\' "
                "OR EXISTS (SELECT 1 FROM attachments a WHERE a.content_id = ci.id "
                "AND a.filename LIKE ? ESCAPE '\\')) "
                "ORDER BY CASE WHEN ci.id = ? THEN 0 WHEN ci.title = ? THEN 1 "
                "ELSE 2 END, ci.published_at DESC LIMIT ?",
                (chat_id, chat_id, user_id, self.owner_user_id, user_id,
                 term, pattern, pattern, pattern, pattern, pattern,
                 pattern, pattern, pattern, term, term, limit),
            ).fetchall()
            return [dict(row) for row in rows]
