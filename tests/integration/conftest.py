import pytest

from loss_intelligence.db.maintenance import TRUNCATE_SQL


@pytest.fixture
def db(test_engine):
    with test_engine.begin() as connection:
        connection.exec_driver_sql(TRUNCATE_SQL)
    return test_engine
