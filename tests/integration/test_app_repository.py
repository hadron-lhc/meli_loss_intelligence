from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from loss_intelligence.app import repository
from tests.integration.helpers import (
    BASE_TIME,
    create_alert,
    create_detection_run,
    create_event,
    create_incident,
    create_scenario,
    create_shipment,
    seed_reference_data,
)

pytestmark = pytest.mark.integration


def _create_return(
    engine,
    shipment_id,
    *,
    declared_reason: str = "damaged",
    inspection_outcome: str = "matches_declaration",
    condition_on_return: str = "damaged",
    initiated_at: datetime | None = None,
):
    return_id = uuid4()
    initiated = initiated_at or (BASE_TIME + timedelta(days=2))
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO returns (
                    return_id, shipment_id, initiated_at, received_at,
                    declared_reason, inspection_outcome, return_status, condition_on_return
                ) VALUES (
                    :return_id, :shipment_id, :initiated_at, :received_at,
                    :declared_reason, :inspection_outcome, 'inspected', :condition_on_return
                )
                """
            ),
            {
                "return_id": return_id,
                "shipment_id": shipment_id,
                "initiated_at": initiated,
                "received_at": initiated + timedelta(days=1),
                "declared_reason": declared_reason,
                "inspection_outcome": inspection_outcome,
                "condition_on_return": condition_on_return,
            },
        )
    return return_id


def test_carrier_zone_hotspots_and_drilldown(db) -> None:
    reference = seed_reference_data(db)
    damaged_id = create_shipment(
        db,
        reference,
        delivered_at=BASE_TIME + timedelta(hours=4),
        shipment_status="delivered",
        is_test_record=False,
    )
    clean_id = create_shipment(
        db,
        reference,
        delivered_at=BASE_TIME + timedelta(hours=5),
        shipment_status="delivered",
        is_test_record=False,
    )
    event_id = create_event(db, reference, damaged_id)
    create_event(db, reference, clean_id)
    create_incident(db, damaged_id, related_event_id=event_id, estimated_loss_amount=50.0)

    scope_id = f"{reference.carrier_id}:{reference.zone_id}"
    create_alert(
        db,
        alert_type="carrier_deviation",
        scope_type="carrier_zone",
        scope_id=scope_id,
    )

    rows = repository.hotspots(
        db,
        "carrier_zone",
        date(2026, 1, 1),
        date(2026, 1, 1),
        minimum_volume=1,
    )
    assert len(rows) == 1
    assert rows[0]["scope_id"] == scope_id
    assert rows[0]["scope_name"] == "Test Carrier / Test Zone"
    assert rows[0]["eligible_shipments"] == 2
    assert rows[0]["confirmed_damage_shipments"] == 1
    assert rows[0]["damage"]["rate"] == pytest.approx(0.5)

    drill = repository.hotspot_drilldown(
        db,
        "carrier_zone",
        scope_id,
        date(2026, 1, 1),
        date(2026, 1, 1),
    )
    assert [row["shipment_id"] for row in drill["shipments"]] == [damaged_id]
    assert len(drill["alerts"]) == 1


def test_hotspot_drilldown_preserves_currency_per_shipment(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = create_shipment(
        db,
        reference,
        delivered_at=BASE_TIME + timedelta(hours=4),
        shipment_status="delivered",
        is_test_record=False,
    )
    event_id = create_event(db, reference, shipment_id)
    create_incident(
        db,
        shipment_id,
        related_event_id=event_id,
        estimated_loss_amount=10.0,
        currency_code="ARS",
    )
    create_incident(
        db,
        shipment_id,
        related_event_id=event_id,
        estimated_loss_amount=5.0,
        currency_code="ARS",
    )
    create_incident(
        db,
        shipment_id,
        related_event_id=event_id,
        estimated_loss_amount=20.0,
        currency_code="USD",
    )

    drill = repository.hotspot_drilldown(
        db,
        "facility",
        str(reference.facility_id),
        date(2026, 1, 1),
        date(2026, 1, 1),
    )

    assert len(drill["shipments"]) == 1
    shipment = drill["shipments"][0]
    assert shipment["shipment_id"] == shipment_id
    assert shipment["incident_count"] == 3
    losses = {
        item["currency_code"]: float(item["estimated_loss_amount"])
        for item in shipment["loss_by_currency"]
    }
    assert losses == {"ARS": 15.0, "USD": 20.0}


def test_alert_evidence_triage_and_investigation_lifecycle(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = create_shipment(
        db,
        reference,
        delivered_at=BASE_TIME + timedelta(hours=4),
        shipment_status="returned",
        is_test_record=False,
    )
    event_id = create_event(db, reference, shipment_id, event_code="DELIVERED")
    incident_id = create_incident(db, shipment_id, related_event_id=event_id)
    return_id = _create_return(
        db,
        shipment_id,
        declared_reason="wrong_item",
        inspection_outcome="does_not_match_declaration",
    )
    alert_id = create_alert(db, scope_type="facility", scope_id=str(reference.facility_id))

    with db.begin() as connection:
        for entity_type, entity_id in (
            ("shipment", shipment_id),
            ("incident", incident_id),
            ("return", return_id),
            ("event", event_id),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO anomaly_alert_evidence (
                        alert_id, entity_type, entity_id, evidence_role
                    ) VALUES (:alert_id, :entity_type, :entity_id, 'primary')
                    """
                ),
                {"alert_id": alert_id, "entity_type": entity_type, "entity_id": entity_id},
            )

    evidence = repository.alert_evidence(db, alert_id)
    assert len(evidence) == 4
    assert all(row["shipment_id"] == shipment_id for row in evidence)
    assert any(row["return_declared_reason"] == "wrong_item" for row in evidence)
    assert any(row["event_code"] == "DELIVERED" for row in evidence)

    repository.update_alert_status(db, alert_id, status="acknowledged")
    assert repository.get_alert(db, alert_id)["status"] == "acknowledged"

    inv_id = repository.create_investigation(db, alert_id)
    assert repository.get_alert(db, alert_id)["status"] == "investigating"

    with pytest.raises(ValueError, match="active investigation"):
        repository.update_alert_status(db, alert_id, status="dismissed")

    with pytest.raises(ValueError, match="require an outcome"):
        repository.update_investigation(
            db,
            inv_id,
            status="closed",
            outcome=None,
            notes="missing outcome",
            recommended_action=None,
        )

    repository.update_investigation(
        db,
        inv_id,
        status="closed",
        outcome="confirmed_issue",
        notes="verified",
        recommended_action="audit carrier",
    )
    assert repository.get_alert(db, alert_id)["status"] == "resolved"
    audit = repository.investigation_audit(db, inv_id)
    assert [row["to_status"] for row in audit] == ["open", "closed"]

    # Reopening succeeds when no other active investigation exists; creating another + reopening
    # converts the unique-index IntegrityError into a ValueError.
    second_inv = repository.create_investigation(db, alert_id)
    with pytest.raises(ValueError, match="active investigation"):
        repository.update_investigation(
            db,
            inv_id,
            status="open",
            outcome=None,
            notes="reopen conflict",
            recommended_action=None,
        )
    assert second_inv != inv_id


