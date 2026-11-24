import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

BASE_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class ReferenceData:
    zone_id: UUID
    facility_id: UUID
    carrier_id: UUID
    product_category_id: UUID
    packaging_type_id: UUID


def seed_reference_data(engine: Engine) -> ReferenceData:
    ids = ReferenceData(
        zone_id=uuid4(),
        facility_id=uuid4(),
        carrier_id=uuid4(),
        product_category_id=uuid4(),
        packaging_type_id=uuid4(),
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO zones (zone_id, zone_code, zone_name, region, country_code) "
                "VALUES (:zone_id, 'TEST-ZONE', 'Test Zone', 'Test Region', 'AR')"
            ),
            {"zone_id": ids.zone_id},
        )
        connection.execute(
            text(
                "INSERT INTO facilities "
                "(facility_id, facility_code, facility_name, facility_type, zone_id, active_from) "
                "VALUES (:facility_id, 'TEST-FAC', 'Test Facility', 'last_mile_hub', "
                ":zone_id, :active_from)"
            ),
            {
                "facility_id": ids.facility_id,
                "zone_id": ids.zone_id,
                "active_from": date(2026, 1, 1),
            },
        )
        connection.execute(
            text(
                "INSERT INTO carriers "
                "(carrier_id, carrier_code, carrier_name, carrier_type, active_from) "
                "VALUES (:carrier_id, 'TEST-CARRIER', 'Test Carrier', 'third_party', "
                ":active_from)"
            ),
            {"carrier_id": ids.carrier_id, "active_from": date(2026, 1, 1)},
        )
        connection.execute(
            text(
                "INSERT INTO product_categories "
                "(product_category_id, category_code, category_name, fragility_class) "
                "VALUES (:category_id, 'TEST-CAT', 'Test Category', 'high')"
            ),
            {"category_id": ids.product_category_id},
        )
        connection.execute(
            text(
                "INSERT INTO packaging_types "
                "(packaging_type_id, packaging_code, packaging_name, protection_level) "
                "VALUES (:packaging_id, 'TEST-PACK', 'Test Packaging', 'medium')"
            ),
            {"packaging_id": ids.packaging_type_id},
        )
    return ids


def create_shipment(
    engine: Engine,
    reference: ReferenceData,
    *,
    shipment_id: UUID | None = None,
    shipment_code: str | None = None,
    destination_zone_id: UUID | None = None,
    shipment_status: str = "in_transit",
    created_at: datetime | None = None,
    delivered_at: datetime | None = None,
    is_test_record: bool = True,
) -> UUID:
    shipment_id = shipment_id or uuid4()
    shipment_code = shipment_code or f"SHP-{shipment_id.hex[:12].upper()}"
    created_at = created_at or BASE_TIME
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO shipments (
                    shipment_id, shipment_code, created_at, dispatched_at, delivered_at,
                    origin_facility_id, destination_zone_id, carrier_id,
                    product_category_id, packaging_type_id, weight_g,
                    length_mm, width_mm, height_mm, declared_value, currency_code,
                    shipment_status, is_test_record, created_record_at
                ) VALUES (
                    :shipment_id, :shipment_code, :created_at, :dispatched_at, :delivered_at,
                    :facility_id, :zone_id, :carrier_id,
                    :category_id, :packaging_id, 1500,
                    200, 150, 100, 25.00, 'ARS',
                    :shipment_status, :is_test_record, :created_at
                )
                """
            ),
            {
                "shipment_id": shipment_id,
                "shipment_code": shipment_code,
                "created_at": created_at,
                "dispatched_at": created_at + timedelta(hours=1),
                "delivered_at": delivered_at,
                "facility_id": reference.facility_id,
                "zone_id": destination_zone_id or reference.zone_id,
                "carrier_id": reference.carrier_id,
                "category_id": reference.product_category_id,
                "packaging_id": reference.packaging_type_id,
                "shipment_status": shipment_status,
                "is_test_record": is_test_record,
            },
        )
    return shipment_id


def create_event(
    engine: Engine,
    reference: ReferenceData,
    shipment_id: UUID,
    *,
    event_id: UUID | None = None,
    event_code: str = "PICKED_UP",
    sequence_number: int = 1,
    occurred_at: datetime | None = None,
    recorded_at: datetime | None = None,
) -> UUID:
    event_id = event_id or uuid4()
    occurred_at = occurred_at or BASE_TIME
    recorded_at = recorded_at or occurred_at
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                INSERT INTO shipment_events (
                    event_id, shipment_id, event_code, event_name, stage, event_status,
                    occurred_at, recorded_at, facility_id, zone_id, carrier_id,
                    sequence_number, source_system
                )
                SELECT
                    :event_id, :shipment_id, et.event_code, et.event_name, et.stage,
                    et.event_status, :occurred_at, :recorded_at, :facility_id, :zone_id,
                    :carrier_id, :sequence_number, 'test_fixture'
                FROM event_types et
                WHERE et.event_code = :event_code
                """
            ),
            {
                "event_id": event_id,
                "shipment_id": shipment_id,
                "event_code": event_code,
                "occurred_at": occurred_at,
                "recorded_at": recorded_at,
                "facility_id": reference.facility_id,
                "zone_id": reference.zone_id,
                "carrier_id": reference.carrier_id,
                "sequence_number": sequence_number,
            },
        )
        if result.rowcount != 1:
            raise AssertionError(f"unknown event code in fixture: {event_code}")
    return event_id


