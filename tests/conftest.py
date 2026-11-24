import re

import pytest
from sqlalchemy.exc import OperationalError

from loss_intelligence.config import Settings
from loss_intelligence.db.engine import (
    create_admin_engine,
    create_engine_for,
    database_name_from_url,
)
from loss_intelligence.db.migrate import run_migrations
from loss_intelligence.synthetic.config import SyntheticDataConfig
from loss_intelligence.synthetic.generator import generate_dataset
from loss_intelligence.synthetic.writer import write_dataset

_SAFE_DB_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _recreate_test_database(settings: Settings) -> None:
    database_name = database_name_from_url(settings.test_database_url)
    if not database_name.endswith("_test") or not _SAFE_DB_NAME.fullmatch(database_name):
        raise RuntimeError(f"refusing to recreate non-test database: {database_name!r}")

    admin_engine = create_admin_engine(settings)
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(app_env="test")


@pytest.fixture(scope="session")
def fixture_dataset():
    return generate_dataset(SyntheticDataConfig.fixture())


@pytest.fixture(scope="session")
def fixture_dataset_dir(tmp_path_factory, fixture_dataset):
    output_root = tmp_path_factory.mktemp("synthetic-datasets")
    return write_dataset(fixture_dataset, output_root).dataset_dir


@pytest.fixture(scope="session")
def test_engine(settings):
    engine = None
    try:
        _recreate_test_database(settings)
        engine = create_engine_for(settings, "test")
        run_migrations(engine)
    except OperationalError as exc:
        if engine is not None:
            engine.dispose()
        pytest.fail(
            "PostgreSQL test database is not reachable. Start it with `make up` "
            f"and verify .env. Original error: {exc}",
            pytrace=False,
        )

    assert engine is not None
    try:
        yield engine
    finally:
        engine.dispose()
