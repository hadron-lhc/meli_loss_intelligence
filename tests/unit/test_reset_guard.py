import pytest

from loss_intelligence.config import DEFAULT_DATABASE_URL, DEFAULT_TEST_DATABASE_URL
from loss_intelligence.db.maintenance import ResetNotAllowed, validate_reset_request


def test_reset_allows_project_databases() -> None:
    assert (
        validate_reset_request(DEFAULT_DATABASE_URL, "local", confirmed=True) == "loss_intelligence"
    )
    assert (
        validate_reset_request(DEFAULT_TEST_DATABASE_URL, "test", confirmed=True)
        == "loss_intelligence_test"
    )


def test_reset_requires_explicit_confirmation() -> None:
    with pytest.raises(ResetNotAllowed, match="explicit confirmation"):
        validate_reset_request(DEFAULT_TEST_DATABASE_URL, "test", confirmed=False)


def test_reset_rejects_unrelated_database() -> None:
    unrelated = "postgresql+psycopg://user:pass@localhost:5432/olist_analytics"
    with pytest.raises(ResetNotAllowed, match="reset is only allowed"):
        validate_reset_request(unrelated, "local", confirmed=True)


def test_reset_rejects_postgres_database() -> None:
    postgres = "postgresql+psycopg://user:pass@localhost:5432/postgres"
    with pytest.raises(ResetNotAllowed, match="reset is only allowed"):
        validate_reset_request(postgres, "local", confirmed=True)


def test_reset_rejects_production_environment() -> None:
    with pytest.raises(ResetNotAllowed, match="production"):
        validate_reset_request(DEFAULT_DATABASE_URL, "production", confirmed=True)
