"""Approved-user menu, guided submission, and catalog retrieval."""

from telegram_manager.catalog_db import CatalogDB
from telegram_manager.submission_flow import MEDIA_FIELDS, SubmissionFlow
from telegram_manager.telegram_api import TelegramAPI, TelegramError
from telegram_manager.workflow_db import WorkflowDB


class UserPanel:
    MENU_LABELS = (
        ("ارسال محتوا", "دریافت محتوا"),
        ("جستجو و دریافت محتوا",),
        ("ادامه پیش‌نویس", "راهنما"),
        ("منوی کاربر",),
    )

    def __init__(self, api: TelegramAPI, catalog: CatalogDB,
                 group_id: int, owner_id: int) -> None:
        self.api = api
        self.catalog = catalog
        self.group_id = group_id
        self.searching: set[int] = set()
        self.workflow = WorkflowDB(catalog.path)
        self.submission = SubmissionFlow(
            api, catalog, self.workflow, group_id, owner_id
        )

    @classmethod
    def keyboard(cls) -> dict:
        return {
            "keyboard": [[{"text": label} for label in row] for row in cls.MENU_LABELS],
            "is_persistent": True,
            "resize_keyboard": True,
            "one_time_keyboard": False,
        }

    def _send(self, user_id: int, text: str, buttons: list[list[dict]] | None = None) -> None:
        args = {"chat_id": user_id, "text": text}
        if buttons is not None:
            args["reply_markup"] = {"inline_keyboard": buttons}
        self.api.call("sendMessage", **args)

    def show_menu(self, user_id: int) -> None:
        self.searching.discard(user_id)
        self.api.call(
            "sendMessage", chat_id=user_id,
            text="منوی کاربر — یک گزینه را انتخاب کنید:",
            reply_markup=self.keyboard(),
        )

    def handle_menu_text(self, user_id: int, text: str) -> bool:
        choice = text.strip()
        if choice == "منوی کاربر":
            self.show_menu(user_id)
        elif choice == "ارسال محتوا":
            self.searching.discard(user_id)
            self._send(user_id, "فایل، ویدیو، عکس، صوت یا متن را در همین گفتگوی خصوصی بفرستید. سپس نام و موضوع مقصد را انتخاب می‌کنید. هر پیام یک محتوای جداگانه است.")
        elif choice == "جستجو و دریافت محتوا":
            self.searching.add(user_id)
            self._send(user_id, "نام، شناسه یکتا، نام فایل یا بخشی از متن را بفرستید.")
        elif choice == "دریافت محتوا":
            self.searching.discard(user_id)
            self.browse_topics(user_id)
        elif choice == "ادامه پیش‌نویس":
            self.searching.discard(user_id)
            draft = self.workflow.active(user_id)
            if draft is None:
                self._send(user_id, "پیش‌نویس فعالی وجود ندارد. برای شروع، محتوا را بفرستید.")
            elif draft["step"] == "title":
                self._send(user_id, "نام محتوا را بفرستید.")
            elif draft["step"] == "topic":
                self.submission.show_topics(user_id, draft)
            else:
                self.submission.show_review(user_id, draft)
        elif choice == "راهنما":
            self._send(
                user_id,
                "راهنمای کاربر\n\n"
                "ارسال و بایگانی محتوا:\n"
                "۱. «ارسال محتوا» را بزنید و یک متن، عکس، ویدیو، فایل، صوت یا پیام پشتیبانی‌شده را در همین گفتگوی خصوصی بفرستید.\n"
                "۲. نام محتوا را بفرستید و یکی از موضوع‌های ثبت‌شده گروه را انتخاب کنید.\n"
                "۳. پیش‌نمایش را بررسی و انتشار را تأیید کنید. ربات محتوا را در همان موضوع با نام، تاریخ و شناسه یکتا منتشر می‌کند و اطلاعات آن را در پایگاه داده ذخیره می‌کند.\n\n"
                "جستجو و دریافت:\n"
                "«دریافت محتوا» را بزنید، موضوع را انتخاب کنید، سپس از فهرست نام، شناسه و فرستنده، محتوای موردنظر را بزنید. ربات پیام اصلی را از گروه برایتان فوروارد می‌کند. "
                "برای جستجوی مستقیم، «جستجو و دریافت محتوا» را بزنید؛ نام، شناسه یکتا، نام فایل یا بخشی از متن را بفرستید و نتیجه را انتخاب کنید.\n\n"
                "پیش‌نویس و محدودیت‌ها:\n"
                "برای ادامه کار ناتمام، «ادامه پیش‌نویس» را بزنید. /cancel پیش‌نویس را لغو می‌کند. "
                "هر پیام یک محتوای جداگانه است؛ آلبوم را باید فایل‌به‌فایل بفرستید. "
                "ارسال تکراری یا نام تکراری در یک موضوع ممکن است رد شود. "
                "استفاده از ربات به تأیید مدیر نیاز دارد."
            )
        else:
            return False
        return True

    def browse_topics(self, user_id: int, page: int = 0) -> None:
        if page < 0:
            raise ValueError("Invalid topic page")
        topics = self.catalog.list_topics(user_id, self.group_id)
        start = page * 10
        if start >= len(topics) and page:
            raise ValueError("Topic page is unavailable")
        if not topics:
            self._send(user_id, "هنوز موضوع فعالی برای دریافت محتوا ثبت نشده است.")
            return
        buttons = [
            [{"text": topic["name"][:55],
              "callback_data": f"user:browse_topic:{topic['id']}:0"}]
            for topic in topics[start:start + 10]
        ]
        navigation = []
        if page:
            navigation.append({"text": "قبلی", "callback_data": f"user:browse_topics:{page - 1}"})
        if start + 10 < len(topics):
            navigation.append({"text": "بعدی", "callback_data": f"user:browse_topics:{page + 1}"})
        if navigation:
            buttons.append(navigation)
        buttons.append([{"text": "جستجو", "callback_data": "user:search"}])
        self._send(user_id, "برای دیدن فهرست محتوا، یک موضوع را انتخاب کنید:", buttons)

    def browse_topic(self, user_id: int, destination_id: int, page: int = 0) -> None:
        if page < 0:
            raise ValueError("Invalid content page")
        topic = next(
            (row for row in self.catalog.list_topics(user_id, self.group_id)
             if row["id"] == destination_id), None,
        )
        if topic is None:
            raise ValueError("Topic is unavailable")
        items = self.catalog.list_content_in_topic(
            user_id, self.group_id, destination_id, limit=11, offset=page * 10
        )
        if not items and page:
            raise ValueError("Content page is unavailable")
        if not items:
            self._send(user_id, f"هنوز محتوایی در موضوع «{topic['name']}» ثبت نشده است.", [
                [{"text": "بازگشت به موضوع‌ها", "callback_data": "user:browse_topics:0"}]
            ])
            return
        lines = [f"محتوای موضوع «{topic['name']}»: "]
        buttons = []
        for index, item in enumerate(items[:10], 1):
            sender = item["display_name"] or (
                "@" + item["username"] if item["username"] else str(item["submitter_user_id"])
            )
            lines.append(f"{index}. {item['title']}\nشناسه: {item['id']}\nفرستنده: {sender[:60]}")
            buttons.append([{"text": f"{index}. {item['title'][:35]}",
                             "callback_data": f"user:fetch:{item['id']}"}])
        navigation = []
        if page:
            navigation.append({"text": "قبلی", "callback_data": f"user:browse_topic:{destination_id}:{page - 1}"})
        if len(items) > 10:
            navigation.append({"text": "بعدی", "callback_data": f"user:browse_topic:{destination_id}:{page + 1}"})
        if navigation:
            buttons.append(navigation)
        buttons.append([{"text": "بازگشت به موضوع‌ها", "callback_data": "user:browse_topics:0"}])
        self._send(user_id, "\n\n".join(lines), buttons)

    def handle_message(self, user_id: int, message: dict) -> None:
        text = (message.get("text") or "").strip()
        if text == "/cancel":
            self.searching.discard(user_id)
            cancelled = self.workflow.cancel(user_id)
            self._send(user_id, "پیش‌نویس لغو شد." if cancelled else "پیش‌نویس فعالی وجود ندارد.")
            return
        if self.handle_menu_text(user_id, text):
            return
        if user_id in self.searching and text:
            self.searching.discard(user_id)
            self.search(user_id, text)
            return
        draft = self.workflow.active(user_id)
        if draft and draft["step"] == "title" and text and not text.startswith("/"):
            try:
                self.submission.title(user_id, text)
            except ValueError:
                self._send(user_id, "نام باید بین ۱ تا ۱۵۰ نویسه باشد. دوباره بفرستید.")
            return
        if draft and draft["step"] == "topic":
            if any(key in message for key in MEDIA_FIELDS):
                self._send(user_id, "یک پیش‌نویس در انتظار انتخاب موضوع است. ابتدا آن را کامل کنید یا /cancel را بفرستید.")
                return
            if text and not text.startswith("/"):
                try:
                    self.submission.title(user_id, text)
                except ValueError:
                    self._send(user_id, "نام باید بین ۱ تا ۱۵۰ نویسه و بدون خط جدید باشد. دوباره بفرستید.")
            else:
                self.submission.show_topics(user_id, draft)
            return
        if draft and draft["step"] == "review":
            if any(key in message for key in MEDIA_FIELDS):
                self._send(user_id, "یک پیش‌نویس در انتظار تأیید انتشار است. ابتدا آن را کامل کنید یا /cancel را بفرستید.")
                return
            self._send(user_id, "برای انتشار، دکمه تأیید در پیش‌نمایش را بزنید یا /cancel را بفرستید.")
            return
        if message.get("media_group_id"):
            self._send(user_id, "ارسال آلبومی هنوز پشتیبانی نمی‌شود. لطفاً فایل‌ها را جداگانه بفرستید.")
            return
        if self.submission.receive(user_id, message):
            return
        self._send(user_id, "این نوع پیام قابل ثبت نیست. متن یا یک فایل پشتیبانی‌شده بفرستید.")

    def search(self, user_id: int, query: str) -> None:
        matches = self.catalog.search(user_id, query, limit=10, chat_id=self.group_id)
        if not matches:
            self._send(user_id, "محتوایی با این نام یا شناسه پیدا نشد.", [
                [{"text": "جستجوی دوباره", "callback_data": "user:search"}]
            ])
            return
        buttons = [
            [{"text": f"{item['title'][:28]} · {item['id']}",
              "callback_data": f"user:fetch:{item['id']}"}]
            for item in matches if len(f"user:fetch:{item['id']}".encode()) <= 64
        ]
        buttons.append([{"text": "جستجوی دوباره", "callback_data": "user:search"}])
        self._send(user_id, "نتایج جستجو — برای دریافت انتخاب کنید:", buttons)

    def fetch(self, user_id: int, content_id: str) -> None:
        item = self.catalog.get_content(user_id, content_id)
        if item is None or not any(
            row["chat_id"] == self.group_id for row in item["published_messages"]
        ):
            self._send(user_id, "این محتوا پیدا نشد یا دسترسی شما تغییر کرده است.")
            return
        published_topic = next(iter(item["published_messages"]), None)
        topic_name = item["project_name"]
        if published_topic:
            topic_name = next(
                (topic["name"] for topic in self.catalog.list_topics(user_id, self.group_id)
                 if topic["topic_id"] == published_topic["topic_id"]),
                topic_name,
            )
        self._send(user_id, f"نام: {item['title']}\nموضوع: {topic_name}\nشناسه: {item['id']}")
        attachments = item["attachments"]
        index = 0
        delivered = 0
        text_delivered = False
        for published in item["published_messages"]:
            if published["role"] == "summary":
                continue
            try:
                self.api.call(
                    "forwardMessage", chat_id=user_id,
                    from_chat_id=published["chat_id"],
                    message_id=published["message_id"],
                )
                delivered += 1
                text_delivered |= published["role"] == "text"
            except TelegramError:
                copied = False
                try:
                    self.api.call(
                        "copyMessage", chat_id=user_id,
                        from_chat_id=published["chat_id"],
                        message_id=published["message_id"],
                    )
                    delivered += 1
                    text_delivered |= published["role"] == "text"
                    copied = True
                except TelegramError:
                    pass
                if not copied and published["role"] == "text" and item["original_text"]:
                    self._send(user_id, item["original_text"])
                    delivered += 1
                    text_delivered = True
                elif not copied and published["role"] == "attachment" and index < len(attachments):
                    attachment = attachments[index]
                    pair = MEDIA_FIELDS.get(attachment["media_type"])
                    if pair:
                        try:
                            self.api.call(pair[0], chat_id=user_id,
                                          **{pair[1]: attachment["file_id"]})
                            delivered += 1
                        except TelegramError:
                            pass
            if published["role"] == "attachment":
                index += 1
        if not text_delivered and item["original_text"]:
            self._send(user_id, item["original_text"])
            delivered += 1
        if delivered == 0:
            self._send(user_id, "نسخه اصلی این محتوا اکنون قابل ارسال نیست.")

    def handle_callback(self, callback: dict) -> None:
        callback_id = callback.get("id")
        user_id = (callback.get("from") or {}).get("id")
        chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
        if not callback_id:
            return
        self.api.call("answerCallbackQuery", callback_query_id=callback_id)
        if not isinstance(user_id, int) or chat_id != user_id:
            return
        if self.catalog.user_status(user_id) != "approved":
            self._send(user_id, "دسترسی شما تأیید نشده یا لغو شده است.")
            return
        parts = (callback.get("data") or "").split(":")
        try:
            if parts[:2] == ["user", "search"]:
                self.searching.add(user_id)
                self._send(user_id, "نام یا شناسه محتوا را بفرستید.")
            elif parts[:2] == ["user", "browse_topics"] and len(parts) == 3:
                self.browse_topics(user_id, int(parts[2]))
            elif parts[:2] == ["user", "browse_topic"] and len(parts) == 4:
                self.browse_topic(user_id, int(parts[2]), int(parts[3]))
            elif parts[:2] == ["user", "fetch"] and len(parts) == 3:
                self.fetch(user_id, parts[2])
            elif parts[:2] == ["user", "topic"] and len(parts) == 4:
                self.submission.choose_topic(user_id, int(parts[2]), int(parts[3]))
            elif parts[:2] == ["user", "topics"] and len(parts) == 3:
                active = self.workflow.active(user_id)
                if active is None or active["id"] != int(parts[2]) or active["step"] != "topic":
                    raise ValueError("Stale topic refresh button")
                self.submission.show_topics(user_id, active)
            elif parts[:2] == ["user", "publish"] and len(parts) == 3:
                self.submission.publish(user_id, int(parts[2]))
            elif parts[:2] == ["user", "cancel"] and len(parts) == 3:
                active = self.workflow.active(user_id)
                if active is None or active["id"] != int(parts[2]):
                    raise ValueError("Stale cancel button")
                self.workflow.cancel(user_id)
                self._send(user_id, "پیش‌نویس لغو شد.")
            else:
                self._send(user_id, "دکمه نامعتبر است.")
        except (ValueError, PermissionError):
            self._send(user_id, "این عملیات دیگر معتبر نیست یا دسترسی شما تغییر کرده است.")
