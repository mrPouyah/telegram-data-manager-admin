# 2026-10-10 — Test-group access bot

## Added

- `src/telegram_manager/telegram_api.py`: standard-library Bot API client that sends JSON requests without exposing the token in errors.
- `src/telegram_manager/access_bot.py`: private-chat `/start`, `/request`, and `/pending` handling; group-admin checks for bot and owner; owner Approve/Reject buttons.
- `src/telegram_manager/__main__.py`: `run` command for long polling.
- `src/telegram_manager/config.py`: optional ignored `.env` loading with process environment override.
- `src/telegram_manager/catalog_db.py`: user-status and pending-request queries.
- `tests/test_access_bot.py`: fake-Telegram tests for owner verification and access decisions.
- `.env.example` and `README.md`: test-group setup instructions and separate test database path.

## Verified

- All 12 local tests pass with Python 3.13, including local `.env` loading and environment override.
- The later saved credentials were moved from `.env.example` into the ignored `.env` file. `check-config` passed.
- A read-only Telegram check authenticated the bot with `getMe`. `getChatMember` for the configured test group returned `Bad Request: chat not found`, so group and owner admin status remain unverified.
- After the bot was added to the test group, a repeat check confirmed bot status `administrator` and configured owner status `creator`.
- Telegram reported no configured webhook, so long polling is available. The verified owner ID was activated in the local test database.

## Current limits

- Group and owner verification now pass. The bot has not been started for interactive live testing.
- The bot currently manages access approval only. Project permissions, content intake, publishing, and retrieval have no Telegram interface yet.
- Use a separate database when later switching from the test group to the main group.

## Next step

Start the bot and exercise an access request in private chat. After that, build the project/topic configuration and content intake screens.
