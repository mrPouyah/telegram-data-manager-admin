# 2026-10-10 — Admin menu

## Added

- `src/telegram_manager/admin_panel.py`: Persian owner menu with buttons for pending requests, approved users, revocation confirmation, content search, project list, and help. Search results have buttons that return the selected original content. If a group message cannot be copied, supported attachments are resent using their stored Telegram file ID.
- `src/telegram_manager/access_bot.py`: `/start` and `/menu` open the admin menu; owner text entered after Search is routed to the menu; admin button actions have their own callback route.
- `src/telegram_manager/catalog_db.py`: approved-user listing and lookup. Revocation now removes project grants and item allowlist entries so later approval cannot restore old permissions.
- `tests/test_access_bot.py` and `tests/test_catalog_db.py`: menu, confirmation, authorization, search, content delivery, file-ID fallback, and grant cleanup tests.
- `src/telegram_manager/telegram_api.py` and `access_bot.py`: temporary Telegram connection failures now trigger bounded-delay retries during startup and polling. Invalid token or webhook errors still stop the process.
- `README.md`: updated owner instructions.

## Verified

- All 17 local tests pass using Python 3.13.
- The current test database has one approved non-owner user and no cataloged content items. The live user list can be inspected; live content retrieval needs a published item.

## Current limits

- Content submission and publication are not implemented, so the content menu is wired to an empty live catalog for now.
- The typed search prompt is kept in process memory. If the bot restarts, open Search again.
- The first live menu attempt stopped during a temporary Telegram connection failure. The retry fix has passed local tests; the restarted live session still needs verification.
