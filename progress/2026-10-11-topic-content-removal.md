# 2026-10-11 — Topic and content removal

- `schema.sql` and `database.py`: schema version 3 adds a group-deletion marker to destinations; version 1 and 2 databases migrate forward.
- `catalog_db.py`: owner-only topic listing, bot-only topic removal, group deletion bookkeeping, and content management methods.
- `admin_panel.py`: topic list and action buttons. Bot-only removal immediately hides a destination from user upload choices while preserving Telegram messages. Group deletion has a confirmation screen, calls `deleteForumTopic`, and hides items whose source topic was removed. The **حذف محتوا** button searches by title or unique ID and offers confirmed catalog-only or group-and-catalog removal.
- `access_bot.py`: routes the admin's content-deletion search messages.
- `tests/test_foundation.py` and `tests/test_access_bot.py`: migration, topic removal, group confirmation, content removal, and partial deletion coverage. 36 tests pass locally.

Telegram limits individual message deletion by age and permissions. The bot reports failures; if a group content deletion is partial, it hides that content from user search and keeps the database record for owner review.

The live database was backed up to `data/telegram_manager-before-schema-v3-2026-10-11.sqlite3` and migrated to version 3. Existing topics and published content were preserved. The bot was restarted with the new controls; no live deletion was performed.

The requested group analysis and organisation feature needs a defined first operation. The Bot API does not provide a way to fetch all historical group messages; a future implementation can index new group updates or use an exported history supplied by the owner.
