import pytest
from sqlalchemy import text

from loss_intelligence.db.migrate import run_migrations

pytestmark = pytest.mark.integration


def test_migrations_are_applied_and_idempotent(test_engine) -> None:
    with test_engine.connect() as connection:
        versions = (
            connection.execute(text("SELECT version FROM schema_migrations ORDER BY version"))
            .scalars()
            .all()
        )

    assert versions == ["001", "002", "003", "004"]
    assert run_migrations(test_engine) == []


def test_expected_schema_objects_exist(test_engine) -> None:
    with test_engine.connect() as connection:
        objects = {
            (row.table_schema, row.table_name)
            for row in connection.execute(
                text(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema IN ('public', 'evaluation', 'meta', 'analytics')"
                )
            )
        }

    expected = {
        ("public", "shipments"),
        ("public", "shipment_events"),
        ("public", "incidents"),
        ("public", "returns"),
        ("public", "anomaly_alerts"),
        ("public", "anomaly_alert_evidence"),
        ("public", "investigations"),
        ("public", "investigation_audit"),
        ("public", "event_types"),
        ("evaluation", "synthetic_scenarios"),
        ("evaluation", "synthetic_truth_links"),
        ("meta", "generation_runs"),
        ("meta", "detection_runs"),
        ("analytics", "eligible_shipments"),
        ("analytics", "confirmed_damage_incidents"),
        ("analytics", "daily_metrics"),
        ("analytics", "loss_by_currency_daily"),
        ("analytics", "scope_damage_daily"),
        ("analytics", "data_quality_daily"),
    }
    assert expected <= objects


def test_event_taxonomy_is_seeded(test_engine) -> None:
    with test_engine.connect() as connection:
        event_count = connection.execute(text("SELECT count(*) FROM event_types")).scalar_one()
        damage_codes = (
            connection.execute(
                text(
                    "SELECT event_code FROM event_types "
                    "WHERE event_code IN ('DAMAGE_REPORTED', 'DAMAGE_CONFIRMED') "
                    "ORDER BY event_code"
                )
            )
            .scalars()
            .all()
        )

    assert event_count == 24
    assert damage_codes == ["DAMAGE_CONFIRMED", "DAMAGE_REPORTED"]


def test_session_timezone_is_utc(test_engine) -> None:
    with test_engine.connect() as connection:
        timezone = connection.execute(text("SHOW TIME ZONE")).scalar_one()
    assert timezone == "UTC"


def test_evaluation_truth_is_isolated_from_public_schema(test_engine) -> None:
    with test_engine.connect() as connection:
        public_truth_tables = (
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' "
                    "AND table_name IN ('synthetic_scenarios', 'synthetic_truth_links')"
                )
            )
            .scalars()
            .all()
        )
        evaluation_tables = (
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'evaluation' "
                    "AND table_name IN ('synthetic_scenarios', 'synthetic_truth_links')"
                )
            )
            .scalars()
            .all()
        )

    assert public_truth_tables == []
    assert sorted(evaluation_tables) == ["synthetic_scenarios", "synthetic_truth_links"]


def test_analytics_views_do_not_reference_evaluation_truth(test_engine) -> None:
    with test_engine.connect() as connection:
        views = (
            connection.execute(
                text(
                    "SELECT viewname, definition FROM pg_views "
                    "WHERE schemaname = 'analytics' ORDER BY viewname"
                )
            )
            .mappings()
            .all()
        )

    assert len(views) == 6
    assert all("evaluation." not in row.definition for row in views)


def test_public_tables_have_no_truth_columns(test_engine) -> None:
    forbidden_columns = {
        "is_anomalous",
        "is_damaged_by_injection",
        "scenario_code",
        "scenario_id",
        "scenario_type",
        "truth_role",
        "expected_detection",
    }
    with test_engine.connect() as connection:
        columns = {
            row.column_name
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                )
            )
        }

    assert columns.isdisjoint(forbidden_columns)
