"""Persian button menu for the configured owner."""

from collections.abc import Callable
import sqlite3
from telegram_manager.catalog_db import CatalogDB
from telegram_manager.telegram_api import TelegramAPI, TelegramError
from telegram_manager.topic_links import topic_from_link


class AdminPanel:
    MENU_LABELS = (
        ("درخواست‌های دسترسی", "کاربران تأییدشده"),
        ("جستجوی محتوا", "دریافت محتوا", "حذف محتوا"),
        ("موضوع‌های ثبت‌شده", "تحلیل محتوای گروه"),
        ("ساخت موضوع جدید", "ثبت موضوع موجود"),
        ("ارسال محتوا", "منوی مدیریت"),
        ("راهنما",),
    )

    def __init__(
        self,
        owner_user_id: int,
        group_id: int,
        api: TelegramAPI,
        database: CatalogDB,
        verify_owner: Callable[[], None],
        show_pending: Callable[[], None],
    ) -> None:
        self.owner_user_id = owner_user_id
        self.group_id = group_id
        self.api = api
        self.database = database
        self.verify_owner = verify_owner
        self.show_pending = show_pending
        self.awaiting_search = False
        self.awaiting_delete_search = False
        self.awaiting_topic_name = False
        self.awaiting_existing_topic_name = False
        self.existing_topic_name: str | None = None

    def _send(self, text: str, buttons: list[list[dict]] | None = None) -> None:
        parameters = {"chat_id": self.owner_user_id, "text": text}
        if buttons is not None:
            parameters["reply_markup"] = {"inline_keyboard": buttons}
        self.api.call("sendMessage", **parameters)

    @staticmethod
    def _button(label: str, action: str) -> dict:
        return {"text": label, "callback_data": action}

    @classmethod
    def persistent_keyboard(cls) -> dict:
        return {
            "keyboard": [[{"text": label} for label in row] for row in cls.MENU_LABELS],
            "is_persistent": True,
            "resize_keyboard": True,
            "one_time_keyboard": False,
        }

    def handle_menu_text(self, text: str) -> bool:
        actions = {
            "درخواست‌های دسترسی": self.show_pending,
            "کاربران تأییدشده": lambda: self._show_users(0),
            "جستجوی محتوا": self._begin_search,
            "حذف محتوا": self._begin_delete_search,
            "موضوع‌های ثبت‌شده": self._show_projects,
            "تحلیل محتوای گروه": self._analyze_content,
            "ساخت موضوع جدید": self._begin_topic_registration,
            "ثبت موضوع موجود": self._begin_existing_topic_registration,
            "راهنما": self._show_help,
            "منوی مدیریت": self.show_menu,
        }
        action = actions.get(text.strip())
        if action is None:
            return False
        self.verify_owner()
        self.awaiting_search = False
        self.awaiting_delete_search = False
        self.awaiting_topic_name = False
        self.awaiting_existing_topic_name = False
        self.existing_topic_name = None
        action()
        return True

    def _begin_search(self) -> None:
        self.awaiting_search = True
        self.awaiting_delete_search = False
        self.awaiting_topic_name = False
        self.awaiting_existing_topic_name = False
        self._send("نام، شناسه، یا بخشی از توضیح محتوا را بفرستید.")

    def _begin_topic_registration(self) -> None:
        self.awaiting_search = False
        self.awaiting_delete_search = False
        self.awaiting_topic_name = True
        self.awaiting_existing_topic_name = False
        self._send(
            "نام موضوع جدید را بفرستید تا ربات آن را در گروه بسازد و برای ارسال محتوا ثبت کند."
        )

    def _begin_existing_topic_registration(self) -> None:
        self.awaiting_search = False
        self.awaiting_delete_search = False
        self.awaiting_topic_name = False
        self.awaiting_existing_topic_name = True
        self.existing_topic_name = None
        self._send("نام موضوع موجود را برای نمایش به کاربران بفرستید.")

    def handle_topic_text(self, text: str) -> bool:
        if not self.awaiting_topic_name and not self.awaiting_existing_topic_name:
            return False
        if not text.strip() or text.startswith("/"):
            return False
        self.verify_owner()
        if self.awaiting_existing_topic_name and self.existing_topic_name is not None:
            topic = topic_from_link(text, self.group_id)
            if topic is None:
                self._send("لینک مستقیم موضوع از همین گروه را بفرستید؛ لینک پیام یا گروه پذیرفته نمی‌شود.")
                return True
            topic_id, username = topic
            if username is not None:
                try:
                    linked_group = self.api.call("getChat", chat_id="@" + username)
                except TelegramError:
                    self._send("گروه این لینک پیدا نشد. لینک مستقیم موضوع را بررسی کنید.")
                    return True
                if linked_group.get("id") != self.group_id:
                    self._send("این لینک به گروه تنظیم‌شده برای ربات تعلق ندارد.")
                    return True
            if any(
                topic["topic_id"] == topic_id and topic["active"]
                for topic in self.database.admin_topics(self.owner_user_id, self.group_id)
            ):
                self._send("این موضوع قبلاً ثبت شده است. لینک موضوع دیگری را بفرستید.")
                return True
            try:
                send_args = {"chat_id": self.group_id}
                if topic_id != 1:
                    send_args["message_thread_id"] = topic_id
                self.api.call("sendMessage", **send_args,
                              text=f"موضوع «{self.existing_topic_name}» برای مدیریت محتوا ثبت شد.")
            except TelegramError:
                self._send("موضوع پیدا نشد یا ربات اجازه ارسال پیام در آن را ندارد. لینک موضوع را بررسی کنید.")
                return True
            self.database.register_topic(
                self.owner_user_id, self.group_id, topic_id, self.existing_topic_name
            )
            self.awaiting_existing_topic_name = False
            self.existing_topic_name = None
            self._send("موضوع موجود ثبت شد و اکنون برای کاربران قابل انتخاب است.")
            return True
        try:
            name = self.database.ensure_topic_name_available(
                self.owner_user_id, self.group_id, text
            )
        except ValueError:
            self._send("نام موضوع نامعتبر است یا موضوعی با همین نام قبلاً ثبت شده است. نام دیگری بفرستید.")
            return True
        if self.awaiting_existing_topic_name:
            self.existing_topic_name = name
            self._send("اکنون لینک مستقیم همان موضوع را از تلگرام کپی کنید و در همین گفت‌وگوی خصوصی بفرستید.")
            return True
        created = self.api.call("createForumTopic", chat_id=self.group_id, name=name)
        if not isinstance(created, dict) or not isinstance(created.get("message_thread_id"), int):
            self._send("تلگرام شناسه معتبر موضوع را برنگرداند. موضوع گروه را بررسی کنید.")
            return True
        self.database.register_topic(self.owner_user_id, self.group_id,
                                     created["message_thread_id"], name)
        self.awaiting_topic_name = False
        self.awaiting_existing_topic_name = False
        self._send(f"موضوع «{name}» ثبت شد و اکنون برای کاربران قابل انتخاب است.")
        return True

    def _show_help(self) -> None:
        self._send(
            "راهنمای مدیر ربات\n\n"
            "دسترسی کاربران:\n"
            "«درخواست‌های دسترسی» را برای تأیید یا رد درخواست‌ها بزنید. "
            "از «کاربران تأییدشده» می‌توانید دسترسی یک کاربر را با تأیید نهایی لغو کنید.\n\n"
            "مدیریت موضوع‌ها:\n"
            "«ساخت موضوع جدید» موضوع را در گروه می‌سازد و در ربات ثبت می‌کند. "
            "برای موضوعی که از قبل در گروه وجود دارد، «ثبت موضوع موجود» را بزنید، نام و سپس لینک مستقیم موضوع را در گفت‌وگوی خصوصی ربات بفرستید. "
            "موضوع‌های جدید گروه خودکار شناسایی نمی‌شوند. "
            "از «موضوع‌های ثبت‌شده» می‌توانید موضوع را فقط از فهرست ربات بردارید یا پس از تأیید، از گروه هم حذف کنید.\n\n"
            "مدیریت محتوا:\n"
            "«ارسال محتوا» همان مسیر کاربر است: محتوا را بفرستید، نام و موضوع را مشخص کنید و انتشار را تأیید کنید. "
            "«جستجوی محتوا» برای پیدا کردن محتوای ثبت‌شده است. «دریافت محتوا» فهرست موضوع‌ها و سپس نام، شناسه و فرستنده محتوا را نشان می‌دهد. "
            "«حذف محتوا» امکان برداشتن آن از فهرست ربات یا حذف پیام‌های ثبت‌شده‌اش از گروه را می‌دهد. "
            "«تحلیل محتوای گروه» گزارش محتوایی را نشان می‌دهد که از طریق همین ربات منتشر شده است؛ پیام‌های دیگر گروه را بررسی نمی‌کند.\n\n"
            "برای باز کردن دوباره پنل، «منوی مدیریت» یا /menu را بزنید."
        )

    def show_menu(self) -> None:
        self.awaiting_search = False
        self.awaiting_delete_search = False
        self.awaiting_topic_name = False
        self.awaiting_existing_topic_name = False
        self._send(
            "پنل مدیریت ربات — یک گزینه را انتخاب کنید:",
            [
                [self._button("درخواست‌های دسترسی", "admin:pending"),
                 self._button("کاربران تأییدشده", "admin:users:0")],
                [self._button("جستجوی محتوا", "admin:search"),
                 self._button("حذف محتوا", "admin:delete_search")],
                [self._button("موضوع‌های ثبت‌شده", "admin:projects"),
                 self._button("تحلیل محتوای گروه", "admin:analyze")],
                [self._button("ساخت موضوع جدید", "admin:add_topic"),
                 self._button("ثبت موضوع موجود", "admin:existing_topic")],
                [self._button("ارسال محتوا", "admin:submit")],
                [self._button("راهنما", "admin:help")],
            ],
        )

    def _show_users(self, page: int) -> None:
        if page < 0:
            raise ValueError("Invalid page")
        page_size = 10
        records = self.database.approved_users(
            self.owner_user_id, limit=page_size + 1, offset=page * page_size
        )
        visible = records[:page_size]
        if not visible:
            self._send("کاربر تأییدشده‌ای در این صفحه وجود ندارد.", [
                [self._button("بازگشت به منو", "admin:menu")]
            ])
            return
        buttons = [
            [self._button(
                f"{(user['display_name'] or user['username'] or 'کاربر')[:25]} · {user['telegram_user_id']}",
                f"admin:revoke:{user['telegram_user_id']}",
            )]
            for user in visible
        ]
        navigation = []
        if page:
            navigation.append(self._button("صفحه قبل", f"admin:users:{page - 1}"))
        if len(records) > page_size:
            navigation.append(self._button("صفحه بعد", f"admin:users:{page + 1}"))
        if navigation:
            buttons.append(navigation)
        buttons.append([self._button("بازگشت به منو", "admin:menu")])
        self._send(
            f"کاربران تأییدشده — صفحه {page + 1}\n"
            "برای لغو دسترسی، کاربر را انتخاب کنید.",
            buttons,
        )

    def _confirm_revoke(self, user_id: int) -> None:
        user = self.database.approved_user(self.owner_user_id, user_id)
        if user is None:
            self._send("این کاربر دیگر دسترسی تأییدشده ندارد.")
            return
        name = user["display_name"] or user["username"] or "نامشخص"
        self._send(
            f"دسترسی {name} با شناسه {user_id} لغو شود؟",
            [[self._button("بله، لغو دسترسی", f"admin:revoke_yes:{user_id}"),
              self._button("انصراف", "admin:menu")]],
        )

    def _revoke(self, user_id: int) -> None:
        self.database.revoke_user(self.owner_user_id, user_id)
        self._send(f"دسترسی کاربر {user_id} لغو شد.", [
            [self._button("کاربران تأییدشده", "admin:users:0"),
             self._button("بازگشت به منو", "admin:menu")]
        ])
        try:
            self.api.call(
                "sendMessage", chat_id=user_id,
                text="دسترسی شما به ربات توسط مدیر لغو شد.",
                reply_markup={"remove_keyboard": True},
            )
        except TelegramError:
            pass  # The database decision remains effective if delivery fails.

    def _show_projects(self, page: int = 0) -> None:
        if page < 0:
            raise ValueError("Invalid topic page")
        topics = self.database.admin_topics(self.owner_user_id, self.group_id)
        if not topics:
            self._send("هنوز موضوعی ثبت نشده است. از دکمه‌های ساخت یا ثبت موضوع استفاده کنید.")
            return
        page_size = 10
        visible = topics[page * page_size:(page + 1) * page_size]
        if not visible:
            raise ValueError("Topic page is empty")
        buttons = [
            [self._button(
                f"{topic['name'][:35]} · "
                + ("حذف‌شده از گروه" if topic["deleted_from_group"] else
                   "غیرفعال" if not topic["active"] else "فعال"),
                f"admin:topic:{topic['id']}",
            )]
            for topic in visible
        ]
        navigation = []
        if page:
            navigation.append(self._button("صفحه قبل", f"admin:topics:{page - 1}"))
        if len(topics) > (page + 1) * page_size:
            navigation.append(self._button("صفحه بعد", f"admin:topics:{page + 1}"))
        if navigation:
            buttons.append(navigation)
        self._send("موضوع‌های ثبت‌شده — برای مدیریت، موضوع را انتخاب کنید:", buttons)

    def _analyze_content(self) -> None:
        analysis = self.database.analyze_managed_content(
            self.owner_user_id, self.group_id
        )
        topics = analysis["topics"]
        items = analysis["items"]
        active_items = [item for item in items if item["status"] == "published"]
        by_topic = {topic["topic_id"]: 0 for topic in topics}
        by_type: dict[str, int] = {}
        duplicates: dict[tuple[int, str], list[dict]] = {}
        for item in active_items:
            by_topic[item["topic_id"]] = by_topic.get(item["topic_id"], 0) + 1
            media_type = item["media_type"]
            by_type[media_type] = by_type.get(media_type, 0) + 1
            duplicates.setdefault((item["topic_id"], item["title"].casefold().strip()), []).append(item)
        missing_details = [item for item in active_items if not (item["description"] or "").strip()]
        inactive_topics = {topic["topic_id"] for topic in topics if not topic["active"]}
        needs_topic_review = [item for item in active_items if item["topic_id"] in inactive_topics]
        duplicate_groups = [group for group in duplicates.values() if len(group) > 1]
        lines = [
            "گزارش محتوای ثبت‌شده توسط ربات در این گروه",
            f"محتوای فعال: {len(active_items)} | موضوع‌های فعال: {sum(topic['active'] for topic in topics)}",
            "به تفکیک موضوع:",
        ]
        for topic in topics[:20]:
            suffix = " (غیرفعال)" if not topic["active"] else ""
            lines.append(f"• {topic['name']}: {by_topic.get(topic['topic_id'], 0)}{suffix}")
        if len(topics) > 20:
            lines.append(f"• {len(topics) - 20} موضوع دیگر")
        lines.append("به تفکیک نوع: " + (
            "، ".join(f"{kind}: {count}" for kind, count in sorted(by_type.items()))
            if by_type else "محتوایی ثبت نشده"
        ))
        lines.append(
            f"برای بازبینی: {len(duplicate_groups)} نام تکراری، "
            f"{len(needs_topic_review)} محتوا در موضوع غیرفعال، "
            f"{len(missing_details)} محتوا بدون توضیح."
        )
        flagged = []
        seen = set()
        for item in [*needs_topic_review, *(group[0] for group in duplicate_groups)]:
            if item["id"] not in seen:
                seen.add(item["id"])
                flagged.append(item)
        buttons = [
            [self._button(f"بازبینی: {item['title'][:25]}", f"admin:content:{item['id']}")]
            for item in flagged[:8]
        ]
        buttons.append([self._button("موضوع‌ها", "admin:topics:0"),
                        self._button("بازگشت به منو", "admin:menu")])
        self._send("\n".join(lines)[:3900], buttons)

    def _show_topic(self, destination_id: int) -> None:
        topic = self.database.admin_topic(self.owner_user_id, self.group_id, destination_id)
        if topic is None:
            raise ValueError("Topic not found")
        if topic["deleted_from_group"]:
            self._send(f"موضوع «{topic['name']}» از گروه حذف شده است.", [
                [self._button("موضوع‌ها", "admin:topics:0")]
            ])
            return
        buttons = []
        if topic["active"]:
            buttons.append([self._button("حذف فقط از ربات", f"admin:topic_off:{destination_id}")])
        if topic["topic_id"] != 1:
            buttons.append([self._button("حذف از گروه", f"admin:topic_delete:{destination_id}")])
        buttons.append([self._button("موضوع‌ها", "admin:topics:0")])
        self._send(f"موضوع: {topic['name']}\nحذف فقط از ربات، پیام‌های گروه را نگه می‌دارد.", buttons)

    def _remove_topic_from_bot(self, destination_id: int) -> None:
        topic = self.database.admin_topic(self.owner_user_id, self.group_id, destination_id)
        if topic is None:
            raise ValueError("Topic not found")
        self.database.remove_topic_from_bot(self.owner_user_id, self.group_id,
                                            destination_id)
        self._send(f"موضوع «{topic['name']}» از گزینه‌های ربات حذف شد. پیام‌های گروه باقی ماندند.")

    def _confirm_delete_group_topic(self, destination_id: int) -> None:
        topic = self.database.admin_topic(self.owner_user_id, self.group_id, destination_id)
        if topic is None or topic["deleted_from_group"] or topic["topic_id"] == 1:
            raise ValueError("Topic cannot be deleted")
        self._send(
            f"آیا از حذف موضوع «{topic['name']}» از گروه مطمئن هستید؟ "
            "تمام پیام‌های داخل آن موضوع نیز حذف می‌شوند.",
            [[self._button("بله، حذف از گروه", f"admin:topic_delete_yes:{destination_id}"),
              self._button("انصراف", f"admin:topic:{destination_id}")]],
        )

    def _delete_group_topic(self, destination_id: int) -> None:
        topic = self.database.admin_topic(self.owner_user_id, self.group_id, destination_id)
        if topic is None or topic["deleted_from_group"] or topic["topic_id"] == 1:
            raise ValueError("Topic cannot be deleted")
        self.api.call("deleteForumTopic", chat_id=self.group_id,
                      message_thread_id=topic["topic_id"])
        self.database.mark_topic_group_deleted(self.owner_user_id, self.group_id,
                                               destination_id)
        self._send(f"موضوع «{topic['name']}» از گروه حذف شد و محتوای آن دیگر در جستجوی ربات نمایش داده نمی‌شود.")

    def _show_search_results(self, query: str) -> None:
        matches = self.database.search(self.owner_user_id, query, limit=10)
        if not matches:
            self._send("محتوایی با این نام یا شناسه پیدا نشد.", [
                [self._button("جستجوی دوباره", "admin:search"),
                 self._button("بازگشت به منو", "admin:menu")]
            ])
            return
        buttons = [
            [self._button(
                f"{item['title'][:28]} · {item['id']}", f"admin:fetch:{item['id']}"
            )]
            for item in matches if len(f"admin:fetch:{item['id']}".encode()) <= 64
        ]
        buttons.append([self._button("جستجوی دوباره", "admin:search")])
        self._send("نتایج جستجو — برای دریافت محتوا انتخاب کنید:", buttons)

    def handle_search_text(self, text: str) -> bool:
        if not self.awaiting_search or text.startswith("/"):
            return False
        self.verify_owner()
        self.awaiting_search = False
        if not text.strip():
            self._send("نام یا شناسه محتوا را بنویسید.")
            self.awaiting_search = True
            return True
        self._show_search_results(text)
        return True

    def _begin_delete_search(self) -> None:
        self.awaiting_search = False
        self.awaiting_topic_name = False
        self.awaiting_existing_topic_name = False
        self.awaiting_delete_search = True
        self._send("شناسه یکتا یا نام محتوایی را که می‌خواهید حذف کنید بفرستید.")

    def handle_delete_search_text(self, text: str) -> bool:
        if not self.awaiting_delete_search or text.startswith("/"):
            return False
        self.verify_owner()
        self.awaiting_delete_search = False
        matches = self.database.admin_search_content(self.owner_user_id, text)
        if not matches:
            self._send("محتوایی با این نام یا شناسه پیدا نشد.")
            return True
        buttons = [
            [self._button(f"{item['title'][:28]} · {item['id']}",
                          f"admin:content:{item['id']}")]
            for item in matches
        ]
        self._send("محتوای موردنظر را انتخاب کنید:", buttons)
        return True

    def _show_content_actions(self, content_id: str) -> None:
        item = self.database.admin_content(self.owner_user_id, content_id)
        if item is None:
            raise ValueError("Content item not found")
        self._send(
            f"نام: {item['title']}\nشناسه: {content_id}\nوضعیت: {item['status']}",
            [[self._button("حذف فقط از فهرست ربات", f"admin:content_bot:{content_id}")],
             [self._button("حذف پیام‌ها از گروه و فهرست", f"admin:content_group:{content_id}")],
             [self._button("بازگشت به منو", "admin:menu")]],
        )

    def _confirm_content_delete(self, content_id: str, from_group: bool) -> None:
        item = self.database.admin_content(self.owner_user_id, content_id)
        if item is None:
            raise ValueError("Content item not found")
        if from_group:
            warning = "پیام‌های این محتوا از گروه حذف می‌شوند و دیگر در جستجو نمایش داده نمی‌شوند. مطمئن هستید؟"
            action = "content_group_yes"
        else:
            warning = "این محتوا از جستجو و دریافت ربات حذف می‌شود؛ پیام‌های گروه باقی می‌مانند. مطمئن هستید؟"
            action = "content_bot_yes"
        self._send(
            f"{item['title']}\nشناسه: {content_id}\n{warning}",
            [[self._button("بله، حذف شود", f"admin:{action}:{content_id}"),
              self._button("انصراف", f"admin:content:{content_id}")]],
        )

    def _delete_content_from_bot(self, content_id: str) -> None:
        self.database.set_content_status(self.owner_user_id, content_id, "archived")
        self._send(f"محتوای {content_id} از فهرست ربات حذف شد. پیام‌های گروه باقی ماندند.")

    def _delete_content_from_group(self, content_id: str) -> None:
        item = self.database.admin_content(self.owner_user_id, content_id)
        if item is None:
            raise ValueError("Content item not found")
        messages = item["published_messages"]
        if not messages or any(row["chat_id"] != self.group_id for row in messages):
            raise ValueError("Content does not belong to the managed group")
        deleted = 0
        failed = 0
        for message in sorted(messages, key=lambda row: row["role"] == "summary"):
            try:
                self.api.call("deleteMessage", chat_id=self.group_id,
                              message_id=message["message_id"])
                deleted += 1
            except TelegramError as exc:
                if "message to delete not found" in str(exc).lower():
                    deleted += 1
                else:
                    failed += 1
        if failed:
            if deleted:
                self.database.set_content_status(self.owner_user_id, content_id,
                                                 "archived")
            self._send(
                f"حذف پیام‌های {content_id} کامل نشد. {failed} پیام حذف نشد. "
                "ممکن است پیام‌های قدیمی از محدودیت زمانی تلگرام گذشته باشند."
            )
            return
        self.database.set_content_status(self.owner_user_id, content_id, "unavailable")
        self._send(f"پیام‌های {content_id} از گروه و محتوا از فهرست ربات حذف شدند.")

    def _send_attachment(self, attachment: dict) -> bool:
        methods = {
            "document": ("sendDocument", "document"),
            "photo": ("sendPhoto", "photo"),
            "video": ("sendVideo", "video"),
            "audio": ("sendAudio", "audio"),
            "voice": ("sendVoice", "voice"),
            "animation": ("sendAnimation", "animation"),
            "video_note": ("sendVideoNote", "video_note"),
            "sticker": ("sendSticker", "sticker"),
        }
        method_and_field = methods.get(attachment["media_type"])
        if method_and_field is None:
            return False
        method, field = method_and_field
        try:
            self.api.call(
                method, chat_id=self.owner_user_id, **{field: attachment["file_id"]}
            )
            return True
        except TelegramError:
            return False

    def _fetch_content(self, content_id: str) -> None:
        item = self.database.get_content(self.owner_user_id, content_id)
        if item is None:
            self._send("این محتوا پیدا نشد یا دسترسی آن تغییر کرده است.")
            return
        published_topic = next(iter(item["published_messages"]), None)
        topic_name = item["project_name"]
        if published_topic:
            topic_name = next(
                (topic["name"] for topic in self.database.list_topics(self.owner_user_id, self.group_id)
                 if topic["topic_id"] == published_topic["topic_id"]),
                topic_name,
            )
        self._send(
            f"{item['title']}\nموضوع: {topic_name}\n"
            f"نوع محتوا: {item['category_name']}\nشناسه: {item['id']}"
        )
        attachments = item["attachments"]
        attachment_index = 0
        delivered = 0
        text_delivered = False
        failed = 0
        for message in item["published_messages"]:
            if message["role"] == "summary":
                continue
            try:
                self.api.call(
                    "copyMessage", chat_id=self.owner_user_id,
                    from_chat_id=message["chat_id"], message_id=message["message_id"],
                )
                delivered += 1
                if message["role"] == "text":
                    text_delivered = True
            except TelegramError:
                if message["role"] == "attachment" and attachment_index < len(attachments):
                    if self._send_attachment(attachments[attachment_index]):
                        delivered += 1
                    else:
                        failed += 1
                elif message["role"] == "text" and item["original_text"]:
                    self._send(item["original_text"])
                    delivered += 1
                    text_delivered = True
                else:
                    failed += 1
            if message["role"] == "attachment":
                attachment_index += 1
        for attachment in attachments[attachment_index:]:
            if self._send_attachment(attachment):
                delivered += 1
            else:
                failed += 1
        if item["original_text"] and not text_delivered:
            self._send(item["original_text"])
            delivered += 1
        if delivered == 0:
            self._send("نسخه اصلی این محتوا اکنون قابل ارسال نیست.")
        elif failed:
            self._send("بخشی از فایل‌های این محتوا قابل ارسال نبود.")

    def handle_callback(self, callback: dict) -> None:
        callback_id = callback.get("id")
        actor = (callback.get("from") or {}).get("id")
        chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
        if not callback_id:
            return
        if actor != self.owner_user_id or chat_id != self.owner_user_id:
            self.api.call(
                "answerCallbackQuery", callback_query_id=callback_id,
                text="فقط مدیر مجاز است.",
            )
            return
        self.api.call(
            "answerCallbackQuery", callback_query_id=callback_id,
            text="در حال انجام...",
        )
        try:
            self.verify_owner()
            parts = (callback.get("data") or "").split(":", 2)
            action = parts[1] if len(parts) > 1 else ""
            value = parts[2] if len(parts) > 2 else ""
            if action == "menu":
                self.show_menu()
            elif action == "pending":
                self.show_pending()
            elif action == "users":
                self._show_users(int(value))
            elif action == "revoke":
                self._confirm_revoke(int(value))
            elif action == "revoke_yes":
                self._revoke(int(value))
            elif action == "search":
                self._begin_search()
            elif action == "delete_search":
                self._begin_delete_search()
            elif action == "fetch":
                self._fetch_content(value)
            elif action == "content":
                self._show_content_actions(value)
            elif action == "content_bot":
                self._confirm_content_delete(value, False)
            elif action == "content_group":
                self._confirm_content_delete(value, True)
            elif action == "content_bot_yes":
                self._delete_content_from_bot(value)
            elif action == "content_group_yes":
                self._delete_content_from_group(value)
            elif action == "projects":
                self._show_projects()
            elif action == "analyze":
                self._analyze_content()
            elif action == "topics":
                self._show_projects(int(value))
            elif action == "topic":
                self._show_topic(int(value))
            elif action == "topic_off":
                self._remove_topic_from_bot(int(value))
            elif action == "topic_delete":
                self._confirm_delete_group_topic(int(value))
            elif action == "topic_delete_yes":
                self._delete_group_topic(int(value))
            elif action == "submit":
                self._send("فایل، ویدیو، عکس، صوت یا متن را در همین گفتگوی خصوصی بفرستید. سپس نام و موضوع را انتخاب می‌کنید.")
            elif action == "add_topic":
                self._begin_topic_registration()
            elif action == "existing_topic":
                self._begin_existing_topic_registration()
            elif action == "help":
                self._show_help()
            else:
                raise ValueError("Unknown menu action")
        except (PermissionError, ValueError):
            self._send("این عملیات مجاز نیست یا اطلاعات آن دیگر معتبر نیست.")
        except sqlite3.Error:
            self._send("ثبت تغییر در پایگاه داده کامل نشد. وضعیت موضوع را بررسی کنید.")
        except TelegramError:
            self._send("ارتباط با تلگرام برقرار نشد. کمی بعد دوباره تلاش کنید.")
