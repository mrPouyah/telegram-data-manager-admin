"""Telegram update handling without network requests."""

from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from telegram_manager.access_bot import AccessBot
from telegram_manager.catalog_db import (
    AttachmentInput,
    CatalogDB,
    PublishedMessageInput,
)
from telegram_manager.config import Settings
from telegram_manager.telegram_api import TelegramError


class FakeAPI:
    def __init__(self, owner_is_admin: bool = True) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.owner_is_admin = owner_is_admin
        self.fail_copy = False
        self.fail_forward = False
        self.fail_group_copy_retryable = False
        self.fail_invalid_topic = False
        self.fail_delete_ids: set[int] = set()
        self.next_message_id = 1000

    def call(self, method: str, **parameters):
        self.calls.append((method, parameters))
        if method == "getMe":
            return {"id": 900}
        if method == "getChatMember":
            if parameters["user_id"] == 900:
                return {"status": "administrator"}
            return {"status": "creator" if self.owner_is_admin else "member"}
        if method == "getChat":
            return {"id": -100123 if parameters["chat_id"] == "@managedgroup" else -100999}
        if method == "createForumTopic":
            return {"message_thread_id": 42, "name": parameters["name"]}
        if method == "copyMessage" and self.fail_copy:
            raise TelegramError("source message unavailable")
        if method == "forwardMessage" and self.fail_forward:
            raise TelegramError("forward unavailable")
        if (method == "copyMessage" and self.fail_group_copy_retryable
                and parameters.get("chat_id") == -100123):
            raise TelegramError("uncertain delivery", retryable=True)
        if (method == "sendMessage" and self.fail_invalid_topic
                and parameters.get("chat_id") == -100123
                and parameters.get("message_thread_id")):
            raise TelegramError("sendMessage: Bad Request: message thread not found (HTTP 400)")
        if method == "deleteMessage" and parameters["message_id"] in self.fail_delete_ids:
            raise TelegramError("deleteMessage: Bad Request: message can't be deleted (HTTP 400)")
        if method in ("sendMessage", "copyMessage", "sendDocument", "sendPhoto", "sendVideo", "sendAudio", "sendVoice", "sendAnimation", "sendVideoNote", "sendSticker"):
            self.next_message_id += 1
            return {"message_id": self.next_message_id}
        return True


def private_message(user_id: int, text: str) -> dict:
    return {
        "message": {
            "from": {"id": user_id, "first_name": f"User {user_id}"},
            "chat": {"id": user_id, "type": "private"},
            "message_id": 10,
            "text": text,
        }
    }


def owner_callback(data: str, callback_id: str = "admin-callback") -> dict:
    return {"callback_query": {
        "id": callback_id, "from": {"id": 1},
        "message": {"chat": {"id": 1}}, "data": data,
    }}


def user_callback(user_id: int, data: str) -> dict:
    return {"callback_query": {
        "id": f"callback-{data}", "from": {"id": user_id},
        "message": {"chat": {"id": user_id}}, "data": data,
    }}


def topic_command(user_id: int, text: str, topic_id: int | None = 42) -> dict:
    message = {
        "from": {"id": user_id},
        "chat": {"id": -100123, "type": "supergroup"},
        "message_id": 30, "text": text,
    }
    if topic_id is not None:
        message["message_thread_id"] = topic_id
    return {"message": message}


class AccessBotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        settings = Settings("test-token", 1, -100123, Path(self.directory.name) / "db.sqlite3")
        self.database = CatalogDB(settings.database_path, settings.owner_user_id)
        self.api = FakeAPI()
        self.bot = AccessBot(settings, self.api, self.database)

    def register_existing(self, name: str, topic_id: int = 42) -> None:
        self.bot.handle_update(owner_callback("admin:existing_topic"))
        self.bot.handle_update(private_message(1, name))
        self.bot.handle_update(private_message(
            1, f"https://t.me/c/123/{topic_id}"
        ))

    def test_owner_must_be_group_admin_before_activation(self) -> None:
        self.api.owner_is_admin = False
        self.bot.handle_update(private_message(1, "/start"))
        self.assertIsNone(self.database.user_status(1))
        self.assertIn("تأیید مدیر انجام نشد", self.api.calls[-1][1]["text"])

        self.api.owner_is_admin = True
        self.bot.handle_update(private_message(1, "/start"))
        self.assertEqual(self.database.user_status(1), "approved")

    def test_request_and_owner_button_decision(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(private_message(2, "/request"))
        self.assertEqual(self.database.user_status(2), "pending")
        notification = [
            parameters for method, parameters in self.api.calls
            if method == "sendMessage" and parameters.get("chat_id") == 1
            and "reply_markup" in parameters
        ][-1]
        button = notification["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "تأیید")
        self.bot.handle_update({
            "callback_query": {
                "id": "callback-1", "from": {"id": 1},
                "message": {"chat": {"id": 1}}, "data": button["callback_data"],
            }
        })
        self.assertEqual(self.database.user_status(2), "approved")
        callback_calls = [
            method for method, _ in self.api.calls if method in
            ("answerCallbackQuery", "getMe", "getChatMember")
        ]
        self.assertEqual(callback_calls[-3:], [
            "answerCallbackQuery", "getChatMember", "getChatMember"
        ])
        approval = [
            parameters for method, parameters in self.api.calls
            if method == "sendMessage" and parameters.get("chat_id") == 2
            and "تأیید شد" in parameters["text"]
        ][-1]
        self.assertTrue(approval["reply_markup"]["is_persistent"])
        labels = [
            button["text"] for row in approval["reply_markup"]["keyboard"]
            for button in row
        ]
        self.assertIn("ارسال محتوا", labels)
        self.assertIn("جستجو و دریافت محتوا", labels)

    def test_approved_user_can_publish_and_retrieve_from_registered_topic(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Plans")
        self.assertEqual(self.database.list_topics(1, -100123)[0]["name"], "Plans")
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)

        self.bot.handle_update(private_message(2, "/menu"))
        self.assertEqual(self.api.calls[-1][1]["chat_id"], 2)
        self.assertTrue(self.api.calls[-1][1]["reply_markup"]["is_persistent"])

        self.bot.handle_update(private_message(2, "ارسال محتوا"))
        file_message = private_message(2, "")["message"]
        file_message["document"] = {"file_id": "test-file", "file_name": "plan.pdf"}
        self.bot.handle_update({"message": file_message})
        self.assertIn("هنوز منتشر نشده است", self.api.calls[-1][1]["text"])
        self.bot.handle_update(private_message(2, "Electrical plan"))
        topic_button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(topic_button["text"], "Plans")
        self.bot.handle_update(user_callback(2, topic_button["callback_data"]))
        preview = self.api.calls[-1][1]
        self.assertIn("Electrical plan", preview["text"])
        publish_button = preview["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(2, publish_button["callback_data"]))
        self.assertIn("منتشر و ذخیره شد", self.api.calls[-1][1]["text"])
        matches = self.database.search(2, "Electrical")
        self.assertEqual(len(matches), 1)
        content_id = matches[0]["id"]
        self.assertTrue(content_id.startswith("CNT_"))
        item = self.database.get_content(2, content_id)
        self.assertEqual(item["attachments"][0]["file_id"], "test-file")
        self.assertEqual(len(item["published_messages"]), 2)
        self.assertTrue(any(
            method == "sendMessage" and parameters.get("chat_id") == -100123
            and parameters.get("message_thread_id") == 42
            and f"#{content_id}" in parameters["text"]
            for method, parameters in self.api.calls
        ))
        group_posts = len([1 for method, parameters in self.api.calls
                           if parameters.get("chat_id") == -100123 and
                           method in ("sendMessage", "copyMessage")])
        self.bot.handle_update(user_callback(2, publish_button["callback_data"]))
        self.assertEqual(group_posts, len([1 for method, parameters in self.api.calls
                           if parameters.get("chat_id") == -100123 and
                           method in ("sendMessage", "copyMessage")]))

        self.bot.handle_update(private_message(2, "جستجو و دریافت محتوا"))
        self.bot.handle_update(private_message(2, "Electrical"))
        result_button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(2, result_button["callback_data"]))
        self.assertTrue(any(
            method == "forwardMessage" and parameters.get("chat_id") == 2
            and parameters.get("from_chat_id") == -100123
            for method, parameters in self.api.calls
        ))

        self.bot.handle_update(private_message(2, "دریافت محتوا"))
        topic_button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(topic_button["text"], "Plans")
        self.bot.handle_update(user_callback(2, topic_button["callback_data"]))
        listing = self.api.calls[-1][1]
        self.assertIn(content_id, listing["text"])
        self.assertIn("Electrical plan", listing["text"])
        self.assertIn("User 2", listing["text"])
        self.bot.handle_update(user_callback(
            2, listing["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        ))
        self.assertEqual(self.api.calls[-1][1]["from_chat_id"], -100123)
        self.api.fail_forward = True
        self.bot.handle_update(user_callback(
            2, listing["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        ))
        self.assertEqual(self.api.calls[-1][0], "copyMessage")

    def test_unapproved_user_cannot_use_user_buttons(self) -> None:
        self.bot.handle_update(private_message(2, "ارسال محتوا"))
        self.assertEqual(self.database.user_status(2), None)
        self.assertNotIn("reply_markup", self.api.calls[-1][1])
        self.assertIn("/request", self.api.calls[-1][1]["text"])

    def test_group_command_cannot_register_topic(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(topic_command(2, "/register_topic Unauthorized"))
        self.bot.handle_update(topic_command(1, "/register_topic Plans"))
        self.assertEqual(self.database.list_topics(1, -100123), [])

    def test_only_owner_can_register_existing_topic_in_private_chat(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(private_message(2, "https://t.me/c/123/42"))
        self.assertEqual(self.database.list_topics(1, -100123), [])
        self.register_existing("Plans")
        self.register_existing("Renamed")
        topics = self.database.list_topics(1, -100123)
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]["name"], "Plans")
        self.assertIn("قبلاً ثبت شده", self.api.calls[-1][1]["text"])

    def test_admin_button_registers_topic_and_user_resumes_waiting_draft(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        content = private_message(2, "")["message"]
        content["document"] = {"file_id": "file-1", "file_name": "plan.pdf"}
        self.bot.handle_update({"message": content})
        self.bot.handle_update(private_message(2, "Plan"))
        waiting = self.api.calls[-1][1]
        self.assertIn("پیش‌نویس شما حفظ شد", waiting["text"])
        refresh = waiting["reply_markup"]["inline_keyboard"][0][0]

        self.bot.handle_update(private_message(1, "ساخت موضوع جدید"))
        self.assertIn("نام موضوع جدید", self.api.calls[-1][1]["text"])
        self.assertEqual(self.database.list_topics(1, -100123), [])
        self.bot.handle_update(private_message(1, "Plans"))
        self.assertIn("ثبت شد", self.api.calls[-1][1]["text"])
        self.assertEqual(self.database.list_topics(1, -100123)[0]["topic_id"], 42)
        self.assertIn(("createForumTopic", {"chat_id": -100123, "name": "Plans"}), self.api.calls)
        self.bot.handle_update(user_callback(2, refresh["callback_data"]))
        button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "Plans")
        self.bot.handle_update(private_message(2, "ادامه پیش‌نویس"))
        resumed = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(resumed["text"], "Plans")

    def test_duplicate_topic_name_is_rejected_before_telegram_creation(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Plans")
        self.bot.handle_update(private_message(1, "ساخت موضوع جدید"))
        self.bot.handle_update(private_message(1, " plans "))
        self.assertIn("قبلاً ثبت شده", self.api.calls[-1][1]["text"])
        self.assertFalse(any(method == "createForumTopic" for method, _ in self.api.calls))
        self.assertEqual(len(self.database.admin_topics(1, -100123)), 1)

    def test_repeated_upload_update_does_not_create_another_draft(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        content = private_message(2, "")["message"]
        content["photo"] = [{"file_id": "photo-1", "file_unique_id": "same-photo"}]
        self.bot.handle_update({"message": content})
        self.bot.handle_update({"message": content})
        self.assertIn("قبلاً دریافت شده", self.api.calls[-1][1]["text"])
        with closing(sqlite3.connect(self.database.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM submission_drafts").fetchone()[0], 1)

    def test_duplicate_title_is_rejected_at_topic_selection_and_can_be_renamed(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Plans")
        project_topic = self.database.list_topics(1, -100123)[0]
        category = self.database.create_category(1, "photo")
        self.database.record_publication(
            1, content_id="CNT_EXISTING", project_id=project_topic["project_id"],
            category_id=category, destination_id=project_topic["id"],
            title="Site photo",
            messages=[PublishedMessageInput(-100123, 42, 150, "attachment")],
            attachments=[AttachmentInput("photo", "old-file", file_unique_id="old-unique")],
        )
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        content = private_message(2, "")["message"]
        content["photo"] = [{"file_id": "new-file", "file_unique_id": "new-unique"}]
        self.bot.handle_update({"message": content})
        self.bot.handle_update(private_message(2, " site photo "))
        topic_button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(2, topic_button["callback_data"]))
        self.assertIn("همین نام", self.api.calls[-1][1]["text"])
        self.assertEqual(self.bot.user_panel.workflow.active(2)["step"], "topic")
        self.bot.handle_update(private_message(2, "Site photo updated"))
        topic_button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(2, topic_button["callback_data"]))
        self.assertEqual(self.bot.user_panel.workflow.active(2)["state"], "ready")

    def test_identical_file_is_rejected_before_group_publication(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Plans")
        topic = self.database.list_topics(1, -100123)[0]
        category = self.database.create_category(1, "photo")
        self.database.record_publication(
            1, content_id="CNT_ORIGINAL", project_id=topic["project_id"],
            category_id=category, destination_id=topic["id"],
            title="Original photo",
            messages=[PublishedMessageInput(-100123, 42, 160, "attachment")],
            attachments=[AttachmentInput("photo", "old-file", file_unique_id="same-unique")],
        )
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        content = private_message(2, "")["message"]
        content["photo"] = [{"file_id": "new-file", "file_unique_id": "same-unique"}]
        self.bot.handle_update({"message": content})
        self.bot.handle_update(private_message(2, "Another photo"))
        topic_button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        group_calls_before = len([1 for method, args in self.api.calls
                                  if method == "sendMessage" and args.get("chat_id") == -100123])
        self.bot.handle_update(user_callback(2, topic_button["callback_data"]))
        self.assertIn("قبلاً در گروه ثبت شده", self.api.calls[-1][1]["text"])
        group_calls_after = len([1 for method, args in self.api.calls
                                 if method == "sendMessage" and args.get("chat_id") == -100123])
        self.assertEqual(group_calls_after, group_calls_before)
        self.assertEqual(self.bot.user_panel.workflow.active(2)["step"], "topic")

    def test_duplicate_appearing_after_preview_blocks_publish(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Plans")
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        content = private_message(2, "")["message"]
        content["document"] = {"file_id": "new-file", "file_unique_id": "new-unique"}
        self.bot.handle_update({"message": content})
        self.bot.handle_update(private_message(2, "Site plan"))
        topic_button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(2, topic_button["callback_data"]))
        publish_button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        topic = self.database.list_topics(1, -100123)[0]
        category = self.database.create_category(1, "document")
        self.database.record_publication(
            1, content_id="CNT_RACE", project_id=topic["project_id"],
            category_id=category, destination_id=topic["id"],
            title="Site plan",
            messages=[PublishedMessageInput(-100123, 42, 170, "attachment")],
            attachments=[AttachmentInput("document", "other-file")],
        )
        before = len([1 for method, args in self.api.calls
                      if method == "sendMessage" and args.get("chat_id") == -100123])
        self.bot.handle_update(user_callback(2, publish_button["callback_data"]))
        after = len([1 for method, args in self.api.calls
                     if method == "sendMessage" and args.get("chat_id") == -100123])
        self.assertEqual(before, after)
        self.assertIn("همین نام", self.api.calls[-1][1]["text"])
        self.assertEqual(self.bot.user_panel.workflow.active(2)["step"], "topic")

    def test_existing_topic_button_registers_link_in_private_chat(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(owner_callback("admin:existing_topic"))
        self.assertIn("نام موضوع موجود", self.api.calls[-1][1]["text"])
        self.bot.handle_update(private_message(1, "Existing plans"))
        self.assertIn("لینک مستقیم", self.api.calls[-1][1]["text"])
        self.assertEqual(self.database.list_topics(1, -100123), [])
        self.bot.handle_update(private_message(1, "https://t.me/c/123/42"))
        self.assertEqual(self.database.list_topics(1, -100123)[0]["name"], "Existing plans")
        self.assertFalse(any(method == "createForumTopic" for method, _ in self.api.calls))

    def test_existing_topic_rejects_wrong_group_and_message_link(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(owner_callback("admin:existing_topic"))
        self.bot.handle_update(private_message(1, "Plans"))
        for link in ("https://t.me/c/999/42", "https://t.me/c/123/42/99",
                     "https://t.me/othergroup/42"):
            self.bot.handle_update(private_message(1, link))
            self.assertEqual(self.database.list_topics(1, -100123), [])
        self.bot.handle_update(private_message(1, "https://t.me/c/123/42"))
        self.assertEqual(self.database.list_topics(1, -100123)[0]["topic_id"], 42)

    def test_existing_public_topic_link_is_matched_to_managed_group(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(owner_callback("admin:existing_topic"))
        self.bot.handle_update(private_message(1, "Plans"))
        self.bot.handle_update(private_message(1, "https://t.me/managedgroup/42"))
        self.assertEqual(self.database.list_topics(1, -100123)[0]["topic_id"], 42)

    def test_general_topic_link_registers_and_publishes_without_thread_id(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(owner_callback("admin:existing_topic"))
        self.bot.handle_update(private_message(1, "General"))
        self.bot.handle_update(private_message(1, "https://t.me/managedgroup/1"))
        topic = self.database.list_topics(1, -100123)[0]
        self.assertEqual(topic["topic_id"], 1)
        registration = [args for method, args in self.api.calls
                        if method == "sendMessage" and args.get("chat_id") == -100123][-1]
        self.assertNotIn("message_thread_id", registration)

        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        self.bot.handle_update(private_message(2, "General topic note"))
        self.bot.handle_update(private_message(2, "Note title"))
        choose = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(2, choose["callback_data"]))
        publish = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(2, publish["callback_data"]))
        item = self.database.search(2, "Note title")[0]
        self.assertEqual(self.database.get_content(2, item["id"])["published_messages"][0]["topic_id"], 1)
        group_posts = [args for method, args in self.api.calls
                       if method in ("sendMessage", "copyMessage")
                       and args.get("chat_id") == -100123]
        self.assertTrue(all("message_thread_id" not in args for args in group_posts))

    def test_existing_topic_send_failure_does_not_register(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(owner_callback("admin:existing_topic"))
        self.bot.handle_update(private_message(1, "Plans"))
        self.api.fail_invalid_topic = True
        self.bot.handle_update(private_message(1, "https://t.me/c/123/42"))
        self.assertEqual(self.database.list_topics(1, -100123), [])

    def test_topic_browse_respects_item_restrictions_and_revocation(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Plans")
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        self.bot.handle_update(private_message(3, "/request"))
        self.database.decide_access(1, 2, approve=True)
        topic = self.database.list_topics(1, -100123)[0]
        category = self.database.create_category(1, "text")
        self.database.record_publication(
            1, content_id="CNT_PRIVATE", project_id=topic["project_id"],
            category_id=category, destination_id=topic["id"], title="Restricted plan",
            original_text="Private plan",
            messages=[PublishedMessageInput(-100123, 42, 160, "text")],
        )
        self.database.restrict_item_to(1, "CNT_PRIVATE", [3])
        self.assertEqual(
            self.database.list_content_in_topic(2, -100123, topic["id"]), []
        )
        self.assertEqual(
            self.database.list_content_in_topic(3, -100123, topic["id"])[0]["id"],
            "CNT_PRIVATE",
        )
        self.bot.handle_update(private_message(3, "دریافت محتوا"))
        topic_button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(3, topic_button["callback_data"]))
        fetch_button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.database.revoke_user(1, 3)
        before = len([1 for method, _ in self.api.calls if method == "forwardMessage"])
        self.bot.handle_update(user_callback(3, fetch_button["callback_data"]))
        after = len([1 for method, _ in self.api.calls if method == "forwardMessage"])
        self.assertEqual(before, after)

    def test_topic_removal_from_bot_and_confirmed_group_deletion(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Plans")
        topic = self.database.admin_topics(1, -100123)[0]
        self.bot.handle_update(owner_callback(f"admin:topic:{topic['id']}"))
        actions = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"]
        self.assertEqual(actions[0][0]["text"], "حذف فقط از ربات")
        self.bot.handle_update(owner_callback(f"admin:topic_off:{topic['id']}"))
        self.assertEqual(self.database.list_topics(1, -100123), [])
        self.assertEqual(self.database.admin_topic(1, -100123, topic["id"])["deleted_from_group"], 0)
        self.assertFalse(any(method == "deleteForumTopic" for method, _ in self.api.calls))

        self.bot.handle_update(owner_callback(f"admin:topic_delete:{topic['id']}"))
        self.assertIn("آیا از حذف", self.api.calls[-1][1]["text"])
        self.assertFalse(any(method == "deleteForumTopic" for method, _ in self.api.calls))
        self.bot.handle_update(owner_callback(f"admin:topic_delete_yes:{topic['id']}"))
        self.assertIn(("deleteForumTopic", {
            "chat_id": -100123, "message_thread_id": 42,
        }), self.api.calls)
        self.assertEqual(self.database.admin_topic(1, -100123, topic["id"])["deleted_from_group"], 1)

    def test_uncertain_publication_stays_unindexed_and_cannot_repeat(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Plans")
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        content = private_message(2, "")["message"]
        content["document"] = {"file_id": "file-1", "file_name": "plan.pdf"}
        self.bot.handle_update({"message": content})
        self.bot.handle_update(private_message(2, "Plan"))
        topic = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(2, topic["callback_data"]))
        publish = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.api.fail_group_copy_retryable = True
        self.bot.handle_update(user_callback(2, publish["callback_data"]))
        self.assertIn("نیاز", self.api.calls[-1][1]["text"])
        with closing(sqlite3.connect(self.database.path)) as connection:
            state = connection.execute("SELECT state FROM publication_jobs").fetchone()[0]
        self.assertEqual(state, "needs_review")
        self.assertEqual(self.database.search(2, "Plan"), [])
        before = len([1 for method, params in self.api.calls
                      if method == "sendMessage" and params.get("chat_id") == -100123])
        self.bot.handle_update(user_callback(2, publish["callback_data"]))
        after = len([1 for method, params in self.api.calls
                     if method == "sendMessage" and params.get("chat_id") == -100123])
        self.assertEqual(before, after)

    def test_invalid_topic_keeps_draft_and_hides_destination(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Plans")
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        content = private_message(2, "")["message"]
        content["photo"] = [{"file_id": "photo-1", "file_unique_id": "unique-1"}]
        self.bot.handle_update({"message": content})
        self.bot.handle_update(private_message(2, "Test photo"))
        topic = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(2, topic["callback_data"]))
        publish = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.api.fail_invalid_topic = True
        self.bot.handle_update(user_callback(2, publish["callback_data"]))
        self.assertIn("پیش‌نویس شما حفظ شد", self.api.calls[-1][1]["text"])
        self.assertEqual(self.database.list_topics(2, -100123), [])
        draft = self.bot.user_panel.workflow.active(2)
        self.assertEqual((draft["step"], draft["state"]), ("topic", "draft"))
        with closing(sqlite3.connect(self.database.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM publication_jobs").fetchone()[0], 0)

    def test_text_submission_is_cataloged_and_searchable(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Meetings")
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        self.bot.handle_update(private_message(2, "Site meeting: door measurements changed"))
        self.bot.handle_update(private_message(2, "Door measurements"))
        topic = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(2, topic["callback_data"]))
        publish = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.bot.handle_update(user_callback(2, publish["callback_data"]))
        matches = self.database.search(2, "door measurements changed")
        self.assertEqual(len(matches), 1)
        item = self.database.get_content(2, matches[0]["id"])
        self.assertEqual(item["original_text"], "Site meeting: door measurements changed")
        self.assertEqual([message["role"] for message in item["published_messages"]],
                         ["summary", "text"])

    def test_owner_can_start_text_submission_from_admin_button(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Notes")
        self.bot.handle_update(private_message(1, "ارسال محتوا"))
        self.bot.handle_update(private_message(1, "Minutes from the site meeting"))
        self.assertIn("نامی برای آن بفرستید", self.api.calls[-1][1]["text"])
        self.assertIsNotNone(self.bot.user_panel.workflow.active(1))

    def test_photo_caption_becomes_title_and_skips_title_prompt(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.register_existing("Photos")
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        photo = private_message(2, "")["message"]
        photo["photo"] = [{"file_id": "small"}, {"file_id": "large"}]
        photo["caption"] = "Hook photos"
        self.bot.handle_update({"message": photo})
        draft = self.bot.user_panel.workflow.active(2)
        self.assertEqual(draft["title"], "Hook photos")
        self.assertEqual(draft["source_payload"]["file_id"], "large")
        self.assertEqual(self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["text"], "Photos")

    def test_revoked_user_cannot_use_stale_user_callback(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        self.database.revoke_user(1, 2)
        before = len(self.api.calls)
        self.bot.handle_update(user_callback(2, "user:fetch:CNT_ANY"))
        self.assertEqual(self.api.calls[before][0], "answerCallbackQuery")
        self.assertIn("تأیید نشده", self.api.calls[-1][1]["text"])
        self.assertFalse(any(method == "copyMessage" for method, _ in self.api.calls[before:]))

    def test_non_owner_callback_cannot_approve(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(private_message(2, "/request"))
        self.bot.handle_update({
            "callback_query": {
                "id": "callback-2", "from": {"id": 3},
                "message": {"chat": {"id": 3}}, "data": "access:approve:1",
            }
        })
        self.assertEqual(self.database.user_status(2), "pending")

    def test_non_owner_cannot_open_admin_menu(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        before = len(self.api.calls)
        self.bot.handle_update({"callback_query": {
            "id": "forged-menu", "from": {"id": 2},
            "message": {"chat": {"id": 2}}, "data": "admin:users:0",
        }})
        self.assertEqual(self.api.calls[before][0], "answerCallbackQuery")
        self.assertEqual(len(self.api.calls), before + 1)

    def test_start_installs_persistent_admin_keyboard(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        messages = [
            parameters for method, parameters in self.api.calls
            if method == "sendMessage" and parameters.get("chat_id") == 1
        ]
        keyboard = messages[-2]["reply_markup"]
        self.assertTrue(keyboard["is_persistent"])
        self.assertFalse(keyboard["one_time_keyboard"])
        labels = [button["text"] for row in keyboard["keyboard"] for button in row]
        self.assertIn("کاربران تأییدشده", labels)
        self.assertIn("جستجوی محتوا", labels)
        self.assertIn("منوی مدیریت", labels)

    def test_persistent_buttons_work_without_repeating_start(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(private_message(1, "کاربران تأییدشده"))
        self.assertIn("کاربر تأییدشده‌ای", self.api.calls[-1][1]["text"])

        self.bot.handle_update(private_message(1, "جستجوی محتوا"))
        self.assertTrue(self.bot.admin.awaiting_search)
        self.bot.handle_update(private_message(1, "منوی مدیریت"))
        self.assertFalse(self.bot.admin.awaiting_search)
        self.assertIn("inline_keyboard", self.api.calls[-1][1]["reply_markup"])

    def test_guide_button_shows_role_specific_persian_tutorials(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(private_message(1, "راهنما"))
        manager_guide = self.api.calls[-1][1]["text"]
        self.assertIn("راهنمای مدیر", manager_guide)
        self.assertIn("ثبت موضوع موجود", manager_guide)
        self.assertIn("درخواست‌های دسترسی", manager_guide)
        self.assertIn("تحلیل محتوای گروه", manager_guide)

        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        self.bot.handle_update(private_message(2, "راهنما"))
        user_guide = self.api.calls[-1][1]["text"]
        self.assertIn("راهنمای کاربر", user_guide)
        self.assertIn("پیش‌نمایش", user_guide)
        self.assertIn("شناسه یکتا", user_guide)
        self.assertIn("جستجو و دریافت محتوا", user_guide)
        self.assertNotIn("درخواست‌های دسترسی", user_guide)

    def test_non_owner_cannot_use_admin_keyboard_text(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        self.bot.handle_update(private_message(2, "کاربران تأییدشده"))
        self.assertEqual(self.api.calls[-1][1]["chat_id"], 2)
        self.assertNotIn("inline_keyboard", self.api.calls[-1][1].get("reply_markup", {}))
        self.assertEqual(self.database.user_status(2), None)

    def test_admin_menu_revokes_only_after_confirmation(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        menu = [
            parameters for method, parameters in self.api.calls
            if method == "sendMessage" and "reply_markup" in parameters
        ][-1]
        labels = [
            button["text"]
            for row in menu["reply_markup"]["inline_keyboard"] for button in row
        ]
        self.assertIn("کاربران تأییدشده", labels)
        self.assertIn("جستجوی محتوا", labels)

        self.bot.handle_update(private_message(2, "/request"))
        self.database.decide_access(1, 1, approve=True)
        self.bot.handle_update(owner_callback("admin:users:0"))
        user_list = [
            parameters for method, parameters in self.api.calls
            if method == "sendMessage" and "کاربران تأییدشده — صفحه" in parameters["text"]
        ][-1]
        revoke_button = user_list["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(revoke_button["callback_data"], "admin:revoke:2")
        self.bot.handle_update(owner_callback(revoke_button["callback_data"], "confirm"))
        self.assertEqual(self.database.user_status(2), "approved")
        self.bot.handle_update(owner_callback("admin:revoke_yes:2", "revoke"))
        self.assertEqual(self.database.user_status(2), "revoked")
        self.assertTrue(any(
            method == "sendMessage" and parameters.get("chat_id") == 2
            and "لغو شد" in parameters["text"]
            and parameters.get("reply_markup") == {"remove_keyboard": True}
            for method, parameters in self.api.calls
        ))
        self.bot.handle_update(private_message(2, "ارسال محتوا"))
        self.assertIn("لغو شده است", self.api.calls[-1][1]["text"])

    def test_admin_search_button_returns_stored_file(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        project = self.database.create_project(1, "Riverside")
        category = self.database.create_category(1, "Drawing")
        destination = self.database.register_destination(1, project, -100123, 42, "Plans")
        self.database.record_publication(
            1, content_id="CNT_TEST", project_id=project,
            category_id=category, destination_id=destination,
            title="Electrical plan",
            messages=[PublishedMessageInput(-100123, 42, 99, "attachment")],
            attachments=[AttachmentInput("document", "telegram-file", "plan.pdf")],
        )
        self.bot.handle_update(owner_callback("admin:search"))
        self.bot.handle_update(private_message(1, "Electrical"))
        results = [
            parameters for method, parameters in self.api.calls
            if method == "sendMessage" and "نتایج جستجو" in parameters["text"]
        ][-1]
        result_button = results["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(result_button["callback_data"], "admin:fetch:CNT_TEST")
        self.bot.handle_update(owner_callback(result_button["callback_data"], "fetch"))
        self.assertTrue(any(
            method == "copyMessage" and parameters["from_chat_id"] == -100123
            and parameters["message_id"] == 99
            for method, parameters in self.api.calls
        ))

    def test_admin_fetch_uses_file_id_if_group_copy_fails(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        project = self.database.create_project(1, "Riverside")
        category = self.database.create_category(1, "Drawing")
        destination = self.database.register_destination(1, project, -100123, 42, "Plans")
        self.database.record_publication(
            1, content_id="CNT_BACKUP", project_id=project,
            category_id=category, destination_id=destination,
            title="Backup plan",
            messages=[PublishedMessageInput(-100123, 42, 100, "attachment")],
            attachments=[AttachmentInput("document", "file-id-backup", "backup.pdf")],
        )
        self.api.fail_copy = True
        self.bot.handle_update(owner_callback("admin:fetch:CNT_BACKUP"))
        self.assertTrue(any(
            method == "sendDocument" and parameters["document"] == "file-id-backup"
            for method, parameters in self.api.calls
        ))

    def test_admin_deletes_content_from_catalog_or_group(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        project = self.database.create_project(1, "Riverside")
        category = self.database.create_category(1, "Drawing")
        destination = self.database.register_destination(1, project, -100123, 42, "Plans")
        for content_id, first_message in (("CNT_BOT", 101), ("CNT_GROUP", 201)):
            self.database.record_publication(
                1, content_id=content_id, project_id=project,
                category_id=category, destination_id=destination,
                title=content_id,
                messages=[PublishedMessageInput(-100123, 42, first_message, "summary"),
                          PublishedMessageInput(-100123, 42, first_message + 1, "attachment")],
                attachments=[AttachmentInput("document", f"file-{content_id}")],
            )

        self.bot.handle_update(private_message(1, "حذف محتوا"))
        self.bot.handle_update(private_message(1, "CNT_BOT"))
        button = self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(button["callback_data"], "admin:content:CNT_BOT")
        self.bot.handle_update(owner_callback("admin:content_bot:CNT_BOT"))
        self.assertIsNotNone(self.database.get_content(1, "CNT_BOT"))
        self.bot.handle_update(owner_callback("admin:content_bot_yes:CNT_BOT"))
        self.assertIsNone(self.database.get_content(1, "CNT_BOT"))
        self.assertFalse(any(method == "deleteMessage" for method, _ in self.api.calls))

        self.bot.handle_update(owner_callback("admin:content_group:CNT_GROUP"))
        self.assertIsNotNone(self.database.get_content(1, "CNT_GROUP"))
        self.bot.handle_update(owner_callback("admin:content_group_yes:CNT_GROUP"))
        deleted = [parameters["message_id"] for method, parameters in self.api.calls
                   if method == "deleteMessage"]
        self.assertEqual(deleted, [202, 201])
        self.assertIsNone(self.database.get_content(1, "CNT_GROUP"))
        self.assertEqual(self.database.admin_content(1, "CNT_GROUP")["status"], "unavailable")

    def test_partial_group_content_deletion_is_reported_and_hidden(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        project = self.database.create_project(1, "Riverside")
        category = self.database.create_category(1, "Drawing")
        destination = self.database.register_destination(1, project, -100123, 42, "Plans")
        self.database.record_publication(
            1, content_id="CNT_PARTIAL", project_id=project,
            category_id=category, destination_id=destination, title="Partial",
            messages=[PublishedMessageInput(-100123, 42, 301, "summary"),
                      PublishedMessageInput(-100123, 42, 302, "attachment")],
            attachments=[AttachmentInput("document", "file-partial")],
        )
        self.api.fail_delete_ids.add(301)
        self.bot.handle_update(owner_callback("admin:content_group_yes:CNT_PARTIAL"))
        self.assertIn("کامل نشد", self.api.calls[-1][1]["text"])
        self.assertEqual(self.database.admin_content(1, "CNT_PARTIAL")["status"], "archived")

    def test_admin_analysis_uses_only_bot_cataloged_group_content(self) -> None:
        self.bot.handle_update(private_message(1, "/start"))
        project = self.database.create_project(1, "Riverside")
        category = self.database.create_category(1, "photo")
        destination = self.database.register_destination(1, project, -100123, 42, "Plans")
        other_destination = self.database.register_destination(
            1, project, -100999, 77, "Other group"
        )
        for content_id, message_id in (("CNT_ONE", 501), ("CNT_TWO", 502)):
            self.database.record_publication(
                1, content_id=content_id, project_id=project,
                category_id=category, destination_id=destination,
                title=content_id,
                messages=[PublishedMessageInput(-100123, 42, message_id, "attachment")],
                attachments=[AttachmentInput("photo", f"file-{content_id}")],
            )
        self.database.record_publication(
            1, content_id="CNT_OTHER", project_id=project,
            category_id=category, destination_id=other_destination,
            title="Other group item",
            messages=[PublishedMessageInput(-100999, 77, 601, "attachment")],
            attachments=[AttachmentInput("photo", "file-other")],
        )
        self.database.remove_topic_from_bot(1, -100123, destination)
        self.bot.handle_update(owner_callback("admin:analyze"))
        report = self.api.calls[-1][1]
        self.assertIn("محتوای فعال: 2", report["text"])
        self.assertIn("Plans: 2 (غیرفعال)", report["text"])
        self.assertIn("0 نام تکراری", report["text"])
        self.assertIn("2 محتوا در موضوع غیرفعال", report["text"])
        self.assertNotIn("Other group item", report["text"])
        buttons = report["reply_markup"]["inline_keyboard"]
        self.assertTrue(any(button["callback_data"].startswith("admin:content:")
                            for row in buttons for button in row))

    def test_startup_retries_temporary_telegram_failure(self) -> None:
        class IntermittentAPI(FakeAPI):
            def __init__(self) -> None:
                super().__init__()
                self.authentication_attempts = 0

            def call(self, method: str, **parameters):
                if method == "getMe":
                    self.authentication_attempts += 1
                    if self.authentication_attempts == 1:
                        raise TelegramError("offline", retryable=True)
                if method == "getWebhookInfo":
                    return {"url": ""}
                if method == "getUpdates":
                    raise TelegramError("stop test")
                return super().call(method, **parameters)

        api = IntermittentAPI()
        self.bot.api = api
        with patch("telegram_manager.access_bot.time.sleep") as sleep:
            with self.assertRaises(TelegramError):
                self.bot.run()
        self.assertEqual(api.authentication_attempts, 2)
        sleep.assert_called_once_with(5)


if __name__ == "__main__":
    unittest.main()
