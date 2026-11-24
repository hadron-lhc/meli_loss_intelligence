import argparse
from dataclasses import dataclass

from sqlalchemy import Engine, text

from loss_intelligence.config import get_settings
from loss_intelligence.db.engine import create_engine_for
from loss_intelligence.logging import configure_logging


@dataclass(frozen=True)
class DatabaseHealth:
    database: str
    timezone: str
    server_version: str


def get_database_health(engine: Engine) -> DatabaseHealth:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT current_database(), current_setting('TimeZone'), "
                "current_setting('server_version')"
            )
        ).one()
    return DatabaseHealth(database=row[0], timezone=row[1], server_version=row[2])


def main() -> None:
    parser = argparse.ArgumentParser(description="Check database connectivity and timezone.")
    parser.add_argument(
        "--database",
        choices=("main", "test"),
        default="main",
        help="target database configuration",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine_for(settings, args.database)
    try:
        health = get_database_health(engine)
        print(
            f"database={health.database} timezone={health.timezone} "
            f"server_version={health.server_version}"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
