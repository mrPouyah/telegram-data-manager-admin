# 2026-10-10 — Persistent admin keyboard

## Added

- `src/telegram_manager/admin_panel.py`: persistent Persian reply keyboard with buttons for access requests, approved users, content search, projects, help, and the inline management menu. Text from these buttons is checked against the owner account and group administrator status before acting. A menu choice also cancels an unfinished search.
- `src/telegram_manager/access_bot.py`: `/start` and `/menu` install the reply keyboard for the owner. Later button presses work directly without repeating `/start`.
- `tests/test_access_bot.py`: checks keyboard settings, later button presses, and rejection of admin text from another account.
- `README.md`: updated owner instructions.

## Verified

- All 20 local tests pass using Python 3.13.
- The updated bot was started in the test environment and its Python process was confirmed running.

## Current limits

- Telegram requires the owner to open the bot chat and send `/start` once before the bot can show a private keyboard. The `is_persistent` setting asks Telegram clients to keep it visible; clients may still allow the user to hide it.
- The owner can send `/menu` once after this restart to install the keyboard in the existing private chat. A live button press by the owner has not yet been confirmed.