def create_incident(
    engine: Engine,
    shipment_id: UUID,
    *,
    incident_id: UUID | None = None,
    related_event_id: UUID | None = None,
    incident_type: str = "package_damage",
    damage_type: str | None = "crushed",
    severity: str = "low",
    reported_at: datetime | None = None,
    confirmed_at: datetime | None = BASE_TIME + timedelta(hours=2),
    incident_status: str = "confirmed",
    estimated_loss_amount: float | None = 10.00,
    currency_code: str | None = "ARS",
    evidence_type: str = "inspection",
) -> UUID:
    incident_id = incident_id or uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO incidents (
                    incident_id, shipment_id, related_event_id, incident_type, damage_type,
                    severity, reported_at, confirmed_at, incident_status,
                    estimated_loss_amount, currency_code, evidence_type, notes, created_at
                ) VALUES (
                    :incident_id, :shipment_id, :related_event_id, :incident_type,
                    :damage_type, :severity, :reported_at, :confirmed_at, :incident_status,
                    :estimated_loss_amount, :currency_code, :evidence_type,
                    'test fixture', :created_at
                )
                """
            ),
            {
                "incident_id": incident_id,
                "shipment_id": shipment_id,
                "related_event_id": related_event_id,
                "incident_type": incident_type,
                "damage_type": damage_type,
                "severity": severity,
                "reported_at": reported_at or BASE_TIME,
                "confirmed_at": confirmed_at,
                "incident_status": incident_status,
                "estimated_loss_amount": estimated_loss_amount,
                "currency_code": currency_code,
                "evidence_type": evidence_type,
                "created_at": BASE_TIME,
            },
        )
    return incident_id


def create_alert(
    engine: Engine,
    *,
    alert_id: UUID | None = None,
    alert_type: str = "damage_rate_spike",
    scope_type: str = "facility",
    scope_id: str | None = None,
    observed_start: datetime | None = None,
    observed_end: datetime | None = None,
    priority: str = "high",
    explanation: str = "test alert",
    model_name: str = "statistical_rules",
    model_version: str = "test-v1",
    status: str = "new",
    detection_run_id: UUID | None = None,
) -> UUID:
    alert_id = alert_id or uuid4()
    observed_start = observed_start or BASE_TIME
    observed_end = observed_end or BASE_TIME + timedelta(days=1)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO anomaly_alerts (
                    alert_id, alert_type, scope_type, scope_id, observed_start, observed_end,
                    baseline_start, baseline_end, observed_numerator, observed_denominator,
                    observed_rate, baseline_rate, anomaly_score, priority, explanation,
                    model_name, model_version, status, generated_at, detection_run_id
                ) VALUES (
                    :alert_id, :alert_type, :scope_type, :scope_id, :observed_start, :observed_end,
                    :baseline_start, :baseline_end, 5, 1000,
                    0.005000, 0.002000, 2.500000, :priority, :explanation,
                    :model_name, :model_version, :status, :generated_at, :detection_run_id
                )
                """
            ),
            {
                "alert_id": alert_id,
                "alert_type": alert_type,
                "scope_type": scope_type,
                "scope_id": scope_id or str(uuid4()),
                "observed_start": observed_start,
                "observed_end": observed_end,
                "baseline_start": observed_start - timedelta(days=30),
                "baseline_end": observed_start,
                "priority": priority,
                "explanation": explanation,
                "model_name": model_name,
                "model_version": model_version,
                "status": status,
                "generated_at": observed_end,
                "detection_run_id": detection_run_id,
            },
        )
    return alert_id


