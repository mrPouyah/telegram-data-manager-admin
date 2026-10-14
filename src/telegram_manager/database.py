"""SQLite connection and initial schema setup."""

from contextlib import closing
from importlib.resources import files
from pathlib import Path
import sqlite3

SCHEMA_VERSION = 4


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize(path: Path) -> None:
    """Create the initial schema in a new database; refuse unknown versions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, 3, SCHEMA_VERSION):
            raise RuntimeError(f"Unsupported database schema version: {version}")
        if version == SCHEMA_VERSION:
            return
        if version == 1:
            with connection:
                connection.execute(
                    "ALTER TABLE submission_drafts ADD COLUMN "
                    "source_payload TEXT NOT NULL DEFAULT '{}'"
                )
                connection.execute(
                    "ALTER TABLE destinations ADD COLUMN "
                    "deleted_from_group INTEGER NOT NULL DEFAULT 0 "
                    "CHECK (deleted_from_group IN (0, 1))"
                )
                _add_duplicate_indexes(connection)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return
        if version == 2:
            with connection:
                connection.execute(
                    "ALTER TABLE destinations ADD COLUMN "
                    "deleted_from_group INTEGER NOT NULL DEFAULT 0 "
                    "CHECK (deleted_from_group IN (0, 1))"
                )
                _add_duplicate_indexes(connection)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return
        if version == 3:
            with connection:
                _add_duplicate_indexes(connection)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return
        schema = files("telegram_manager").joinpath("schema.sql").read_text(
            encoding="utf-8"
        )
        connection.executescript(
            f"BEGIN;\n{schema}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;"
        )


def _add_duplicate_indexes(connection: sqlite3.Connection) -> None:
    topic_collisions = connection.execute(
        "SELECT count(*) FROM (SELECT chat_id, lower(trim(name)) "
        "FROM destinations WHERE active = 1 AND deleted_from_group = 0 "
        "GROUP BY chat_id, lower(trim(name)) HAVING count(*) > 1)"
    ).fetchone()[0]
    source_collisions = connection.execute(
        "SELECT count(*) FROM (SELECT source_chat_id, source_message_ids "
        "FROM submission_drafts GROUP BY source_chat_id, source_message_ids "
        "HAVING count(*) > 1)"
    ).fetchone()[0]
    if topic_collisions or source_collisions:
        raise RuntimeError(
            "Cannot enable duplicate guards: existing duplicate topic names "
            f"({topic_collisions}) or source messages ({source_collisions})"
        )
    connection.execute(
        "CREATE UNIQUE INDEX active_topic_name_per_group "
        "ON destinations(chat_id, lower(trim(name))) "
        "WHERE active = 1 AND deleted_from_group = 0"
    )
    connection.execute(
        "CREATE UNIQUE INDEX one_draft_per_source_message "
        "ON submission_drafts(source_chat_id, source_message_ids)"
    )
