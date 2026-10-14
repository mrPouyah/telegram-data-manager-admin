"""Read direct Telegram forum-topic links supplied by the owner."""

from urllib.parse import urlsplit
import re


def topic_from_link(link: str, managed_group_id: int) -> tuple[int, str | None] | None:
    """Return (topic ID, public username if any) from a direct topic link.

    A copied message link has an additional path component and is deliberately
    rejected: its last number is a message ID, not the topic ID.
    """
    value = link.strip()
    if value.startswith("t.me/"):
        value = "https://" + value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or parsed.hostname not in (
        "t.me", "www.t.me", "telegram.me", "www.telegram.me"
    ) or parsed.query or parsed.fragment or parsed.username or parsed.password:
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) == 3 and parts[0] == "c":
        group, topic = parts[1:]
        if not group.isascii() or not topic.isascii() or not group.isdecimal() or not topic.isdecimal():
            return None
        if managed_group_id != int("-100" + group):
            return None
        username = None
    elif len(parts) == 2 and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", parts[0]):
        username, topic = parts
        if not topic.isascii() or not topic.isdecimal():
            return None
    else:
        return None
    topic_id = int(topic)
    return (topic_id, username) if topic_id > 0 else None
