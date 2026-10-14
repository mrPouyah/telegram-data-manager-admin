# 2026-10-11 — Separate admin topic buttons

- `src/telegram_manager/admin_panel.py`: the owner now has separate **ساخت موضوع جدید** and **ثبت موضوع موجود** buttons in both admin keyboards. New topics are created through Telegram. For existing topics, the bot asks for a display name and gives the exact `/register_topic Name` command to send inside the existing topic; the group message provides the trustworthy thread ID.
- `tests/test_access_bot.py`: verifies the existing-topic button and subsequent group registration, without creating another topic.
- `README.md`: documents both paths.

The bot cannot enumerate historical topics through the Bot API, so an existing topic still needs one message from the owner inside that topic.
