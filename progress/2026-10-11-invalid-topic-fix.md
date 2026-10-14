# 2026-10-11 — Invalid topic publication fix

## Finding

Two test publications failed before sending any group message with Telegram's `message thread not found` error. The admin link flow had accepted a message ID as though it were a topic ID. Buttons worked, but the saved destination was invalid.

## Changes

- `admin_panel.py`: **ساخت موضوع جدید** asks for a name, calls `createForumTopic`, and saves the topic ID returned by Telegram. Existing topics are registered with `/register_topic Name` sent inside the topic.
- `catalog_db.py`, `workflow_db.py`, and `submission_flow.py`: if Telegram rejects a missing topic before any group message is sent, hide that destination and restore the user's draft to topic selection.
- `tests/test_access_bot.py`: checks topic creation and invalid-topic draft recovery. All 31 tests pass.
- `README.md`: explains the corrected admin steps.

## Live data repair

Backed up the database to `data/telegram_manager-before-invalid-topic-repair-2026-10-11.sqlite3`. Disabled the invalid destination and restored the latest unsent test draft to topic selection. An older failed draft remains in the review record. No content item was published by these attempts.

## Next live step

The owner must create a new topic with the admin button or register an existing topic from inside that topic. The user can then tap **ادامه پیش‌نویس**, select the topic, and confirm publication.
