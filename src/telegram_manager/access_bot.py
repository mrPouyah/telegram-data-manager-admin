"""Private-chat owner verification and user access requests."""

import sys
import time
import sqlite3

from telegram_manager.admin_panel import AdminPanel
from telegram_manager.catalog_db import CatalogDB
from telegram_manager.config import Settings
from telegram_manager.telegram_api import TelegramAPI, TelegramError
from telegram_manager.user_panel import UserPanel


class AccessBot:
    def __init__(self, settings: Settings, api: TelegramAPI, database: CatalogDB) -> None:
        self.settings = settings
        self.api = api
        self.database = database
        self._bot_id: int | None = None
        self.admin = AdminPanel(
            settings.owner_user_id, settings.managed_group_id, api,
            database, self.verify_owner, self._show_pending
        )
        self.user_panel = UserPanel(
            api, database, settings.managed_group_id, settings.owner_user_id
        )

    def verify_owner(self) -> None:
        """Check both bot and configured owner in the configured group."""
        if self._bot_id is None:
            self._bot_id = self.api.call("getMe")["id"]
        bot_member = self.api.call(
            "getChatMember", chat_id=self.settings.managed_group_id, user_id=self._bot_id
        )
        owner_member = self.api.call(
            "getChatMember",
            chat_id=self.settings.managed_group_id,
            user_id=self.settings.owner_user_id,
        )
        admins = {"administrator", "creator"}
        if bot_member.get("status") not in admins:
            raise PermissionError("ربات باید مدیر گروه تنظیم‌شده باشد.")
        if owner_member.get("status") not in admins:
            raise PermissionError("شناسه مالک، مدیر گروه تنظیم‌شده نیست.")
        self.database.activate_owner(self.settings.owner_user_id)

    def _send(self, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
        parameters = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            parameters["reply_markup"] = reply_markup
        self.api.call("sendMessage", **parameters)

    @staticmethod
    def _decision_buttons(request_id: int) -> dict:
        return {"inline_keyboard": [[
            {"text": "تأیید", "callback_data": f"access:approve:{request_id}"},
            {"text": "رد", "callback_data": f"access:reject:{request_id}"},
        ]]}

    def _notify_owner(self, request_id: int, user_id: int, name: str, note: str) -> None:
        self._send(
            self.settings.owner_user_id,
            f"درخواست دسترسی شماره {request_id}\nشناسه کاربر: {user_id}\nنام: {name}\nتوضیح: {note}",
            self._decision_buttons(request_id),
        )

    def _show_pending(self) -> None:
        requests = self.database.pending_requests(self.settings.owner_user_id)
        if not requests:
            self._send(self.settings.owner_user_id, "درخواست دسترسی در انتظار بررسی وجود ندارد.")
            return
        for request in requests:
            self._notify_owner(
                request["id"], request["telegram_user_id"],
                request["display_name"] or "نامشخص", request["explanation"] or "ندارد",
            )

    def _handle_private_message(self, message: dict) -> None:
        user = message.get("from") or {}
        user_id = user.get("id")
        chat_id = message.get("chat", {}).get("id")
        if not isinstance(user_id, int) or chat_id != user_id:
            return
        words = (message.get("text") or "").split(maxsplit=1)
        command = words[0].split("@", 1)[0] if words else ""

        if user_id == self.settings.owner_user_id:
            if command in ("/start", "/pending", "/menu"):
                try:
                    self.verify_owner()
                except PermissionError as exc:
                    self._send(chat_id, f"تأیید مدیر انجام نشد: {exc}")
                    return
                except TelegramError:
                    self._send(chat_id, "تأیید مدیر انجام نشد. شناسه گروه و دسترسی ربات را بررسی کنید.")
                    return
                if command == "/pending":
                    self._show_pending()
                else:
                    self._send(
                        chat_id,
                        "هویت شما به‌عنوان مدیر گروه تنظیم‌شده تأیید شد. دکمه‌های مدیریت پایین گفتگو در دسترس هستند.",
                        self.admin.persistent_keyboard(),
                    )
                    self.admin.show_menu()
            else:
                try:
                    owner_text = message.get("text") or ""
                    if (owner_text in ("ارسال محتوا", "دریافت محتوا", "/send", "/cancel")
                            or any(key in message for key in (
                                "document", "photo", "video", "audio", "voice",
                                "animation", "video_note", "sticker",
                            ))):
                        if owner_text == "/send":
                            self.user_panel.handle_menu_text(user_id, "ارسال محتوا")
                        else:
                            self.user_panel.handle_message(user_id, message)
                        return
                    if self.admin.handle_menu_text(message.get("text") or ""):
                        return
                    if self.admin.handle_topic_text(message.get("text") or ""):
                        return
                    if self.admin.handle_delete_search_text(message.get("text") or ""):
                        return
                    if self.admin.handle_search_text(message.get("text") or ""):
                        return
                except (PermissionError, TelegramError, ValueError, sqlite3.Error):
                    self._send(chat_id, "عملیات انجام نشد. دسترسی مدیر و ارتباط با تلگرام را بررسی کنید.")
                    return
                self.user_panel.handle_message(user_id, message)
            return

        status = self.database.user_status(user_id)
        if status == "approved":
            if command in ("/start", "/menu"):
                self.user_panel.show_menu(user_id)
            else:
                self.user_panel.handle_message(user_id, message)
        elif status == "pending":
            self._send(chat_id, "درخواست دسترسی شما در انتظار تأیید مدیر است.")
        elif status == "revoked":
            self._send(chat_id, "دسترسی شما به ربات لغو شده است. با مدیر تماس بگیرید.")
        elif command in ("/start", "/request"):
            request_id = self.database.request_access(
                user_id, display_name=user.get("first_name"),
                username=user.get("username"),
            )
            try:
                self._notify_owner(
                    request_id, user_id, user.get("first_name") or "نامشخص", "ندارد"
                )
                self._send(chat_id, "درخواست دسترسی ثبت شد. مدیر آن را بررسی می‌کند.")
            except TelegramError:
                self._send(
                    chat_id,
                    "درخواست ثبت شد. از مدیر بخواهید ربات را باز کند و /pending را بفرستد.",
                )
        else:
            self._send(chat_id, "برای درخواست دسترسی، /request را بفرستید.")

    def _handle_callback(self, callback: dict) -> None:
        callback_id = callback.get("id")
        user_id = (callback.get("from") or {}).get("id")
        data = callback.get("data") or ""
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        if not callback_id:
            return
        if data.startswith("user:"):
            self.user_panel.handle_callback(callback)
            return
        if data.startswith("admin:"):
            self.admin.handle_callback(callback)
            return
        if user_id != self.settings.owner_user_id or chat.get("id") != user_id:
            self.api.call("answerCallbackQuery", callback_query_id=callback_id, text="فقط مدیر مجاز است.")
            return
        parts = data.split(":")
        if len(parts) != 3 or parts[:2] not in (["access", "approve"], ["access", "reject"]):
            self.api.call("answerCallbackQuery", callback_query_id=callback_id, text="درخواست نامعتبر است.")
            return
        self.api.call(
            "answerCallbackQuery", callback_query_id=callback_id,
            text="در حال بررسی درخواست...",
        )
        try:
            request_id = int(parts[2])
            self.verify_owner()
            pending = {r["id"]: r for r in self.database.pending_requests(user_id)}
            request = pending.get(request_id)
            if request is None:
                raise ValueError("این درخواست قبلاً بررسی شده است.")
            approved = parts[1] == "approve"
            self.database.decide_access(user_id, request_id, approved)
            self._send(
                user_id,
                f"درخواست شماره {request_id} "
                + ("تأیید شد." if approved else "رد شد."),
            )
            try:
                self._send(
                    request["telegram_user_id"],
                    "درخواست دسترسی شما تأیید شد. منوی کاربر پایین گفتگو در دسترس است."
                    if approved else "درخواست دسترسی شما رد شد.",
                    self.user_panel.keyboard() if approved else {"remove_keyboard": True},
                )
            except TelegramError:
                pass  # The decision remains saved if the user blocked the bot.
        except TelegramError:
            self._send(user_id, "بررسی درخواست انجام نشد. ارتباط با تلگرام را دوباره بررسی کنید.")
        except PermissionError:
            self._send(user_id, "بررسی درخواست انجام نشد. دسترسی مدیر تأیید نشد.")
        except ValueError:
            self._send(user_id, "درخواست نامعتبر است یا قبلاً بررسی شده است.")

    def handle_update(self, update: dict) -> None:
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
        elif "message" in update:
            message = update["message"]
            if message.get("chat", {}).get("type") == "private":
                self._handle_private_message(message)

    def run(self) -> None:
        """Consume updates with long polling. Keep one bot process running."""
        while True:
            try:
                self._bot_id = self.api.call("getMe")["id"]
                webhook = self.api.call("getWebhookInfo")
                if webhook.get("url"):
                    raise TelegramError("Remove the existing webhook before using long polling")
                break
            except TelegramError as exc:
                if not exc.retryable:
                    raise
                print("Telegram is temporarily unavailable; retrying.", file=sys.stderr)
                time.sleep(5)
        offset = None
        while True:
            parameters = {"timeout": 25, "allowed_updates": ["message", "callback_query"]}
            if offset is not None:
                parameters["offset"] = offset
            try:
                updates = self.api.call("getUpdates", **parameters)
            except TelegramError as exc:
                if not exc.retryable:
                    raise
                print("Telegram polling was interrupted; retrying.", file=sys.stderr)
                time.sleep(5)
                continue
            for update in updates:
                try:
                    self.handle_update(update)
                except Exception as exc:
                    print(f"Could not handle a Telegram update ({type(exc).__name__}).", file=sys.stderr)
                offset = update["update_id"] + 1
