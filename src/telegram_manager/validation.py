"""Canonical labels and duplicate identities used at input and database boundaries."""

from dataclasses import dataclass
import unicodedata


_ARABIC_FORMS = str.maketrans({"ي": "ی", "ك": "ک"})


@dataclass(frozen=True)
class DuplicateContentError(ValueError):
    reason: str
    existing_id: str | None = None


def clean_label(value: str, maximum: int) -> str:
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Name contains invalid characters")
    label = " ".join(unicodedata.normalize("NFKC", value).translate(_ARABIC_FORMS).split())
    if not label or len(label) > maximum:
        raise ValueError(f"Name must be 1–{maximum} characters")
    return label


def label_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).translate(_ARABIC_FORMS).split()).casefold()


def text_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).replace("\r\n", "\n").strip().casefold()


def payload_identity(payload: dict) -> tuple[str, str] | None:
    media_type = payload.get("media_type")
    if media_type == "text":
        body = payload.get("text") or ""
        return ("text", text_key(body)) if body.strip() else None
    if not media_type:
        return None
    file_key = payload.get("file_unique_id") or payload.get("file_id")
    return (media_type, file_key) if file_key else None
