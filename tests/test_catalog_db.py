"""Database behavior across approvals, publication, and retrieval."""

from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest

from telegram_manager.catalog_db import (
    AttachmentInput,
    CatalogDB,
    PublishedMessageInput,
)
from telegram_manager.database import connect
from telegram_manager.validation import DuplicateContentError


class CatalogDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = CatalogDB(Path(self.directory.name) / "catalog.sqlite3", 1)
        self.database.activate_owner(1)  # The Telegram layer must verify admin status first.
        self.project = self.database.create_project(1, "Riverside Villa")
        self.category = self.database.create_category(1, "Drawing")
        self.destination = self.database.register_destination(
            1, self.project, -100123, 42, "Plans", is_default=True
        )

    def approve(self, user_id: int, *, read: bool, submit: bool) -> None:
        request_id = self.database.request_access(user_id)
        self.database.decide_access(1, request_id, approve=True)
        self.database.set_project_permission(
            1, user_id, self.project, can_read=read, can_submit=submit
        )

    def publish(self, user_id: int = 2, content_id: str = "CNT_ABC123") -> None:
        self.database.record_publication(
            user_id,
            content_id=content_id,
            project_id=self.project,
            category_id=self.category,
            destination_id=self.destination,
            title="Electrical layout",
            description="Ground floor socket plan",
            messages=[PublishedMessageInput(-100123, 42, 99, "attachment")],
            attachments=[AttachmentInput("document", "tg-file-1", "electrical.pdf")],
        )

    def test_approval_permissions_and_retrieval(self) -> None:
        self.approve(2, read=True, submit=True)
        request_id = self.database.request_access(3)
        self.database.decide_access(1, request_id, approve=True)
        self.assertEqual(len(self.database.list_projects(2, "submit")), 1)
        self.assertEqual(len(self.database.list_projects(3, "submit")), 1)
        self.assertEqual(self.database.list_destinations(2, self.project)[0]["topic_id"], 42)
        self.assertEqual(self.database.list_destinations(3, self.project)[0]["topic_id"], 42)
        self.assertEqual(self.database.list_categories(3)[0]["name"], "Drawing")
        self.publish()

        matches = self.database.search(3, "electrical")
        self.assertEqual([item["id"] for item in matches], ["CNT_ABC123"])
        item = self.database.get_content(3, "CNT_ABC123")
        self.assertEqual(item["attachments"][0]["file_id"], "tg-file-1")
        self.assertEqual(item["published_messages"][0]["topic_id"], 42)
        self.assertEqual(self.database.search(3, "electrical.pdf")[0]["id"], "CNT_ABC123")
        self.assertEqual(self.database.search(3, "electrical", chat_id=-100999), [])
        self.assertEqual(self.database.search(3, "CNT_ABC123")[0]["id"], "CNT_ABC123")
        self.assertEqual(self.database.search(3, "#CNT_ABC123")[0]["id"], "CNT_ABC123")
        self.database.update_search_text("CNT_ABC123", "socket positions", "complete", "pdf")
        self.assertEqual(self.database.search(3, "socket positions")[0]["id"], "CNT_ABC123")

        self.database.revoke_user(1, 3)
        self.assertEqual(self.database.search(3, "electrical"), [])
        self.assertIsNone(self.database.get_content(3, "CNT_ABC123"))
        with closing(connect(self.database.path)) as connection:
            old_grants = connection.execute(
                "SELECT count(*) FROM project_permissions WHERE telegram_user_id = 3"
            ).fetchone()[0]
            self.assertEqual(old_grants, 0)

    def test_unapproved_users_cannot_submit_or_discover(self) -> None:
        self.assertFalse(self.database.can_access_project(4, self.project, "read"))
        self.assertEqual(self.database.list_projects(4, "read"), [])
        self.assertEqual(self.database.list_categories(4), [])
        self.assertEqual(self.database.search(4, "Riverside"), [])
        self.assertIsNone(self.database.get_content(4, "CNT_ABC123"))
        with self.assertRaises(PermissionError):
            self.publish(4)

    def test_item_restriction_and_project_permission_both_apply(self) -> None:
        self.approve(2, read=True, submit=True)
        self.approve(3, read=True, submit=False)
        self.publish()
        self.database.restrict_item_to(1, "CNT_ABC123", [2])
        self.assertEqual(self.database.search(3, "electrical"), [])
        self.assertIsNone(self.database.get_content(3, "CNT_ABC123"))
        self.assertIsNotNone(self.database.get_content(1, "CNT_ABC123"))
        self.database.restrict_item_to(1, "CNT_ABC123", [])
        self.assertEqual(len(self.database.search(3, "electrical")), 1)

    def test_publication_is_atomic_and_content_id_is_unique(self) -> None:
        self.approve(2, read=True, submit=True)
        with self.assertRaises(ValueError):
            self.database.record_publication(
                2, content_id="CNT_BAD", project_id=self.project,
                category_id=self.category, destination_id=self.destination,
                title="Wrong destination",
                messages=[PublishedMessageInput(-100123, 999, 100, "text")],
            )
        self.assertIsNone(self.database.get_content(1, "CNT_BAD"))
        self.publish()
        with self.assertRaises(sqlite3.IntegrityError):
            self.publish(content_id="CNT_ABC123")
        self.assertEqual(len(self.database.search(1, "CNT_ABC123")), 1)

    def test_only_owner_can_approve_or_change_catalog(self) -> None:
        request_id = self.database.request_access(2)
        self.assertEqual(self.database.request_access(2), request_id)
        with self.assertRaises(PermissionError):
            self.database.decide_access(2, request_id, approve=True)
        with self.assertRaises(PermissionError):
            self.database.create_project(2, "Unauthorized")
        self.database.decide_access(1, request_id, approve=True)
        self.assertEqual(self.database.approved_users(1)[0]["telegram_user_id"], 2)
        self.assertIsNotNone(self.database.approved_user(1, 2))
        with self.assertRaises(PermissionError):
            self.database.approved_users(2)
        with self.assertRaises(PermissionError):
            self.database.set_project_permission(
                2, 2, self.project, can_read=True, can_submit=True
            )

    def test_duplicate_topic_names_and_existing_topics_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.database.register_topic(1, -100123, 42, "Plans")
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.database.register_topic(1, -100123, 43, " plans ")
        with self.assertRaises(ValueError):
            self.database.register_topic(1, -100123, 43, "Invalid\nname")
        self.assertEqual(len(self.database.admin_topics(1, -100123)), 1)

    def test_removed_topic_can_be_reactivated_with_updated_label(self) -> None:
        destination = self.database.register_topic(1, -100123, 43, "Old plans")
        self.database.remove_topic_from_bot(1, -100123, destination)
        self.database.register_topic(1, -100123, 43, "New plans")
        topic = next(row for row in self.database.list_topics(1, -100123)
                     if row["topic_id"] == 43)
        self.assertEqual(topic["name"], "New plans")
        with closing(connect(self.database.path)) as connection:
            project_name = connection.execute(
                "SELECT name FROM projects WHERE id = ?", (topic["project_id"],)
            ).fetchone()["name"]
        self.assertTrue(project_name.startswith("New plans ["))

    def test_duplicate_title_or_file_is_rejected_before_catalog_insert(self) -> None:
        self.approve(2, read=True, submit=True)
        self.publish()
        with self.assertRaises(DuplicateContentError) as title_error:
            self.database.record_publication(
                2, content_id="CNT_SAME_TITLE", project_id=self.project,
                category_id=self.category, destination_id=self.destination,
                title=" electrical layout ",
                messages=[PublishedMessageInput(-100123, 42, 100, "attachment")],
                attachments=[AttachmentInput("document", "different-file")],
            )
        self.assertEqual(title_error.exception.reason, "title")
        other = self.database.register_destination(
            1, self.project, -100123, 43, "Photos"
        )
        with self.assertRaises(DuplicateContentError) as file_error:
            self.database.record_publication(
                2, content_id="CNT_SAME_FILE", project_id=self.project,
                category_id=self.category, destination_id=other,
                title="Another title",
                messages=[PublishedMessageInput(-100123, 43, 101, "attachment")],
                attachments=[AttachmentInput("document", "tg-file-1")],
            )
        self.assertEqual(file_error.exception.reason, "content")
        self.assertIsNone(self.database.admin_content(1, "CNT_SAME_TITLE"))
        self.assertIsNone(self.database.admin_content(1, "CNT_SAME_FILE"))

    def test_catalog_only_removal_still_blocks_duplicate_group_file(self) -> None:
        self.approve(2, read=True, submit=True)
        self.publish()
        self.database.set_content_status(1, "CNT_ABC123", "archived")
        other = self.database.register_destination(1, self.project, -100123, 43, "Photos")
        arguments = dict(
            content_id="CNT_REUPLOAD", project_id=self.project,
            category_id=self.category, destination_id=other,
            title="Re-upload",
            messages=[PublishedMessageInput(-100123, 43, 101, "attachment")],
            attachments=[AttachmentInput("document", "tg-file-1")],
        )
        with self.assertRaises(DuplicateContentError):
            self.database.record_publication(2, **arguments)
        self.database.set_content_status(1, "CNT_ABC123", "unavailable")
        self.database.record_publication(2, **arguments)
        self.assertIsNotNone(self.database.get_content(2, "CNT_REUPLOAD"))


if __name__ == "__main__":
    unittest.main()
