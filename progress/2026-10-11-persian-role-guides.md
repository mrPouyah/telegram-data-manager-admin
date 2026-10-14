# 2026-10-11 — Persian user and manager guides

## Completed

- Expanded the existing «راهنما» button in `src/telegram_manager/user_panel.py` into a Persian tutorial for submitting content, choosing a topic, confirming publication, searching and retrieving, resuming or canceling drafts, and upload limits.
- Expanded the manager «راهنما» button in `src/telegram_manager/admin_panel.py` into a Persian tutorial for approving and revoking users, creating or registering topics, removing topics or content, submitting and finding content, and reading the group content report.
- Added a test in `tests/test_access_bot.py` that checks the guide button shows the correct role-specific information.

## Verification

`PYTHONPATH=src python -m unittest discover -s tests` — 49 tests passed.

## Limits and next step

The guides describe current features only. Album uploads remain unsupported, and topics created directly in the group must be registered manually. Next, try both Guide buttons in Telegram after restarting the bot.
