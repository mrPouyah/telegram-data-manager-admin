# 2026-10-11 — Topic publication and retrieval

## Added

- `access_bot.py`: owner-only `/register_topic Name` inside the configured supergroup topic, with group and administrator checks. Private messages and callbacks now route to the user workflow.
- `catalog_db.py`: registered topics and approval-based access to submission and saved content. One registered topic is represented by one catalog project/destination pair in the existing schema.
- `workflow_db.py`, `submission_flow.py`, and `user_panel.py`: persistent one-item drafts, title and topic prompts, preview and confirmation, unique IDs, topic summary and original-message publication, catalog finalization, search, and original-content retrieval.
- `schema.sql` and `database.py`: schema version 2 stores source payloads in drafts and migrates version 1 databases.
- `admin_panel.py`: registered-topic list and owner submission button.
- Tests for migration, complete publication and retrieval, topic authorization, revocation, and uncertain delivery.
- `README.md` and `BOT_PLAN.md`: current instructions and scope.

## Verified

- All 28 local tests pass using Python 3.13.
- The configured database was backed up to `data/telegram_manager-before-topic-flow-2026-10-11.sqlite3` and migrated to schema version 2.
- The updated bot was started for the configured main group, and its Python process was confirmed running.

## Current limits

- One incoming message is one content item. Albums and multi-file batches need a separate workflow.
- Search covers metadata, filenames, and original text; PDF text extraction, OCR, and transcription are not implemented.
- Telegram delivery and SQLite commit cannot be atomic. An uncertain or partial send is marked `needs_review` and requires manual reconciliation; the bot does not blindly resend it.
- Live topic registration, publication, and retrieval require owner and approved-user interaction in Telegram; local tests cover those paths without posting to the main group.
