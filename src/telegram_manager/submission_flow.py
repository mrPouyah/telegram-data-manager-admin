"""Guided private submissions and topic publication."""

from datetime import datetime, timezone
import json
import sqlite3

from telegram_manager.catalog_db import AttachmentInput, CatalogDB, PublishedMessageInput
from telegram_manager.telegram_api import TelegramAPI, TelegramError
from telegram_manager.workflow_db import WorkflowDB
from telegram_manager.validation import DuplicateContentError


MEDIA_FIELDS = {
    "document": ("sendDocument", "document"),
    "photo": ("sendPhoto", "photo"),
    "video": ("sendVideo", "video"),
    "audio": ("sendAudio", "audio"),
    "voice": ("sendVoice", "voice"),
    "animation": ("sendAnimation", "animation"),
    "video_note": ("sendVideoNote", "video_note"),
    "sticker": ("sendSticker", "sticker"),
}


def source_payload(message: dict) -> dict | None:
    for kind in MEDIA_FIELDS:
        media = message.get(kind)
        if not media:
            continue
        if kind == "photo":
            media = media[-1]
        if not media.get("file_id"):
            return None
        return {
            "media_type": kind,
            "file_id": media["file_id"],
            "file_unique_id": media.get("file_unique_id"),
            "filename": media.get("file_name"),
            "caption": message.get("caption") or "",
        }
    content = (message.get("text") or "").strip()
    if content and not content.startswith("/"):
        return {"media_type": "text", "text": content}
    return None