def create_detection_run(
    engine: Engine,
    *,
    detection_run_id: UUID | None = None,
    dataset_generation_run_id: UUID | None = None,
    model_name: str = "statistical_rules",
    model_version: str = "test-v1",
    status: str = "completed",
) -> UUID:
    detection_run_id = detection_run_id or uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO meta.detection_runs (
                    detection_run_id, dataset_generation_run_id, model_name, model_version,
                    config, config_hash, status, completed_at
                ) VALUES (
                    :detection_run_id, :dataset_generation_run_id, :model_name, :model_version,
                    CAST(:config AS JSONB), :config_hash, :status, NOW()
                )
                """
            ),
            {
                "detection_run_id": detection_run_id,
                "dataset_generation_run_id": dataset_generation_run_id,
                "model_name": model_name,
                "model_version": model_version,
                "config": json.dumps({"test": True}),
                "config_hash": "test-hash",
                "status": status,
            },
        )
    return detection_run_id


def create_investigation(
    engine: Engine,
    *,
    investigation_id: UUID | None = None,
    alert_id: UUID | None = None,
    incident_id: UUID | None = None,
    status: str = "open",
    outcome: str | None = None,
    reviewer_label: str = "demo_reviewer",
    opened_at: datetime | None = None,
    closed_at: datetime | None = None,
) -> UUID:
    investigation_id = investigation_id or uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO investigations (
                    investigation_id, alert_id, incident_id, status, outcome,
                    reviewer_label, opened_at, closed_at, notes, recommended_action,
                    created_at, updated_at
                ) VALUES (
                    :investigation_id, :alert_id, :incident_id, :status, :outcome,
                    :reviewer_label, :opened_at, :closed_at, NULL, NULL,
                    :opened_at, :opened_at
                )
                """
            ),
            {
                "investigation_id": investigation_id,
                "alert_id": alert_id,
                "incident_id": incident_id,
                "status": status,
                "outcome": outcome,
                "reviewer_label": reviewer_label,
                "opened_at": opened_at or BASE_TIME,
                "closed_at": closed_at,
            },
        )
    return investigation_id


def create_scenario(
    engine: Engine,
    *,
    scenario_id: UUID | None = None,
    scenario_code: str | None = None,
    scenario_type: str = "facility_rate_shift",
    split: str = "test",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    affected_entity_type: str = "facility",
    affected_entity_id: str = "TEST-FAC",
    expected_detection: bool = True,
) -> UUID:
    scenario_id = scenario_id or uuid4()
    scenario_code = scenario_code or f"SCEN-{scenario_id.hex[:8].upper()}"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO evaluation.synthetic_scenarios (
                    scenario_id, scenario_code, scenario_type, description, split,
                    start_at, end_at, affected_entity_type, affected_entity_id,
                    expected_detection, expected_signals, difficulty
                ) VALUES (
                    :scenario_id, :scenario_code, :scenario_type, 'test scenario',
                    :split, :start_at, :end_at, :affected_entity_type, :affected_entity_id,
                    :expected_detection, CAST(:expected_signals AS JSONB), 'medium'
                )
                """
            ),
            {
                "scenario_id": scenario_id,
                "scenario_code": scenario_code,
                "scenario_type": scenario_type,
                "split": split,
                "start_at": start_at or BASE_TIME,
                "end_at": end_at or BASE_TIME + timedelta(days=7),
                "affected_entity_type": affected_entity_type,
                "affected_entity_id": affected_entity_id,
                "expected_detection": expected_detection,
                "expected_signals": json.dumps({"damage_rate": "increase"}),
            },
        )
    return scenario_id


def create_truth_link(
    engine: Engine,
    scenario_id: UUID,
    *,
    entity_type: str = "shipment",
    entity_id: UUID | None = None,
    truth_role: str = "affected",
) -> UUID:
    truth_link_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO evaluation.synthetic_truth_links (
                    truth_link_id, scenario_id, entity_type, entity_id, truth_role
                ) VALUES (
                    :truth_link_id, :scenario_id, :entity_type, :entity_id, :truth_role
                )
                """
            ),
            {
                "truth_link_id": truth_link_id,
                "scenario_id": scenario_id,
                "entity_type": entity_type,
                "entity_id": entity_id or uuid4(),
                "truth_role": truth_role,
            },
        )
    return truth_link_id
