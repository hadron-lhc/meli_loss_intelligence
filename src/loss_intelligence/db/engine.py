import re
from typing import Literal

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url

from loss_intelligence.config import Settings

DatabaseTarget = Literal["main", "test"]

_DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _install_utc_timezone(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_utc_timezone(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET TIME ZONE 'UTC'")
        finally:
            cursor.close()


def database_url_for(settings: Settings, database: DatabaseTarget = "main") -> str:
    return settings.test_database_url if database == "test" else settings.database_url


def database_name_from_url(url: str) -> str:
    name = make_url(url).database
    if not name:
        raise ValueError("database URL does not include a database name")
    return name


def create_engine_for(settings: Settings, database: DatabaseTarget = "main") -> Engine:
    engine = create_engine(
        database_url_for(settings, database),
        pool_pre_ping=True,
        echo=settings.db_echo,
    )
    _install_utc_timezone(engine)
    return engine


def create_admin_engine(settings: Settings) -> Engine:
    engine = create_engine(
        settings.test_admin_database_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    _install_utc_timezone(engine)
    return engine


def ensure_database_exists(settings: Settings, database: DatabaseTarget = "test") -> None:
    database_name = database_name_from_url(database_url_for(settings, database))
    if not _DATABASE_NAME_PATTERN.fullmatch(database_name):
        raise ValueError(f"unsafe database name: {database_name!r}")

    admin_engine = create_admin_engine(settings)
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            ).scalar_one_or_none()
            if exists is None:
                connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        admin_engine.dispose()
