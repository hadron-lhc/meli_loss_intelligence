from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.integration.helpers import (
    BASE_TIME,
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


def test_shipment_requires_existing_destination_zone(db) -> None:
    reference = seed_reference_data(db)
    with pytest.raises(IntegrityError):
        create_shipment(db, reference, destination_zone_id=uuid4())


def test_event_code_must_exist_in_taxonomy(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = create_shipment(db, reference)

    with pytest.raises(IntegrityError):
        with db.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO shipment_events (
                        event_id, shipment_id, event_code, event_name, stage,
                        event_status, occurred_at, recorded_at, facility_id, zone_id,
                        carrier_id, sequence_number, source_system
                    ) VALUES (
                        :event_id, :shipment_id, 'NOT_A_CODE', 'Invalid', 'other',
                        'unknown', :occurred_at, :occurred_at, :facility_id, :zone_id,
                        :carrier_id, 1, 'test_fixture'
                    )
                    """
                ),
                {
                    "event_id": uuid4(),
                    "shipment_id": shipment_id,
                    "occurred_at": BASE_TIME,
                    "facility_id": reference.facility_id,
                    "zone_id": reference.zone_id,
                    "carrier_id": reference.carrier_id,
                },
            )


def test_event_sequence_is_unique_per_shipment(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = create_shipment(db, reference)
    create_event(db, reference, shipment_id, sequence_number=1)

    with pytest.raises(IntegrityError):
        create_event(db, reference, shipment_id, sequence_number=1)


def test_confirmed_incident_requires_confirmed_at(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = create_shipment(db, reference)

    with pytest.raises(IntegrityError):
        create_incident(db, shipment_id, confirmed_at=None)


def test_package_damage_requires_damage_type(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = create_shipment(db, reference)

    with pytest.raises(IntegrityError):
        create_incident(db, shipment_id, damage_type=None)


def test_monetary_amount_requires_currency(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = create_shipment(db, reference)

    with pytest.raises(IntegrityError):
        create_incident(db, shipment_id, currency_code=None)


def test_incident_related_event_must_belong_to_same_shipment(db) -> None:
    reference = seed_reference_data(db)
    first_shipment = create_shipment(db, reference)
    second_shipment = create_shipment(db, reference)
    second_event = create_event(db, reference, second_shipment)

    with pytest.raises(IntegrityError):
        create_incident(db, first_shipment, related_event_id=second_event)


def test_one_active_investigation_per_alert(db) -> None:
    alert_id = create_alert(db)
    create_investigation(db, alert_id=alert_id, status="open")

    with pytest.raises(IntegrityError):
        create_investigation(db, alert_id=alert_id, status="in_review")


def test_truth_link_is_unique_per_scenario_entity(db) -> None:
    scenario_id = create_scenario(db)
    entity_id = uuid4()
    create_truth_link(db, scenario_id, entity_id=entity_id)

    with pytest.raises(IntegrityError):
        create_truth_link(db, scenario_id, entity_id=entity_id)
