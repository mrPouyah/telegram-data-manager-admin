# 2026-10-13 — Topic content browsing

- Added **دریافت محتوا** to the approved-user and owner keyboards. It opens registered topics, then paged item lists showing title, unique ID, and sender.
- Selecting an item forwards the original group content to private chat. If forwarding fails, delivery falls back to copying, then saved text or Telegram file ID.
- The database query lists only published items in the selected active topic and applies approval and item allowlist rules. The fetch callback rechecks access before delivery.
- Direct text search remains available through **جستجو و دریافت محتوا**.
- All 54 local tests pass with Python 3.13, including browse access checks, revocation, and forwarding fallback. Live Telegram forwarding has not been exercised; the bot must be restarted with the updated code.
