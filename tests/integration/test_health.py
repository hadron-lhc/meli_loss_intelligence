import pytest

from loss_intelligence.db.engine import database_name_from_url
from loss_intelligence.db.health import get_database_health

pytestmark = pytest.mark.integration


def test_database_health_reports_utc_and_test_database(db, settings) -> None:
    health = get_database_health(db)
    assert health.database == database_name_from_url(settings.test_database_url)
    assert health.timezone == "UTC"
    assert health.server_version.startswith("16.")
