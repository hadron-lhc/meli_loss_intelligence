import argparse
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, text

from loss_intelligence.config import get_settings
from loss_intelligence.db.engine import DatabaseTarget, create_engine_for
from loss_intelligence.logging import configure_logging

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MIGRATIONS_DIR = PROJECT_ROOT / "sql"

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    path: Path
    checksum: str


def discover_migrations(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> list[Migration]:
    if not migrations_dir.is_dir():
        raise MigrationError(f"migrations directory not found: {migrations_dir}")

    migrations: list[Migration] = []
    seen: set[str] = set()

    for path in sorted(migrations_dir.glob("*.sql")):
        version, separator, remainder = path.stem.partition("_")
        if not version or not separator or not version.isdigit():
            raise MigrationError(f"invalid migration filename: {path.name}")
        if version in seen:
            raise MigrationError(f"duplicate migration version: {version}")
        seen.add(version)
        migrations.append(
            Migration(
                version=version,
                description=remainder.replace("_", " "),
                path=path,
                checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )

    if not migrations:
        raise MigrationError(f"no migrations found in {migrations_dir}")

    return migrations


def run_migrations(
    engine: Engine,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> list[str]:
    migrations = discover_migrations(migrations_dir)
    applied_versions: list[str] = []

    with engine.begin() as connection:
        connection.exec_driver_sql(SCHEMA_MIGRATIONS_DDL)
        applied = {
            row.version: row.checksum
            for row in connection.execute(text("SELECT version, checksum FROM schema_migrations"))
        }

        for migration in migrations:
            existing_checksum = applied.get(migration.version)
            if existing_checksum is not None:
                if existing_checksum != migration.checksum:
                    raise MigrationError(
                        f"checksum mismatch for migration {migration.version}: "
                        f"database={existing_checksum}, file={migration.checksum}"
                    )
                continue

            logger.info("applying migration %s (%s)", migration.version, migration.path.name)
            connection.exec_driver_sql(migration.path.read_text(encoding="utf-8"))
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (version, description, checksum) "
                    "VALUES (:version, :description, :checksum)"
                ),
                {
                    "version": migration.version,
                    "description": migration.description,
                    "checksum": migration.checksum,
                },
            )
            applied_versions.append(migration.version)

    return applied_versions


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply versioned SQL migrations.")
    parser.add_argument(
        "--database",
        choices=("main", "test"),
        default="main",
        help="target database configuration",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
        help="directory containing versioned .sql migrations",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine_for(settings, args.database)
    target: DatabaseTarget = args.database

    try:
        applied = run_migrations(engine, args.migrations_dir)
        if applied:
            print(f"Applied migrations to {target}: {', '.join(applied)}")
        else:
            print(f"No pending migrations for {target}.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
