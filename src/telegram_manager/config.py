"""Validate the deployment configuration without exposing secrets."""

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Mapping


class ConfigurationError(ValueError):
    """A required setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    bot_token: str
    owner_user_id: int
    managed_group_id: int
    database_path: Path


def _local_values() -> Mapping[str, str]:
    """Read an optional ignored .env file; process environment takes priority."""
    values: dict[str, str] = {}
    path = Path(".env")
    if path.exists():
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                raise ConfigurationError(f"Invalid .env entry on line {number}")
            key, value = stripped.split("=", 1)
            key = key.strip()
            if key not in {
                "TELEGRAM_BOT_TOKEN", "OWNER_TELEGRAM_USER_ID",
                "MANAGED_GROUP_ID", "DATABASE_PATH",
            }:
                raise ConfigurationError(f"Unknown .env setting on line {number}")
            values[key] = value.strip().strip('"').strip("'")
    values.update(os.environ)
    return values


def _integer_setting(source: Mapping[str, str], name: str) -> int:
    value = source.get(name, "").strip()
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if parsed == 0:
        raise ConfigurationError(f"{name} cannot be zero")
    return parsed


def load_settings(source: Mapping[str, str] | None = None) -> Settings:
    """Load required values from the process environment or a supplied mapping."""
    values = _local_values() if source is None else source
    token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token == "replace-with-botfather-token":
        raise ConfigurationError("TELEGRAM_BOT_TOKEN is required")

    owner_user_id = _integer_setting(values, "OWNER_TELEGRAM_USER_ID")
    managed_group_id = _integer_setting(values, "MANAGED_GROUP_ID")
    if owner_user_id < 1:
        raise ConfigurationError("OWNER_TELEGRAM_USER_ID must be positive")
    if managed_group_id >= 0:
        raise ConfigurationError("MANAGED_GROUP_ID must be negative")

    return Settings(
        bot_token=token,
        owner_user_id=owner_user_id,
        managed_group_id=managed_group_id,
        database_path=load_database_path(values),
    )


def load_database_path(source: Mapping[str, str] | None = None) -> Path:
    """The database can be initialized before a bot token exists."""
    values = _local_values() if source is None else source
    raw_path = values.get("DATABASE_PATH", "data/telegram_manager.sqlite3").strip()
    if not raw_path:
        raise ConfigurationError("DATABASE_PATH cannot be empty")
    return Path(raw_path)
