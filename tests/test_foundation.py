"""Small checks for the foundation's real boundaries."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from telegram_manager.config import ConfigurationError, load_settings
from telegram_manager.database import connect, initialize


class SettingsTests(unittest.TestCase):
    def test_valid_settings(self) -> None:
        settings = load_settings(
            {
                "TELEGRAM_BOT_TOKEN": "example-token",
                "OWNER_TELEGRAM_USER_ID": "123",
                "MANAGED_GROUP_ID": "-100456",
                "DATABASE_PATH": "data/example.sqlite3",
            }
        )
        self.assertEqual(settings.owner_user_id, 123)
        self.assertEqual(settings.managed_group_id, -100456)
        self.assertEqual(settings.database_path, Path("data/example.sqlite3"))

    def test_missing_token_and_invalid_owner_are_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_settings({"OWNER_TELEGRAM_USER_ID": "123", "MANAGED_GROUP_ID": "-100456"})
        with self.assertRaises(ConfigurationError):
            load_settings(
                {
                    "TELEGRAM_BOT_TOKEN": "example-token",
                    "OWNER_TELEGRAM_USER_ID": "-123",
                    "MANAGED_GROUP_ID": "-100456",
                }
            )

    def test_local_env_file_and_process_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_directory = Path.cwd()
            try:
                os.chdir(directory)
                Path(".env").write_text(
                    "TELEGRAM_BOT_TOKEN=local-token\n"
                    "OWNER_TELEGRAM_USER_ID=123\n"
                    "MANAGED_GROUP_ID=-100456\n",
                    encoding="utf-8",
                )
                with patch.dict(os.environ, {"OWNER_TELEGRAM_USER_ID": "789"}, clear=True):
                    settings = load_settings()
            finally:
                os.chdir(original_directory)
            self.assertEqual(settings.bot_token, "local-token")
            self.assertEqual(settings.owner_user_id, 789)


class DatabaseTests(unittest.TestCase):
    def test_initialization_is_repeatable_and_enforces_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "manager.sqlite3"
            initialize(path)
            initialize(path)
            with closing(connect(path)) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                self.assertEqual(version, 4)
                self.assertTrue(connection.execute("PRAGMA foreign_keys").fetchone()[0])
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO project_permissions (telegram_user_id, project_id) VALUES (?, ?)",
                        (999, 999),
                    )

    def test_v1_database_is_migrated_without_losing_users(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            initialize(path)
            with closing(connect(path)) as connection, connection:
                connection.execute("INSERT INTO users (telegram_user_id, status) VALUES (42, 'approved')")
                connection.execute("DROP INDEX active_topic_name_per_group")
                connection.execute("DROP INDEX one_draft_per_source_message")
                connection.execute("ALTER TABLE submission_drafts DROP COLUMN source_payload")
                connection.execute("ALTER TABLE destinations DROP COLUMN deleted_from_group")
                connection.execute("PRAGMA user_version = 1")
            initialize(path)
            with closing(connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
                self.assertIsNotNone(connection.execute(
                    "SELECT 1 FROM users WHERE telegram_user_id = 42"
                ).fetchone())
                columns = [row[1] for row in connection.execute(
                    "PRAGMA table_info(submission_drafts)"
                )]
                self.assertIn("source_payload", columns)
                destination_columns = [row[1] for row in connection.execute(
                    "PRAGMA table_info(destinations)"
                )]
                self.assertIn("deleted_from_group", destination_columns)

    def test_v2_database_adds_group_deletion_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v2.sqlite3"
            initialize(path)
            with closing(connect(path)) as connection, connection:
                connection.execute("DROP INDEX active_topic_name_per_group")
                connection.execute("DROP INDEX one_draft_per_source_message")
                connection.execute("ALTER TABLE destinations DROP COLUMN deleted_from_group")
                connection.execute("PRAGMA user_version = 2")
            initialize(path)
            with closing(connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
                columns = [row[1] for row in connection.execute(
                    "PRAGMA table_info(destinations)"
                )]
                self.assertIn("deleted_from_group", columns)

    def test_v3_database_adds_duplicate_guards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v3.sqlite3"
            initialize(path)
            with closing(connect(path)) as connection, connection:
                connection.execute("DROP INDEX active_topic_name_per_group")
                connection.execute("DROP INDEX one_draft_per_source_message")
                connection.execute("PRAGMA user_version = 3")
            initialize(path)
            with closing(connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
                indexes = {row[1] for row in connection.execute("PRAGMA index_list(destinations)")}
                self.assertIn("active_topic_name_per_group", indexes)
                draft_indexes = {row[1] for row in connection.execute("PRAGMA index_list(submission_drafts)")}
                self.assertIn("one_draft_per_source_message", draft_indexes)

    def test_migration_reports_existing_topic_duplicates_without_changing_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicates.sqlite3"
            initialize(path)
            with closing(connect(path)) as connection, connection:
                connection.execute("DROP INDEX active_topic_name_per_group")
                connection.execute("DROP INDEX one_draft_per_source_message")
                connection.execute(
                    "INSERT INTO destinations (chat_id, topic_id, name) "
                    "VALUES (-100123, 42, 'Plans'), (-100123, 43, ' plans ')"
                )
                connection.execute("PRAGMA user_version = 3")
            with self.assertRaisesRegex(RuntimeError, "duplicate topic names"):
                initialize(path)
            with closing(connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT count(*) FROM destinations").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
