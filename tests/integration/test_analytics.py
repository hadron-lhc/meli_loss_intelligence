from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from loss_intelligence.analytics.metrics import (
    SCOPE_TYPES,
    get_data_quality,
    get_loss_by_currency,
    get_overview,
    get_scope_hotspots,
    get_snapshot,
)
from tests.integration.helpers import (
    BASE_TIME,
    create_event,
    create_incident,
    create_shipment,
    seed_reference_data,
)

pytestmark = pytest.mark.integration

DAY_ONE = date(2026, 1, 1)
DAY_TWO = date(2026, 1, 2)


def _eligible_shipment(
    engine,
    reference,
    *,
    created_at: datetime = BASE_TIME,
):
    return create_shipment(
        engine,
        reference,
        created_at=created_at,
        delivered_at=created_at + timedelta(hours=3),
        shipment_status="delivered",
        is_test_record=False,
    )


def test_overview_uses_distinct_shipments_and_created_date_cohort(db) -> None:
    reference = seed_reference_data(db)
    first = _eligible_shipment(db, reference)
    second = _eligible_shipment(db, reference)
    third = _eligible_shipment(db, reference)
    fourth = _eligible_shipment(db, reference)
    _eligible_shipment(db, reference, created_at=BASE_TIME + timedelta(days=1))
    first_event = create_event(db, reference, first)

    create_incident(db, first, related_event_id=first_event, estimated_loss_amount=10)
    create_incident(db, first, related_event_id=first_event, estimated_loss_amount=15)
    create_incident(db, third, incident_status="rejected")
    create_incident(db, fourth, incident_type="package_loss", damage_type=None)
    create_shipment(
        db,
        reference,
        created_at=BASE_TIME,
        delivered_at=BASE_TIME + timedelta(hours=3),
        shipment_status="delivered",
        is_test_record=True,
    )
    create_shipment(
        db,
        reference,
        created_at=BASE_TIME,
        shipment_status="in_transit",
        is_test_record=False,
    )
    create_incident(db, second, incident_status="reported", confirmed_at=None)

    overall = get_overview(db, minimum_volume=1)

    assert overall.start_date == DAY_ONE
    assert overall.end_date == DAY_TWO
    assert overall.eligible_shipments == 5
    assert overall.confirmed_damage_incidents == 2
    assert overall.damage.numerator == 1
    assert overall.damage.denominator == 5
    assert overall.damage.rate == pytest.approx(0.2)
    assert overall.damage.per_1000 == pytest.approx(200.0)
    assert overall.damage.ci_low <= overall.damage.rate <= overall.damage.ci_high
    assert overall.damage.low_volume is False

    first_day = get_overview(db, DAY_ONE, DAY_ONE, minimum_volume=1)

    assert first_day.eligible_shipments == 4
    assert first_day.damage.numerator == 1
    assert first_day.damage.rate == pytest.approx(0.25)


def test_overview_reports_mature_and_immature_cohorts(db) -> None:
    reference = seed_reference_data(db)
    mature_id = _eligible_shipment(db, reference, created_at=BASE_TIME)
    immature_id = _eligible_shipment(
        db,
        reference,
        created_at=BASE_TIME + timedelta(days=20),
    )
    create_incident(db, mature_id)
    create_incident(db, immature_id)

    overview = get_overview(db, minimum_volume=1, maturity_days=14)

    assert overview.eligible_shipments == 2
    assert overview.confirmed_damage_incidents == 2
    assert overview.maturity.maturity_days == 14
    assert overview.maturity.mature_end_date == date(2026, 1, 7)
    assert overview.maturity.mature.denominator == 1
    assert overview.maturity.mature.numerator == 1
    assert overview.maturity.immature.denominator == 1
    assert overview.maturity.immature.numerator == 1
    assert overview.maturity.mature_damage_incidents == 1
    assert overview.maturity.immature_damage_incidents == 1


