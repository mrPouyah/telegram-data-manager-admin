# 2026-10-11 — Cataloged content analysis

- `catalog_db.py`: added an owner-only read of topics and content recorded by the bot in the configured group. It excludes unrelated group messages and other groups.
- `admin_panel.py`: added **تحلیل محتوای گروه** to both admin menus. The report counts active items by topic and media type, flags duplicate titles, content tied to inactive topics, and missing descriptions, with buttons to review flagged items.
- `tests/test_access_bot.py`: verifies group scoping, counts, issue flags, and review buttons. 37 local tests pass.
- `README.md`: documents report scope.

This first analysis uses catalog metadata. It does not inspect media bytes or move existing Telegram posts. The admin can use the linked review and deletion controls to decide what to change.