class SubmissionFlow:
    def __init__(self, api: TelegramAPI, catalog: CatalogDB,
                 workflow: WorkflowDB, group_id: int, owner_id: int) -> None:
        self.api = api
        self.catalog = catalog
        self.workflow = workflow
        self.group_id = group_id
        self.owner_id = owner_id

    def _send(self, user_id: int, text: str, buttons: list[list[dict]] | None = None) -> None:
        args = {"chat_id": user_id, "text": text}
        if buttons is not None:
            args["reply_markup"] = {"inline_keyboard": buttons}
        self.api.call("sendMessage", **args)

    def receive(self, user_id: int, message: dict) -> bool:
        payload = source_payload(message)
        if payload is None:
            return False
        try:
            self.workflow.start(user_id, user_id, message["message_id"], payload)
        except ValueError as exc:
            if "already submitted" in str(exc):
                self._send(user_id, "این پیام قبلاً دریافت شده است. برای ادامه از «ادامه پیش‌نویس» استفاده کنید.")
            else:
                self._send(user_id, "این پیام قابل ثبت نیست. یک محتوای معتبر دوباره بفرستید.")
            return True
        caption_lines = (payload.get("caption") or "").splitlines()
        caption_title = caption_lines[0].strip() if caption_lines else ""
        if caption_title and len(caption_title) <= 150:
            self.title(user_id, caption_title)
            return True
        suggestion = payload.get("filename") or ""
        self._send(
            user_id,
            "محتوا دریافت شد و هنوز منتشر نشده است. نامی برای آن بفرستید. "
            + (f"نام فایل: {suggestion}\n" if suggestion else "")
            + "برای لغو، /cancel را بفرستید.",
        )
        return True

    def title(self, user_id: int, value: str) -> None:
        draft = self.workflow.set_title(user_id, value)
        topics = self.catalog.list_topics(user_id, self.group_id)
        if not topics:
            self._send(
                user_id,
                "هنوز موضوعی ثبت نشده است. از مدیر بخواهید موضوعی را ثبت کند. "
                "پیش‌نویس شما حفظ شد؛ سپس دکمه تازه‌سازی را بزنید.",
                [[{"text": "تازه‌سازی موضوع‌ها",
                   "callback_data": f"user:topics:{draft['id']}"}]],
            )
            return
        buttons = [
            [{"text": topic["name"],
              "callback_data": f"user:topic:{draft['id']}:{topic['id']}"}]
            for topic in topics[:40]
        ]
        buttons.append([{"text": "لغو", "callback_data": f"user:cancel:{draft['id']}"}])
        self._send(user_id, "موضوع مقصد را انتخاب کنید:", buttons)

    def show_topics(self, user_id: int, draft: dict) -> None:
        topics = self.catalog.list_topics(user_id, self.group_id)
        if not topics:
            self._send(
                user_id, "هنوز موضوعی برای ارسال ثبت نشده است. پس از ثبت مدیر، دوباره تازه‌سازی کنید.",
                [[{"text": "تازه‌سازی موضوع‌ها",
                   "callback_data": f"user:topics:{draft['id']}"}]],
            )
            return
        buttons = [
            [{"text": topic["name"],
              "callback_data": f"user:topic:{draft['id']}:{topic['id']}"}]
            for topic in topics[:40]
        ]
        self._send(user_id, "موضوع مقصد را انتخاب کنید:", buttons)

    def choose_topic(self, user_id: int, draft_id: int, destination_id: int) -> None:
        topic = self.catalog.topic(user_id, self.group_id, destination_id)
        if topic is None:
            raise PermissionError("Topic is unavailable")
        current = self.workflow.active(user_id)
        if current is None or current["id"] != draft_id or current["step"] != "topic":
            raise ValueError("Draft is no longer waiting for a topic")
        duplicate = self.catalog.find_duplicate_content(
            user_id, self.group_id, destination_id,
            current["title"], current["source_payload"],
        )
        if duplicate is not None:
            self._send(user_id, self._duplicate_message(duplicate))
            return
        draft = self.workflow.set_topic(
            user_id, draft_id, topic["project_id"], destination_id
        )
        self.show_review(user_id, draft)

    @staticmethod
    def _duplicate_message(duplicate: DuplicateContentError) -> str:
        reference = f" شناسه محتوای موجود: {duplicate.existing_id}." if duplicate.existing_id else ""
        if duplicate.reason == "title":
            return "محتوایی با همین نام در این موضوع ثبت شده است. نام دیگری بفرستید یا /cancel را بزنید." + reference
        return "این فایل یا متن قبلاً در گروه ثبت شده است. محتوای تکراری منتشر نمی‌شود." + reference

    def show_review(self, user_id: int, draft: dict) -> None:
        topic = self.catalog.topic(user_id, self.group_id, draft["destination_id"])
        if topic is None:
            raise PermissionError("Topic is unavailable")
        draft_id = draft["id"]
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        payload = draft["source_payload"]
        self._send(
            user_id,
            f"پیش‌نمایش انتشار\nنام: {draft['title']}\nموضوع: {topic['name']}\n"
            f"نوع: {payload['media_type']}\nتاریخ: {date}\n"
            "پس از تأیید، شناسه یکتا ساخته و محتوا در این موضوع منتشر می‌شود.",
            [[{"text": "تأیید و انتشار", "callback_data": f"user:publish:{draft_id}"},
              {"text": "لغو", "callback_data": f"user:cancel:{draft_id}"}]],
        )

    def _copy_or_send(self, draft: dict, topic: dict) -> dict:
        payload = draft["source_payload"]
        args = {"chat_id": self.group_id}
        if topic["topic_id"] != 1:
            args["message_thread_id"] = topic["topic_id"]
        try:
            return self.api.call(
                "copyMessage", **args, from_chat_id=draft["source_chat_id"],
                message_id=json.loads(draft["source_message_ids"])[0],
            )
        except TelegramError as exc:
            if exc.retryable:
                raise
            if payload["media_type"] == "text":
                return self.api.call("sendMessage", **args, text=payload["text"])
            method, field = MEDIA_FIELDS[payload["media_type"]]
            return self.api.call(method, **args, **{field: payload["file_id"]})

    def publish(self, user_id: int, draft_id: int) -> None:
        draft = self.workflow.active(user_id)
        if draft is None or draft["id"] != draft_id or draft["state"] != "ready":
            self._send(user_id, "این پیش‌نویس دیگر آماده انتشار نیست.")
            return
        topic = self.catalog.topic(user_id, self.group_id, draft["destination_id"])
        if topic is None:
            self._send(user_id, "موضوع مقصد دیگر در دسترس نیست.")
            return
        try:
            draft, content_id = self.workflow.begin_publish(user_id, draft_id)
        except DuplicateContentError as exc:
            if exc.reason == "title":
                self.workflow.return_ready_to_topic(user_id, draft_id)
            self._send(user_id, self._duplicate_message(exc))
            return
        except (PermissionError, ValueError):
            self._send(user_id, "انتشار قبلاً شروع شده یا دسترسی شما تغییر کرده است.")
            return
        except sqlite3.Error:
            self._send(user_id, "پایگاه داده فعلاً در دسترس نیست. کمی بعد دوباره تلاش کنید.")
            return
        payload = draft["source_payload"]
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        summary = (
            f"{draft['title']}\nموضوع: {topic['name']}\nتاریخ: {date}\n"
            f"نوع: {payload['media_type']}\nشناسه: #{content_id}"
        )
        try:
            send_args = {"chat_id": self.group_id}
            if topic["topic_id"] != 1:
                send_args["message_thread_id"] = topic["topic_id"]
            sent = self.api.call("sendMessage", **send_args, text=summary)
            self.workflow.record_sent(draft_id, "summary", sent["message_id"])
            copied = self._copy_or_send(draft, topic)
            role = "text" if payload["media_type"] == "text" else "attachment"
            self.workflow.record_sent(draft_id, role, copied["message_id"])
            messages = [
                PublishedMessageInput(self.group_id, topic["topic_id"],
                                      row["message_id"], row["role"])
                for row in self.workflow.sent(draft_id)
            ]
            attachments = [] if role == "text" else [AttachmentInput(
                payload["media_type"], payload["file_id"], payload.get("filename"),
                payload.get("file_unique_id"),
            )]
            self.catalog.record_publication(
                user_id, content_id=content_id, project_id=topic["project_id"],
                category_id=self.catalog.category_for_media(payload["media_type"]),
                destination_id=topic["id"], title=draft["title"],
                description=payload.get("caption"),
                original_text=payload.get("text"),
                messages=messages, attachments=attachments,
            )
            self.workflow.finish(draft_id)
            self._send(user_id, f"محتوا در موضوع «{topic['name']}» منتشر و ذخیره شد.\nشناسه: {content_id}")
        except (TelegramError, PermissionError, ValueError, KeyError, sqlite3.Error) as exc:
            if (isinstance(exc, TelegramError)
                    and "message thread not found" in str(exc).lower()
                    and not self.workflow.sent(draft_id)):
                self.catalog.disable_topic(self.owner_id, self.group_id, topic["topic_id"])
                self.workflow.reset_invalid_topic(draft_id)
                self._send(
                    user_id,
                    "موضوع مقصد در گروه پیدا نشد و انتشار انجام نشد. پیش‌نویس شما حفظ شد. "
                    "از مدیر بخواهید موضوع را دوباره ثبت کند؛ سپس «ادامه پیش‌نویس» را بزنید.",
                )
                return
            self.workflow.needs_review(draft_id, str(exc))
            self._send(
                user_id,
                f"انتشار کامل نشد. ممکن است بخشی در گروه ارسال شده باشد. "
                f"برای جلوگیری از تکرار، دوباره منتشر نکنید. شناسه پیگیری: {content_id}",
            )
            try:
                self._send(self.owner_id, f"انتشار {content_id} نیاز به بررسی دستی دارد.")
            except TelegramError:
                pass
