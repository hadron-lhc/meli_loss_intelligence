import pytest
from pydantic import ValidationError

from loss_intelligence.config import Settings


def test_defaults_use_local_port_5433() -> None:
    settings = Settings(_env_file=None)
    assert ":5433/" in settings.database_url
    assert ":5433/" in settings.test_database_url
    assert ":5433/" in settings.test_admin_database_url


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level="LOUD")


def test_database_url_requires_psycopg_driver() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql://user:pass@localhost:5432/db",
        )


def test_log_level_is_normalized() -> None:
    settings = Settings(_env_file=None, log_level="debug")
    assert settings.log_level == "DEBUG"