def test_hotspots_keep_incident_concentration_separate_from_rate(db) -> None:
    reference = seed_reference_data(db)
    first = _eligible_shipment(db, reference)
    second = _eligible_shipment(db, reference)
    third = _eligible_shipment(db, reference)
    fourth = _eligible_shipment(db, reference, created_at=BASE_TIME + timedelta(days=1))
    first_event = create_event(db, reference, first)
    create_event(db, reference, second)
    create_event(db, reference, third)
    create_event(db, reference, fourth)

    create_incident(db, first, related_event_id=first_event, estimated_loss_amount=5)
    create_incident(db, first, related_event_id=first_event, estimated_loss_amount=10)
    create_incident(db, second, estimated_loss_amount=20.50, currency_code="USD")
    create_incident(db, third, estimated_loss_amount=None, currency_code=None)

    facilities = get_scope_hotspots(
        db,
        "facility",
        DAY_ONE,
        DAY_ONE,
        minimum_volume=1,
    )
    assert len(facilities) == 1
    facility = facilities[0]
    assert facility.scope_name == "Test Facility"
    assert facility.eligible_shipments == 3
    assert facility.confirmed_damage_shipments == 1
    assert facility.confirmed_damage_incidents == 2
    assert facility.damage.rate == pytest.approx(1 / 3)
    assert facility.incident_share == pytest.approx(0.5)
    assert facility.damage.low_volume is False

    low_volume = get_scope_hotspots(
        db,
        "facility",
        DAY_ONE,
        DAY_ONE,
        minimum_volume=4,
    )
    assert low_volume[0].damage.low_volume is True

    both_days = get_scope_hotspots(
        db,
        "facility",
        DAY_ONE,
        DAY_TWO,
        minimum_volume=1,
    )
    assert len(both_days) == 1
    assert both_days[0].eligible_shipments == 4
    assert both_days[0].confirmed_damage_shipments == 1
    assert both_days[0].confirmed_damage_incidents == 2

    stages = get_scope_hotspots(
        db,
        "stage",
        DAY_ONE,
        DAY_ONE,
        minimum_volume=1,
    )
    assert len(stages) == 1
    assert stages[0].scope_id == "origin_processing"
    assert stages[0].confirmed_damage_shipments == 1
    assert stages[0].eligible_shipments == 3

    losses = {item.currency_code: item for item in get_loss_by_currency(db, DAY_ONE, DAY_ONE)}
    assert set(losses) == {"ARS", "USD"}
    assert losses["ARS"].confirmed_damage_incidents == 2
    assert losses["ARS"].estimated_loss_amount == Decimal("15.00")
    assert losses["USD"].confirmed_damage_incidents == 1
    assert losses["USD"].estimated_loss_amount == Decimal("20.50")


def test_stage_attribution_falls_back_to_operational_stage(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = _eligible_shipment(db, reference)
    create_event(
        db,
        reference,
        shipment_id,
        event_code="DELIVERED",
        sequence_number=1,
        occurred_at=BASE_TIME,
    )
    damage_event_id = create_event(
        db,
        reference,
        shipment_id,
        event_code="DAMAGE_CONFIRMED",
        sequence_number=2,
        occurred_at=BASE_TIME + timedelta(hours=1),
    )
    create_incident(
        db,
        shipment_id,
        related_event_id=damage_event_id,
        reported_at=BASE_TIME + timedelta(hours=1),
        confirmed_at=BASE_TIME + timedelta(hours=2),
    )

    stages = {
        item.scope_id: item
        for item in get_scope_hotspots(
            db,
            "stage",
            DAY_ONE,
            DAY_ONE,
            minimum_volume=1,
        )
    }

    assert stages["delivery"].confirmed_damage_shipments == 1
    assert stages["other"].confirmed_damage_shipments == 0


def test_data_quality_daily_detects_declared_anomalies(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = _eligible_shipment(db, reference)
    late_event = create_event(
        db,
        reference,
        shipment_id,
        sequence_number=1,
        occurred_at=BASE_TIME,
        recorded_at=BASE_TIME + timedelta(hours=25),
    )
    create_event(
        db,
        reference,
        shipment_id,
        sequence_number=2,
        occurred_at=BASE_TIME,
        recorded_at=BASE_TIME,
    )
    create_event(
        db,
        reference,
        shipment_id,
        sequence_number=3,
        occurred_at=BASE_TIME,
        recorded_at=BASE_TIME - timedelta(hours=1),
    )
    create_event(
        db,
        reference,
        shipment_id,
        event_code="DATA_GAP_DETECTED",
        sequence_number=4,
        occurred_at=BASE_TIME,
        recorded_at=BASE_TIME,
    )

    with db.begin() as connection:
        connection.execute(
            text(
                "UPDATE shipment_events SET facility_id = NULL, carrier_id = NULL "
                "WHERE event_id = :event_id"
            ),
            {"event_id": late_event},
        )
        connection.execute(
            text(
                "UPDATE shipments SET weight_g = NULL, length_mm = NULL, "
                "width_mm = NULL, height_mm = NULL "
                "WHERE shipment_id = :shipment_id"
            ),
            {"shipment_id": shipment_id},
        )

    report = get_data_quality(db, DAY_ONE, DAY_ONE)

    assert report.totals.late_recorded_events == 1
    assert report.totals.timestamp_conflicts == 1
    assert report.totals.duplicate_event_records == 2
    assert report.totals.shipments_with_duplicate_event_codes == 1
    assert report.totals.events_missing_facility == 1
    assert report.totals.events_missing_carrier == 1
    assert report.totals.shipments_missing_dimensions == 1
    assert report.totals.data_gap_events == 1
    assert len(report.daily) == 1
    assert report.daily[0].cohort_date == DAY_ONE


def test_snapshot_includes_every_scope_type(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = _eligible_shipment(db, reference)
    event_id = create_event(db, reference, shipment_id)
    create_incident(db, shipment_id, related_event_id=event_id)

    snapshot = get_snapshot(db, minimum_volume=1, hotspot_limit=5)

    assert snapshot.overview.eligible_shipments == 1
    assert snapshot.overview.damage.rate == 1.0
    assert set(snapshot.hotspots) == set(SCOPE_TYPES)
    assert snapshot.hotspots["facility"][0].scope_id == str(reference.facility_id)
    assert snapshot.loss_by_currency[0].currency_code == "ARS"
    assert snapshot.data_quality.totals.late_recorded_events == 0
