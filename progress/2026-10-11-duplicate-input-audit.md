# 2026-10-11 — Duplicate and input audit

## Findings and changes

- `validation.py`: central label cleanup and matching rules for Persian and Arabic forms, whitespace, case, and file/text identities.
- `catalog_db.py`: duplicate active topic names and re-registering an active topic now fail with an error. Publication rejects a repeated title in the same topic or an identical file/text already cataloged in the managed group. It also checks title length, invalid control characters, message IDs, and attachment/text metadata before inserting.
- `workflow_db.py`: repeated source message IDs cannot make another draft. Publication rechecks existing and in-progress content inside an immediate SQLite transaction, so a duplicate found after preview is still blocked before sending to the group.
- `admin_panel.py` and `access_bot.py`: duplicate topic names are rejected before `createForumTopic` is called and the owner receives a Persian error. The update loop continues after a malformed update instead of stopping the bot.
- `submission_flow.py` and `user_panel.py`: users see Persian duplicate errors. A title conflict can be corrected on the saved draft; an identical file/text is not published. A new file sent while another draft waits is explicitly rejected.
- `schema.sql` and `database.py`: schema version 4 adds unique indexes for active topic names per group and source message references.
- Tests cover duplicate topics, titles, file identities, repeated upload updates, a duplicate appearing after preview, archived content that still has group posts, topic reactivation, and migrations. All 48 tests pass.

## Live database

Backed up `data/telegram_manager.sqlite3` to `data/telegram_manager-before-duplicate-guards-2026-10-11.sqlite3`, then migrated to schema version 4. SQLite integrity check passed and foreign-key check found zero errors. Existing active topic and published item counts were preserved. No live group content was changed.

If an older database already contains duplicate topic names or source-message references, migration now reports aggregate collision counts and leaves that database unchanged for review.

## Limits

The bot can compare Telegram file identities and saved text. It cannot recognize visually similar but different files, and the Bot API cannot enumerate unregistered historical group topics; a new topic may still share a name with a group topic that has never been registered with the bot.

Catalog-only removal keeps the content identity reserved because the group post remains. Successful deletion of all recorded group messages marks the item unavailable, allowing a later upload of the same file. Partial message deletion keeps the identity reserved for review.

Reactivating a bot-only removed topic updates the generated project label with the new topic name. Manually created project names stay unchanged.
