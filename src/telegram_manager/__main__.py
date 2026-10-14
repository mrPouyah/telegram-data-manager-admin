"""Local setup commands for the project foundation."""

import argparse
import sys

from telegram_manager.config import ConfigurationError, load_database_path, load_settings
from telegram_manager.database import initialize


def main() -> int:
    parser = argparse.ArgumentParser(prog="telegram-manager")
    command = parser.add_subparsers(dest="command", required=True)
    command.add_parser("check-config", help="validate required environment variables")
    command.add_parser("init-db", help="create the initial SQLite database")
    command.add_parser("run", help="run the Telegram access bot using long polling")
    args = parser.parse_args()

    try:
        if args.command == "init-db":
            database_path = load_database_path()
            initialize(database_path)
            print(f"Database ready: {database_path}")
        else:
            settings = load_settings()
            if args.command == "run":
                from telegram_manager.access_bot import AccessBot
                from telegram_manager.catalog_db import CatalogDB
                from telegram_manager.telegram_api import TelegramAPI

                bot = AccessBot(
                    settings,
                    TelegramAPI(settings.bot_token),
                    CatalogDB(settings.database_path, settings.owner_user_id),
                )
                bot.run()
            else:
                print("Configuration is valid")
    except (ConfigurationError, OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
