# 2026-10-11 — Admin topic registration

Update: the link-based registration described below was replaced after a live test showed that a copied message link could be mistaken for a topic link. See [the invalid topic fix](2026-10-11-invalid-topic-fix.md).

## Added

- `src/telegram_manager/admin_panel.py`: **ثبت موضوع** in the admin reply keyboard and inline menu. The owner can paste a link to a topic or a message in that topic, name it, and register it. The link is checked against the configured group and its thread is checked with Telegram before registration.
- `src/telegram_manager/access_bot.py`: routes the owner's registration replies to the admin panel.
- `src/telegram_manager/submission_flow.py` and `user_panel.py`: when an upload has no registered destination, the draft stays saved and offers **تازه‌سازی موضوع‌ها**. The persistent user keyboard also has **ادامه پیش‌نویس**.
- `src/telegram_manager/submission_flow.py`: the first line of a file caption becomes the title for new submissions, so a separate name prompt is unnecessary when the user already named the file in its caption.
- `tests/test_access_bot.py`: verifies a wrong-group link is rejected and a waiting user can resume after the owner registers a topic.
- `README.md`: documents both topic registration paths.
- `run_bot.py`: starts the source checkout from the project folder without installing it into system Python.

## Verified

- All 30 local tests pass using Python 3.13.

## Current limits

- Existing topics must still be registered individually; the bot does not enumerate or automatically sync all supergroup topics.
- A live owner link and resumed user draft have not yet been tested in Telegram.
