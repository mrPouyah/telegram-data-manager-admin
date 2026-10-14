# 2026-10-10 — Project foundation

## Completed

- Added a Python package scaffold with a command-line entry point.
- Added validation for the bot token, owner Telegram user ID, group ID, and database path.
- Added SQLite schema version 1 for users, approvals, projects, permissions, topics, categories, drafts, content, attachments, published messages, search text, publication jobs, and audit events.
- Added `check-config` and `init-db` commands and foundation tests.
- Added `.env.example`, `.gitignore`, and local setup instructions.
- Created this progress folder and its record format.

## Verification

- Checked that the files and expected sections exist.
- Python tests and commands could not be run here because this machine's `py` launcher reports no installed Python interpreter. Run the commands in the root README after installing Python 3.11 or newer.

## Current limits

- The bot does not yet connect to Telegram or handle messages.
- The schema is an initial design. Future changes need versioned migrations.
- Attachment bytes are planned to remain in Telegram; independent storage is undecided.

## Next step

Implement owner identity verification and the access-request/approval workflow, then connect the Telegram bot interface. Preserve the planned permission checks at every action.
