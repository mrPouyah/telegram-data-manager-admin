# 2026-10-10 — Persian bot interface

## Added

- `src/telegram_manager/access_bot.py`: Persian messages for owner verification, access requests, approvals, rejections, pending requests, revocation, and invalid actions. Approval buttons now read «تأیید» and «رد».
- `tests/test_access_bot.py`: checks Persian verification text and the approval button label.
- `README.md`: notes the Persian interface and the slash commands used to operate it.

## Verified

- All 12 local tests pass using Python 3.13.
- The previous live session was stopped and the updated bot started against the test group. Its process remained running after startup.
- The owner confirmed the restarted bot's live owner-verification reply is in Persian.

## Current limits

- Project configuration, content submission, publication, and retrieval through Telegram remain future work.
- Slash commands remain `/start`, `/request`, and `/pending` while all user-facing responses and approval buttons are Persian.
- No second-account access request has been submitted yet, so the live Approve/Reject path remains to be checked. Local tests cover that path.
