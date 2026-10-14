# 2026-10-10 — Faster approval response

## Finding

The live access request was saved as approved, but the owner reported a long wait after pressing «تأیید». The callback handler used to make multiple Telegram admin-check requests before calling `answerCallbackQuery`, leaving Telegram's button indicator active during those checks.

## Changed

- `src/telegram_manager/access_bot.py`: acknowledge an authorized approval or rejection tap immediately with «در حال بررسی درخواست...», then verify admin status, save the decision, and send a separate Persian result message.
- Cache the bot's own Telegram user ID for the running process so repeated owner checks make one fewer API request.
- `tests/test_access_bot.py`: assert that callback acknowledgment happens before the two group-admin checks.

## Verified

- The existing live request is recorded as approved in the test database.
- All 12 local tests pass.
- The test bot was restarted with the new code and remained running after startup.

## Limit

The improved timing has not yet been confirmed by pressing a new live approval button. A previously approved request cannot be approved a second time.
