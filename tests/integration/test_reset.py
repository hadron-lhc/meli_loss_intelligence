import pytest
from sqlalchemy import text

from loss_intelligence.db.maintenance import reset_operational_data
from tests.integration.helpers import (
    create_alert,
    create_event,
    create_incident,
    create_investigation,
    create_scenario,
    create_shipment,
    create_truth_link,
    seed_reference_data,
)

pytestmark = pytest.mark.integration


def test_reset_clears_operational_and_evaluation_data(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = create_shipment(db, reference)
    create_event(db, reference, shipment_id)
    create_incident(db, shipment_id)
    alert_id = create_alert(db)
    create_investigation(db, alert_id=alert_id)
    scenario_id = create_scenario(db)
    create_truth_link(db, scenario_id, entity_id=shipment_id)

    reset_operational_data(db)

    with db.connect() as connection:
        for table in (
            "zones",
            "facilities",
            "carriers",
            "product_categories",
            "packaging_types",
            "shipments",
            "shipment_events",
            "incidents",
            "anomaly_alerts",
            "anomaly_alert_evidence",
            "investigations",
            "investigation_audit",
            "returns",
            "meta.generation_runs",
            "meta.detection_runs",
            "evaluation.synthetic_scenarios",
            "evaluation.synthetic_truth_links",
        ):
            count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            assert count == 0, table

        event_type_count = connection.execute(text("SELECT count(*) FROM event_types")).scalar_one()

    assert event_type_count == 24
