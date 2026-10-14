# 2026-10-13 — General topic registration

- Fixed direct-topic-link parsing to accept topic ID `1`, Telegram's General topic.
- For General, registration and publication send ordinary group messages without `message_thread_id`; catalog records still store topic ID `1`.
- Confirmed that the owner's General-topic link points to the configured forum supergroup.
- Added a full General-topic registration and publication test. All 55 local tests pass with Python 3.13.
