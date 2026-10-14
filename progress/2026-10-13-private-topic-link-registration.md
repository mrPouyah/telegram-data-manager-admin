# 2026-10-13 — Private topic-link registration

- Existing topics are now registered entirely through the owner's private bot chat: select **ثبت موضوع موجود**, send a display name, then send the direct topic link.
- The bot accepts direct `t.me/c/<group>/<topic>` and `t.me/<username>/<topic>` links only. It checks the configured group, confirms it can post to the topic, and then stores the numeric topic ID. It rejects message links, wrong-group links, duplicates, and inaccessible topics.
- `/register_topic` messages in the group no longer register topics. New-topic creation through the owner menu is unchanged.
- Updated the Persian owner guide, README, and plan. All 53 local tests pass with Python 3.13.

Live Telegram registration has not been exercised in this change; the bot must be restarted with the updated code before using the new flow.
