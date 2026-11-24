import argparse

from sqlalchemy import Engine

from loss_intelligence.config import get_settings
from loss_intelligence.db.engine import (
    create_engine_for,
    database_name_from_url,
    database_url_for,
)
from loss_intelligence.logging import configure_logging

ALLOWED_RESET_DATABASES = frozenset({"loss_intelligence", "loss_intelligence_test"})

TRUNCATE_SQL = """
TRUNCATE TABLE
    evaluation.synthetic_truth_links,
    evaluation.synthetic_scenarios,
    meta.detection_runs,
    meta.generation_runs,
    investigation_audit,
    anomaly_alert_evidence,
    investigations,
    anomaly_alerts,
    incidents,
    returns,
    shipment_events,
    shipments,
    packaging_types,
    product_categories,
    carriers,
    facilities,
    zones
RESTART IDENTITY CASCADE
"""


class ResetNotAllowed(RuntimeError):
    pass


def validate_reset_request(database_url: str, app_env: str, confirmed: bool) -> str:
    if not confirmed:
        raise ResetNotAllowed("reset requires explicit confirmation (--yes)")
    if app_env == "production":
        raise ResetNotAllowed("reset is never allowed in production")
    database_name = database_name_from_url(database_url)
    if database_name not in ALLOWED_RESET_DATABASES:
        raise ResetNotAllowed(
            f"reset is only allowed for {sorted(ALLOWED_RESET_DATABASES)}, not {database_name!r}"
        )
    return database_name


def reset_operational_data(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(TRUNCATE_SQL)


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely truncate project databases.")
    parser.add_argument(
        "--database",
        choices=("main", "test"),
        default="test",
        help="target database configuration",
    )
    parser.add_argument("--yes", action="store_true", help="confirm destructive reset")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    database_url = database_url_for(settings, args.database)
    database_name = validate_reset_request(database_url, settings.app_env, args.yes)

    engine = create_engine_for(settings, args.database)
    try:
        reset_operational_data(engine)
        print(f"Reset database {database_name}.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