def test_shipment_filters_returns_summary_and_validation_window(db) -> None:
    reference = seed_reference_data(db)
    returned_id = create_shipment(
        db,
        reference,
        delivered_at=BASE_TIME + timedelta(hours=3),
        shipment_status="returned",
        is_test_record=False,
    )
    clean_id = create_shipment(
        db,
        reference,
        delivered_at=BASE_TIME + timedelta(hours=4),
        shipment_status="delivered",
        is_test_record=False,
    )
    event_id = create_event(db, reference, returned_id, event_code="PICKED_UP", sequence_number=1)
    create_incident(db, returned_id, related_event_id=event_id)
    _create_return(
        db,
        returned_id,
        declared_reason="damaged",
        inspection_outcome="does_not_match_declaration",
    )
    _create_return(
        db,
        returned_id,
        declared_reason="other",
        inspection_outcome="matches_declaration",
        initiated_at=BASE_TIME + timedelta(days=3),
    )

    damaged = repository.shipment_search(db, None, damaged_only=True)
    assert [row["shipment_id"] for row in damaged] == [returned_id]
    delivered = repository.shipment_search(db, None, status="delivered")
    assert [row["shipment_id"] for row in delivered] == [clean_id]

    incidents = repository.shipment_incidents(db, returned_id)
    assert incidents[0]["related_event_code"] == "PICKED_UP"
    assert len(repository.shipment_returns(db, returned_id)) == 2

    summary = repository.returns_summary(db, date(2026, 1, 1), date(2026, 1, 1))
    assert summary["totals"]["shipments_with_return"] == 1
    assert summary["totals"]["repeat_shipments"] == 1
    assert summary["totals"]["discrepancy_returns"] == 1
    assert summary["by_category"][0]["category_name"] == "Test Category"
    assert summary["flagged_shipments"][0]["shipment_id"] == returned_id

    run_id = create_detection_run(db)
    create_scenario(
        db,
        split="validation",
        start_at=datetime(2026, 3, 1, tzinfo=UTC),
        end_at=datetime(2026, 3, 15, tzinfo=UTC),
        affected_entity_id=str(reference.facility_id),
    )
    val_win = repository.validation_window(db)
    assert val_win is not None
    assert val_win["start_at"] == datetime(2026, 3, 1, tzinfo=UTC)
    assert len(repository.detection_runs(db)) == 1
    assert repository.evaluation_summary(db, detection_run_id=run_id, k=5)["total_alerts"] == 0
