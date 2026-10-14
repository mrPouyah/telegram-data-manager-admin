# Telegram Content Manager

Python Telegram bot that organizes approved users' files and text into registered supergroup topics and retrieves saved content by name or unique ID.

## Current state

The bot verifies the configured owner, handles access requests, registers group topics, guides approved users through one-message submissions, publishes the content with a unique ID, saves its details in SQLite, and retrieves saved files or text. See [progress/](progress/) for dated progress records.

## Layout

```text
BOT_PLAN.md                 Product and implementation plan
src/telegram_manager/       Python package, SQLite schema, and catalog operations
tests/                     Foundation tests
progress/                  Dated progress records
.env.example               Required deployment settings example
```

## Local setup

Requires Python 3.11 or newer.

1. Create a virtual environment: `py -3 -m venv .venv` on Windows. If the launcher cannot find Python, invoke your installed `python.exe` directly.
2. Install the package: `.venv\Scripts\python -m pip install -e .`.
3. Create or migrate the database: `.venv\Scripts\python -m telegram_manager init-db`. This step needs no bot token.
4. Copy `.env.example` to `.env` and replace the placeholders. The local `.env` is ignored by Git. Process environment variables override its values.
5. Validate settings: `.venv\Scripts\python -m telegram_manager check-config`.
6. Run the tests: `.venv\Scripts\python -m unittest discover -s tests`.
7. Add the bot to the configured supergroup as an administrator, then run `.venv\Scripts\python -m telegram_manager run`.

8. If you are using an installed Python without an editable package install, run `python run_bot.py run` from the project folder. Keep this process running for the bot to answer messages.
9. Send `/start` to the bot once from the configured owner account. The Persian admin keyboard includes access requests, approved users, content search, registered topics, and sending content. Other users can send `/request`; you approve them with the notification buttons.
10. Register each destination topic from the owner account in the bot's private chat. For a new group topic, tap **ساخت موضوع جدید** and send its name; the bot uses Telegram's returned topic ID. For a topic that already exists, tap **ثبت موضوع موجود**, send a display name, then copy the topic's direct link from Telegram and send it to the bot in the same private chat. Private-group links look like `https://t.me/c/1234567890/42`; public-group links look like `https://t.me/groupname/42`. The General topic uses ID `1` and is supported. A message link is not accepted. The bot checks that the link belongs to the configured group and that it can post to the topic before registering it. Repeat for every topic users may select.
11. An approved user sends text or one file in private chat, supplies a title (or uses the first line of a file caption automatically), selects a registered topic, and confirms the preview. The bot posts a summary with the title, topic, UTC date, and unique `CNT_...` ID, then copies the original content into that topic and catalogs it.
12. The approved user taps **دریافت محتوا**, chooses a registered topic, and sees paged content entries with title, unique ID, and sender. Selecting an item forwards its original group message into private chat. **جستجو و دریافت محتوا** remains available for direct search by ID, title, filename, topic, or saved text. If Telegram cannot forward a message, the bot tries copying it, then its saved text or file reference. If no topic was registered when a new upload was named, the draft remains saved; **ادامه پیش‌نویس** or **تازه‌سازی موضوع‌ها** shows topics registered later. `/cancel` abandons a draft; `/menu` restores the keyboard.
13. The owner can open **موضوع‌های ثبت‌شده** to remove a topic from the bot's upload choices or delete it from the Telegram group. Group deletion asks for confirmation and removes all messages in that topic. The owner can open **حذف محتوا**, search by title or unique ID, and remove an item from the bot's catalog or delete its recorded group posts too; both content actions ask for confirmation.
14. The owner can tap **تحلیل محتوای گروه** for a report based only on content the bot has published and cataloged in the managed group. It counts items by topic and media type, flags repeated titles, items in inactive topics, and missing descriptions, and links flagged items to admin review. The report uses saved metadata; it does not inspect file contents or unrelated group messages.

`TELEGRAM_BOT_TOKEN` is a secret. Keep it out of source control. The SQLite database defaults to `data/telegram_manager.sqlite3`, which is ignored by Git. Schema versions 1–3 migrate to version 4 automatically; back up the database before operational changes.

`MANAGED_GROUP_ID` points to the group the bot manages. Use a separate `DATABASE_PATH` for test and main groups. The bot checks that both the configured owner and bot are administrators in that group before activating the owner. Owner approval grants submission and retrieval across registered topics; revocation blocks later actions. Legacy project-permission records remain in the database but are no longer used as the access gate.

The bot uses Telegram long polling. Run only one process with a given token and remove any existing webhook. Topic registration and user content are handled in private chat.

One message becomes one catalog item. Duplicate topic names in the managed group, repeated source messages, repeated titles in the same topic, and identical files or text already cataloged in the group are rejected before publication. The user sees an error and can send a new title when only the title conflicts. Albums and multi-file batches are not yet supported. Search covers saved metadata and original text; it does not extract text from PDFs, scan images, or transcribe audio. If Telegram delivery is uncertain or only partly succeeds, the bot marks the publication for owner review and does not retry it automatically. If Telegram confirms that the destination topic does not exist before any message was sent, the bot hides that topic and preserves the draft for choosing a corrected destination. Telegram may refuse to delete older individual messages; if only some messages are removed, the bot hides the incomplete content from user search and reports the partial result to the owner.
