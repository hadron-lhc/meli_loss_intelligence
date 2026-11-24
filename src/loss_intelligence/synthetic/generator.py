from __future__ import annotations

import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from loss_intelligence.domain.events import EVENT_TAXONOMY
from loss_intelligence.synthetic.common import (
    DATASET_FILES,
    deterministic_uuid,
    random_datetime,
    random_hours,
    utc_start,
    weighted_choice,
)
from loss_intelligence.synthetic.config import SyntheticDataConfig
from loss_intelligence.synthetic.models import (
    EventPlan,
    GeneratedDataset,
    IncidentPlan,
    ReferenceData,
    ReturnPlan,
    ScenarioPlan,
    ShipmentPlan,
)
from loss_intelligence.synthetic.reference import build_reference_data
from loss_intelligence.synthetic.scenarios import match_scenarios, plan_scenarios

GENERATOR_VERSION = "0.2.1"
DATASET_SCHEMA_VERSION = "002"

OUTCOMES = ["delivered", "cancelled", "in_transit", "lost", "unknown"]
OUTCOME_WEIGHTS = [0.967, 0.010, 0.015, 0.003, 0.005]

DAMAGE_TYPES = [
    ("crushed", 0.25),
    ("torn", 0.15),
    ("punctured", 0.12),
    ("wet", 0.08),
    ("broken_contents", 0.20),
    ("deformed", 0.10),
    ("other", 0.05),
    ("unknown", 0.05),
]

SEVERITIES = [
    ("low", 0.35),
    ("medium", 0.40),
    ("high", 0.20),
    ("critical", 0.03),
    ("unknown", 0.02),
]

EVIDENCE_TYPES = [
    ("photo", 0.30),
    ("inspection", 0.25),
    ("customer_report", 0.20),
    ("carrier_report", 0.10),
    ("multiple", 0.10),
    ("unknown", 0.05),
]

INCIDENT_STATUSES = [
    ("confirmed", 0.90),
    ("under_review", 0.05),
    ("reported", 0.03),
    ("rejected", 0.02),
]

RETURN_REASONS = [
    ("not_as_described", 0.30),
    ("damaged", 0.20),
    ("wrong_item", 0.10),
    ("changed_mind", 0.20),
    ("missing_parts", 0.10),
    ("other", 0.10),
]

INSPECTION_OUTCOMES = [
    ("matches_declaration", 0.55),
    ("does_not_match_declaration", 0.10),
    ("inconclusive", 0.12),
    ("unknown", 0.08),
    ("not_inspected", 0.15),
]

CONDITIONS_ON_RETURN = [
    ("new", 0.40),
    ("used", 0.25),
    ("damaged", 0.15),
    ("unknown", 0.20),
]

OPTIONAL_EVENT_CODES = frozenset(
    {
        "PICKUP_SCHEDULED",
        "ORIGIN_RECEIVED",
        "ORIGIN_SORTED",
        "LINEHAUL_IN_TRANSIT",
        "DESTINATION_SORTED",
        "TRANSFERRED_LAST_MILE",
        "OUT_FOR_DELIVERY",
    }
)

DAMAGE_SCENARIO_TYPES = frozenset(
    {"facility_rate_shift", "carrier_zone_shift", "packaging_risk_shift"}
)

FRAGILITY_FACTOR = {"low": 0.55, "medium": 1.0, "high": 2.0, "unknown": 1.0}
PROTECTION_FACTOR = {"low": 1.7, "medium": 1.0, "high": 0.5, "unknown": 1.0}


def generate_dataset(config: SyntheticDataConfig) -> GeneratedDataset:
    rng = random.Random(config.seed)
    reference = build_reference_data(config)
    shipments = _generate_shipments(config, reference, rng)
    scenarios = plan_scenarios(config, reference, shipments)
    match_scenarios(shipments, scenarios)

    for shipment in shipments:
        _build_base_events(shipment, rng)
        _apply_baseline_data_quality(shipment, config, rng)
        if shipment.data_quality_scenario_id is not None:
            _apply_data_quality_scenario(shipment, rng, shipment.data_quality_scenario_id)
        if shipment.event_sequence_scenario_id is not None:
            _apply_event_sequence_scenario(shipment, rng, shipment.event_sequence_scenario_id)
        _update_key_timestamps(shipment)
        _generate_incidents(config, reference, shipment, rng)
        _generate_returns(config, reference, shipment, rng)
        _finalize_shipment(shipment)

    rows = _build_rows(config, reference, shipments, scenarios)
    rows["synthetic_truth_links"] = _build_truth_links(config, shipments, scenarios, rng)

    run_id = deterministic_uuid(
        config.seed,
        "generation_run",
        f"{GENERATOR_VERSION}:{config.config_hash}",
    )
    row_counts = {name: len(rows.get(name, [])) for name in DATASET_FILES}
    scenario_counts = {
        split: sum(1 for scenario in scenarios if scenario.split == split)
        for split in ("train", "validation", "test")
    }
    scenario_type_counts = Counter(scenario.scenario_type for scenario in scenarios)
    data_quality_findings = _data_quality_findings(shipments)
    observed_rates = _observed_rates(shipments)

    manifest = {
        "generator_version": GENERATOR_VERSION,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "run_id": str(run_id),
        "seed": config.seed,
        "config": config.model_dump(mode="json"),
        "config_hash": config.config_hash,
        "generated_at": datetime.now(UTC).isoformat(),
        "row_counts": row_counts,
        "scenario_counts": scenario_counts,
        "scenario_type_counts": dict(scenario_type_counts),
        "observed_rates": observed_rates,
        "data_quality_findings": data_quality_findings,
        "files": DATASET_FILES,
        "notes": [
            "Synthetic data only.",
            "Scenario and truth data belong in evaluation.* and must not be loaded into core.*.",
            "Intentional data-quality anomalies are expected and reported in "
            "data_quality_findings.",
        ],
    }
    return GeneratedDataset(manifest=manifest, rows=rows)


def _generate_shipments(
    config: SyntheticDataConfig,
    reference: ReferenceData,
    rng: random.Random,
) -> list[ShipmentPlan]:
    start = utc_start(config.start_date)
    end = utc_start(config.end_date + timedelta(days=1)) - timedelta(seconds=1)
    if end <= start:
        end = start + timedelta(days=1)

    facilities = reference.facilities
    zones = reference.zones
    carriers = reference.carriers
    categories = reference.product_categories
    packaging_types = reference.packaging_types

    shipments: list[ShipmentPlan] = []
    for index in range(config.shipment_count):
        key = f"{index + 1:07d}"
        origin_facility = rng.choice(facilities)
        destination_zone = rng.choice(zones)
        destination_facility_id = rng.choice(
            reference.facilities_by_zone[destination_zone["zone_id"]]
        )
        destination_facility = next(
            facility
            for facility in facilities
            if facility["facility_id"] == destination_facility_id
        )
        carrier_id = None if rng.random() < 0.005 else rng.choice(carriers)["carrier_id"]
        category = rng.choice(categories)
        packaging = rng.choice(packaging_types)

        if rng.random() < config.incomplete_dimensions_rate:
            weight_g = length_mm = width_mm = height_mm = None
        else:
            weight_g = rng.randint(200, 25_000)
            length_mm = rng.randint(100, 800)
            width_mm = rng.randint(80, 600)
            height_mm = rng.randint(50, 500)

        if rng.random() < 0.03:
            declared_value = None
            currency_code = None
        else:
            declared_value = (
                Decimal(rng.randint(500, 80_000)) + Decimal(rng.randint(0, 99)) / Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            currency_code = "ARS"

        shipments.append(
            ShipmentPlan(
                index=index,
                key=key,
                shipment_id=deterministic_uuid(config.seed, "shipment", key),
                shipment_code=f"SHP-{config.start_date.year}-{index + 1:07d}",
                created_at=random_datetime(rng, start, end),
                origin_facility_id=origin_facility["facility_id"],
                origin_zone_id=origin_facility["zone_id"],
                destination_zone_id=destination_facility["zone_id"],
                destination_facility_id=destination_facility["facility_id"],
                carrier_id=carrier_id,
                product_category_id=category["product_category_id"],
                packaging_type_id=packaging["packaging_type_id"],
                weight_g=weight_g,
                length_mm=length_mm,
                width_mm=width_mm,
                height_mm=height_mm,
                declared_value=declared_value,
                currency_code=currency_code,
                outcome=weighted_choice(rng, OUTCOMES, OUTCOME_WEIGHTS),
            )
        )

    return shipments


def _add_event(
    events: list[EventPlan],
    key: str,
    event_code: str,
    occurred_at: datetime,
    facility_id: UUID | None = None,
    zone_id: UUID | None = None,
    carrier_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    scenario_id: UUID | None = None,
) -> EventPlan:
    unique_key = key
    suffix = 2
    existing = {event.key for event in events}
    while unique_key in existing:
        unique_key = f"{key}-{suffix}"
        suffix += 1
    event = EventPlan(
        key=unique_key,
        event_code=event_code,
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        facility_id=facility_id,
        zone_id=zone_id,
        carrier_id=carrier_id,
        metadata=metadata,
        scenario_id=scenario_id,
    )
    events.append(event)
    return event


def _build_base_events(shipment: ShipmentPlan, rng: random.Random) -> None:
    events = shipment.events
    t = shipment.created_at
    origin_facility = shipment.origin_facility_id
    origin_zone = shipment.origin_zone_id
    destination_facility = shipment.destination_facility_id
    destination_zone = shipment.destination_zone_id
    carrier = shipment.carrier_id

    _add_event(events, "SHP_CREATED", "SHP_CREATED", t)

    if shipment.outcome == "cancelled":
        t += random_hours(rng, 0, 2)
        _add_event(
            events, "PICKUP_SCHEDULED", "PICKUP_SCHEDULED", t, origin_facility, origin_zone, carrier
        )
        t += random_hours(rng, 1, 6)
        _add_event(events, "PICKED_UP", "PICKED_UP", t, origin_facility, origin_zone, carrier)
        t += random_hours(rng, 1, 4)
        _add_event(
            events, "ORIGIN_RECEIVED", "ORIGIN_RECEIVED", t, origin_facility, origin_zone, carrier
        )
        return

    t += random_hours(rng, 0, 2)
    _add_event(
        events, "PICKUP_SCHEDULED", "PICKUP_SCHEDULED", t, origin_facility, origin_zone, carrier
    )
    t += random_hours(rng, 1, 6)
    _add_event(events, "PICKED_UP", "PICKED_UP", t, origin_facility, origin_zone, carrier)
    t += random_hours(rng, 1, 4)
    _add_event(
        events, "ORIGIN_RECEIVED", "ORIGIN_RECEIVED", t, origin_facility, origin_zone, carrier
    )
    t += random_hours(rng, 1, 4)
    _add_event(events, "ORIGIN_SORTED", "ORIGIN_SORTED", t, origin_facility, origin_zone, carrier)
    t += random_hours(rng, 1, 6)
    _add_event(
        events,
        "DISPATCHED_LINEHAUL",
        "DISPATCHED_LINEHAUL",
        t,
        origin_facility,
        origin_zone,
        carrier,
    )
    t += random_hours(rng, 2, 12)
    _add_event(events, "LINEHAUL_IN_TRANSIT", "LINEHAUL_IN_TRANSIT", t, None, None, carrier)

    if shipment.outcome == "in_transit":
        return

    t += random_hours(rng, 8, 48)
    _add_event(
        events,
        "ARRIVED_DESTINATION",
        "ARRIVED_DESTINATION",
        t,
        destination_facility,
        destination_zone,
        carrier,
    )
    t += random_hours(rng, 1, 6)
    _add_event(
        events,
        "DESTINATION_SORTED",
        "DESTINATION_SORTED",
        t,
        destination_facility,
        destination_zone,
        carrier,
    )
    t += random_hours(rng, 1, 4)
    _add_event(
        events,
        "TRANSFERRED_LAST_MILE",
        "TRANSFERRED_LAST_MILE",
        t,
        destination_facility,
        destination_zone,
        carrier,
    )
    t += random_hours(rng, 1, 8)
    _add_event(
        events,
        "OUT_FOR_DELIVERY",
        "OUT_FOR_DELIVERY",
        t,
        destination_facility,
        destination_zone,
        carrier,
    )

    if shipment.outcome == "lost":
        t += random_hours(rng, 1, 48)
        _add_event(
            events,
            "PACKAGE_MISSING",
            "PACKAGE_MISSING",
            t,
            destination_facility,
            destination_zone,
            carrier,
        )
        return

    if shipment.outcome == "unknown":
        t += random_hours(rng, 1, 24)
        _add_event(
            events,
            "DATA_GAP_DETECTED",
            "DATA_GAP_DETECTED",
            t,
            destination_facility,
            destination_zone,
            carrier,
        )
        return

    if rng.random() < 0.06:
        t += random_hours(rng, 1, 4)
        _add_event(
            events,
            "DELIVERY_ATTEMPTED",
            "DELIVERY_ATTEMPTED",
            t,
            destination_facility,
            destination_zone,
            carrier,
            metadata={"attempt": 1},
        )
        if rng.random() < 0.5:
            t += random_hours(rng, 1, 3)
            _add_event(
                events,
                "DELIVERY_EXCEPTION",
                "DELIVERY_EXCEPTION",
                t,
                destination_facility,
                destination_zone,
                carrier,
                metadata={"reason": "customer_unavailable"},
            )
        t += random_hours(rng, 12, 36)
        _add_event(
            events,
            "OUT_FOR_DELIVERY",
            "OUT_FOR_DELIVERY",
            t,
            destination_facility,
            destination_zone,
            carrier,
        )

    t += random_hours(rng, 1, 8)
    _add_event(events, "DELIVERED", "DELIVERED", t, destination_facility, destination_zone, carrier)


def _apply_baseline_data_quality(
    shipment: ShipmentPlan,
    config: SyntheticDataConfig,
    rng: random.Random,
) -> None:
    optional_events = [
        event for event in shipment.events if event.event_code in OPTIONAL_EVENT_CODES
    ]
    for event in optional_events:
        if rng.random() < config.event_missing_rate:
            if event in shipment.events:
                shipment.events.remove(event)
            _add_event(
                shipment.events,
                f"DATA_GAP-{event.key}",
                "DATA_GAP_DETECTED",
                event.occurred_at,
                event.facility_id,
                event.zone_id,
                event.carrier_id,
                metadata={"missing_event_code": event.event_code},
            )

    for event in shipment.events:
        if event.event_code == "SHP_CREATED":
            continue
        if rng.random() < config.event_late_rate:
            event.recorded_at = event.occurred_at + random_hours(rng, 1, 72)
        if rng.random() < config.unknown_attribution_rate:
            if rng.random() < 0.5:
                event.facility_id = None
            else:
                event.carrier_id = None


def _apply_data_quality_scenario(
    shipment: ShipmentPlan,
    rng: random.Random,
    scenario_id: UUID,
) -> None:
    shipment.weight_g = None
    shipment.length_mm = None
    shipment.width_mm = None
    shipment.height_mm = None

    optional_events = [
        event
        for event in shipment.events
        if event.event_code in OPTIONAL_EVENT_CODES and event.scenario_id is None
    ]
    if optional_events:
        removed = rng.choice(optional_events)
        shipment.events.remove(removed)
        _add_event(
            shipment.events,
            f"DATA-GAP-SCENARIO-{removed.key}",
            "DATA_GAP_DETECTED",
            removed.occurred_at,
            removed.facility_id,
            removed.zone_id,
            removed.carrier_id,
            metadata={"missing_event_code": removed.event_code},
            scenario_id=scenario_id,
        )

    duplicable = [
        event for event in shipment.events if event.event_code not in {"SHP_CREATED", "DELIVERED"}
    ]
    if duplicable:
        source = rng.choice(duplicable)
        _add_event(
            shipment.events,
            f"DUPLICATE-{source.key}",
            source.event_code,
            source.occurred_at,
            source.facility_id,
            source.zone_id,
            source.carrier_id,
            metadata=source.metadata,
            scenario_id=scenario_id,
        )

    events = [event for event in shipment.events if event.event_code != "SHP_CREATED"]
    if events:
        conflicting = rng.choice(events)
        conflicting.recorded_at = conflicting.occurred_at - timedelta(hours=2)
        conflicting.scenario_id = scenario_id

        late = rng.choice(events)
        late.recorded_at = late.occurred_at + timedelta(days=5)
        late.scenario_id = scenario_id

        unknown = rng.choice(events)
        unknown.facility_id = None
        unknown.carrier_id = None
        unknown.scenario_id = scenario_id


def _apply_event_sequence_scenario(
    shipment: ShipmentPlan,
    rng: random.Random,
    scenario_id: UUID,
) -> None:
    events = shipment.events
    arrival = next(
        (event for event in events if event.event_code == "ARRIVED_DESTINATION"),
        None,
    )
    if arrival is None:
        return

    delay = timedelta(days=rng.randint(2, 5))
    found_arrival = False
    for event in events:
        if event is arrival:
            found_arrival = True
        if found_arrival:
            event.occurred_at += delay
            event.recorded_at += delay
            event.scenario_id = scenario_id

    dispatch = next(
        (event for event in events if event.event_code == "DISPATCHED_LINEHAUL"),
        None,
    )
    if dispatch is not None:
        midpoint = dispatch.occurred_at + (arrival.occurred_at - dispatch.occurred_at) / 2
        _add_event(
            events,
            "LINEHAUL_IN_TRANSIT-EXTRA",
            "LINEHAUL_IN_TRANSIT",
            midpoint,
            None,
            None,
            shipment.carrier_id,
            scenario_id=scenario_id,
        )

    delivered = next(
        (event for event in events if event.event_code == "DELIVERED"),
        None,
    )
    if delivered is not None:
        attempt_time = delivered.occurred_at - random_hours(rng, 2, 12)
        _add_event(
            events,
            "DELIVERY_ATTEMPTED-EXTRA",
            "DELIVERY_ATTEMPTED",
            attempt_time,
            shipment.destination_facility_id,
            shipment.destination_zone_id,
            shipment.carrier_id,
            metadata={"attempt": 2},
            scenario_id=scenario_id,
        )


def _update_key_timestamps(shipment: ShipmentPlan) -> None:
    shipment.events.sort(key=lambda event: (event.occurred_at, event.key))
    shipment.dispatched_at = next(
        (
            event.occurred_at
            for event in shipment.events
            if event.event_code == "DISPATCHED_LINEHAUL"
        ),
        None,
    )
    shipment.delivered_at = next(
        (event.occurred_at for event in shipment.events if event.event_code == "DELIVERED"),
        None,
    )


def _risk_multiplier(shipment: ShipmentPlan, reference: ReferenceData) -> float:
    category = reference.category_by_id[shipment.product_category_id]
    packaging = reference.packaging_by_id[shipment.packaging_type_id]
    value = (
        FRAGILITY_FACTOR.get(category["fragility_class"], 1.0)
        * PROTECTION_FACTOR.get(packaging["protection_level"], 1.0)
        * reference.carrier_effect.get(shipment.carrier_id, 1.0)
        * reference.facility_effect.get(shipment.origin_facility_id, 1.0)
        * reference.facility_effect.get(shipment.destination_facility_id, 1.0)
        * reference.zone_effect.get(shipment.destination_zone_id, 1.0)
    )
    return max(0.2, min(value, 5.0))


def _generate_incidents(
    config: SyntheticDataConfig,
    reference: ReferenceData,
    shipment: ShipmentPlan,
    rng: random.Random,
) -> None:
    if shipment.outcome != "delivered" or shipment.delivered_at is None:
        return

    damage_scenarios = [
        scenario
        for scenario in shipment.matched_scenarios
        if scenario.scenario_type in DAMAGE_SCENARIO_TYPES
    ]
    multiplier = (
        max(config.damage_scenario_multiplier for _ in damage_scenarios)
        if damage_scenarios
        else 1.0
    )
    influencing = damage_scenarios[0] if damage_scenarios else None
    probability = min(
        0.25,
        config.baseline_damage_rate * _risk_multiplier(shipment, reference) * multiplier,
    )
    if rng.random() >= probability:
        return

    incident_count = 2 if rng.random() < 0.08 else 1
    base_time = shipment.delivered_at or max(
        (event.occurred_at for event in shipment.events),
        default=shipment.created_at,
    )
    facility_id, zone_id, carrier_id = _incident_attribution(shipment, reference, influencing)

    for incident_index in range(incident_count):
        reported_at = (
            base_time
            + random_hours(rng, 1, 48)
            + timedelta(days=incident_index * rng.randint(1, 3))
        )
        status = weighted_choice(
            rng,
            [item[0] for item in INCIDENT_STATUSES],
            [item[1] for item in INCIDENT_STATUSES],
        )
        confirmed_at = reported_at + random_hours(rng, 2, 72) if status == "confirmed" else None
        damage_type = weighted_choice(
            rng,
            [item[0] for item in DAMAGE_TYPES],
            [item[1] for item in DAMAGE_TYPES],
        )
        severity = weighted_choice(
            rng,
            [item[0] for item in SEVERITIES],
            [item[1] for item in SEVERITIES],
        )
        evidence_type = weighted_choice(
            rng,
            [item[0] for item in EVIDENCE_TYPES],
            [item[1] for item in EVIDENCE_TYPES],
        )
        estimated_loss, currency_code = _estimated_loss(shipment, rng)
        scenario_id = influencing.scenario_id if influencing else None

        _add_event(
            shipment.events,
            f"DAMAGE_REPORTED-{incident_index + 1}",
            "DAMAGE_REPORTED",
            reported_at,
            facility_id,
            zone_id,
            carrier_id,
            scenario_id=scenario_id,
        )
        related_key = f"DAMAGE_REPORTED-{incident_index + 1}"
        if confirmed_at is not None:
            _add_event(
                shipment.events,
                f"DAMAGE_CONFIRMED-{incident_index + 1}",
                "DAMAGE_CONFIRMED",
                confirmed_at,
                facility_id,
                zone_id,
                carrier_id,
                scenario_id=scenario_id,
            )
            related_key = f"DAMAGE_CONFIRMED-{incident_index + 1}"

        shipment.incidents.append(
            IncidentPlan(
                key=f"{incident_index + 1}",
                incident_id=deterministic_uuid(
                    config.seed, "incident", f"{shipment.key}:{incident_index + 1}"
                ),
                incident_type="package_damage",
                damage_type=damage_type,
                severity=severity,
                reported_at=reported_at,
                confirmed_at=confirmed_at,
                incident_status=status,
                estimated_loss_amount=estimated_loss,
                currency_code=currency_code,
                evidence_type=evidence_type,
                related_event_key=related_key,
                created_at=confirmed_at or reported_at,
                scenario_id=scenario_id,
            )
        )


def _incident_attribution(
    shipment: ShipmentPlan,
    reference: ReferenceData,
    influencing: ScenarioPlan | None,
) -> tuple[UUID, UUID, UUID | None]:
    facility_id = shipment.destination_facility_id
    zone_id = shipment.destination_zone_id
    carrier_id = shipment.carrier_id

    if influencing is None:
        return facility_id, zone_id, carrier_id

    if influencing.scenario_type == "facility_rate_shift":
        facility_id = influencing.affected_facility_id or facility_id
        zone_id = reference.zone_by_facility.get(facility_id, zone_id)
    elif influencing.scenario_type == "carrier_zone_shift":
        carrier_id = influencing.affected_carrier_id or carrier_id
        zone_id = influencing.affected_zone_id or zone_id
        facilities = reference.facilities_by_zone.get(zone_id)
        if facilities:
            facility_id = facilities[0]

    return facility_id, zone_id, carrier_id


def _estimated_loss(
    shipment: ShipmentPlan,
    rng: random.Random,
) -> tuple[Decimal | None, str | None]:
    if shipment.declared_value is None or rng.random() >= 0.92:
        return None, None
    fraction = Decimal(str(round(rng.uniform(0.35, 1.0), 2)))
    amount = (shipment.declared_value * fraction).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return amount, "ARS"


def _generate_returns(
    config: SyntheticDataConfig,
    reference: ReferenceData,
    shipment: ShipmentPlan,
    rng: random.Random,
) -> None:
    if shipment.outcome != "delivered" or shipment.delivered_at is None:
        return

    return_scenario = next(
        (
            scenario
            for scenario in shipment.matched_scenarios
            if scenario.scenario_type == "return_pattern_shift"
        ),
        None,
    )
    category = reference.category_by_id[shipment.product_category_id]
    fragility = category["fragility_class"]
    probability = config.return_rate * (
        0.8 if fragility == "low" else 1.3 if fragility == "high" else 1.0
    )
    if shipment.incidents:
        probability = max(probability, 0.30)
    if return_scenario is not None:
        probability = min(0.65, probability * config.return_scenario_multiplier)
    if rng.random() >= probability:
        return

    if return_scenario is not None:
        initiated_at = shipment.delivered_at + random_hours(rng, 6, 5 * 24)
    else:
        initiated_at = shipment.delivered_at + random_hours(rng, 24, 14 * 24)

    received_at = initiated_at + random_hours(rng, 24, 7 * 24) if rng.random() < 0.85 else None
    if received_at is None:
        inspection_outcome = "not_inspected"
        return_status = weighted_choice(rng, ["initiated", "in_transit"], [0.5, 0.5])
    else:
        inspection_outcome = weighted_choice(
            rng,
            [item[0] for item in INSPECTION_OUTCOMES],
            [item[1] for item in INSPECTION_OUTCOMES],
        )
        return_status = (
            "received"
            if inspection_outcome == "not_inspected"
            else weighted_choice(rng, ["inspected", "closed"], [0.5, 0.5])
        )

    reason_weights = list(RETURN_REASONS)
    if shipment.incidents:
        reason_weights = [
            ("damaged", 0.60),
            ("not_as_described", 0.20),
            ("wrong_item", 0.05),
            ("changed_mind", 0.05),
            ("missing_parts", 0.05),
            ("other", 0.05),
        ]
    elif return_scenario is not None:
        reason_weights = [
            ("not_as_described", 0.40),
            ("damaged", 0.25),
            ("wrong_item", 0.15),
            ("changed_mind", 0.10),
            ("missing_parts", 0.05),
            ("other", 0.05),
        ]
    declared_reason = weighted_choice(
        rng,
        [item[0] for item in reason_weights],
        [item[1] for item in reason_weights],
    )
    condition = (
        None
        if received_at is None
        else weighted_choice(
            rng,
            [item[0] for item in CONDITIONS_ON_RETURN],
            [item[1] for item in CONDITIONS_ON_RETURN],
        )
    )
    scenario_id = return_scenario.scenario_id if return_scenario else None

    _add_event(
        shipment.events,
        "RETURN_INITIATED",
        "RETURN_INITIATED",
        initiated_at,
        shipment.destination_facility_id,
        shipment.destination_zone_id,
        shipment.carrier_id,
        scenario_id=scenario_id,
    )
    if return_status != "initiated":
        _add_event(
            shipment.events,
            "RETURN_IN_TRANSIT",
            "RETURN_IN_TRANSIT",
            initiated_at + random_hours(rng, 6, 48),
            shipment.destination_facility_id,
            shipment.destination_zone_id,
            shipment.carrier_id,
            scenario_id=scenario_id,
        )
    if received_at is not None:
        _add_event(
            shipment.events,
            "RETURN_RECEIVED",
            "RETURN_RECEIVED",
            received_at,
            shipment.destination_facility_id,
            shipment.destination_zone_id,
            shipment.carrier_id,
            scenario_id=scenario_id,
        )
        if inspection_outcome != "not_inspected":
            _add_event(
                shipment.events,
                "RETURN_INSPECTED",
                "RETURN_INSPECTED",
                received_at + random_hours(rng, 1, 48),
                shipment.destination_facility_id,
                shipment.destination_zone_id,
                shipment.carrier_id,
                scenario_id=scenario_id,
            )

    shipment.returns.append(
        ReturnPlan(
            key="1",
            return_id=deterministic_uuid(config.seed, "return", f"{shipment.key}:1"),
            initiated_at=initiated_at,
            received_at=received_at,
            declared_reason=declared_reason,
            inspection_outcome=inspection_outcome,
            return_status=return_status,
            condition_on_return=condition,
            created_at=initiated_at,
            scenario_id=scenario_id,
        )
    )


def _finalize_shipment(shipment: ShipmentPlan) -> None:
    _update_key_timestamps(shipment)
    if shipment.returns:
        shipment.shipment_status = "returned"
    elif shipment.outcome == "delivered":
        shipment.shipment_status = "delivered"
    elif shipment.outcome == "cancelled":
        shipment.shipment_status = "cancelled"
    elif shipment.outcome == "lost":
        shipment.shipment_status = "lost"
    elif shipment.outcome == "in_transit":
        shipment.shipment_status = "in_transit"
    else:
        shipment.shipment_status = "unknown"


def _build_rows(
    config: SyntheticDataConfig,
    reference: ReferenceData,
    shipments: list[ShipmentPlan],
    scenarios: list[ScenarioPlan],
) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {
        "zones": [dict(zone) for zone in reference.zones],
        "facilities": [dict(facility) for facility in reference.facilities],
        "carriers": [dict(carrier) for carrier in reference.carriers],
        "product_categories": [dict(category) for category in reference.product_categories],
        "packaging_types": [dict(packaging) for packaging in reference.packaging_types],
        "shipments": [],
        "shipment_events": [],
        "incidents": [],
        "returns": [],
        "synthetic_scenarios": [],
    }

    for shipment in shipments:
        rows["shipments"].append(
            {
                "shipment_id": shipment.shipment_id,
                "shipment_code": shipment.shipment_code,
                "created_at": shipment.created_at,
                "dispatched_at": shipment.dispatched_at,
                "delivered_at": shipment.delivered_at,
                "origin_facility_id": shipment.origin_facility_id,
                "destination_zone_id": shipment.destination_zone_id,
                "carrier_id": shipment.carrier_id,
                "product_category_id": shipment.product_category_id,
                "packaging_type_id": shipment.packaging_type_id,
                "weight_g": shipment.weight_g,
                "length_mm": shipment.length_mm,
                "width_mm": shipment.width_mm,
                "height_mm": shipment.height_mm,
                "declared_value": shipment.declared_value,
                "currency_code": shipment.currency_code,
                "shipment_status": shipment.shipment_status,
                "is_test_record": False,
                "created_record_at": shipment.created_at,
            }
        )

        for sequence, event in enumerate(shipment.events, start=1):
            taxonomy = EVENT_TAXONOMY[event.event_code]
            rows["shipment_events"].append(
                {
                    "event_id": deterministic_uuid(
                        config.seed, "event", f"{shipment.key}:{event.key}"
                    ),
                    "shipment_id": shipment.shipment_id,
                    "event_code": event.event_code,
                    "event_name": taxonomy.name,
                    "stage": taxonomy.stage,
                    "event_status": taxonomy.status,
                    "occurred_at": event.occurred_at,
                    "recorded_at": event.recorded_at,
                    "sequence_number": sequence,
                    "source_system": "simulator_tracking",
                    "facility_id": event.facility_id,
                    "zone_id": event.zone_id,
                    "carrier_id": event.carrier_id,
                    "event_metadata": event.metadata,
                }
            )

        for incident in shipment.incidents:
            rows["incidents"].append(
                {
                    "incident_id": incident.incident_id,
                    "shipment_id": shipment.shipment_id,
                    "incident_type": incident.incident_type,
                    "damage_type": incident.damage_type,
                    "severity": incident.severity,
                    "reported_at": incident.reported_at,
                    "confirmed_at": incident.confirmed_at,
                    "estimated_loss_amount": incident.estimated_loss_amount,
                    "currency_code": incident.currency_code,
                    "incident_status": incident.incident_status,
                    "evidence_type": incident.evidence_type,
                    "related_event_id": deterministic_uuid(
                        config.seed,
                        "event",
                        f"{shipment.key}:{incident.related_event_key}",
                    ),
                    "created_at": incident.created_at,
                }
            )

        for return_plan in shipment.returns:
            rows["returns"].append(
                {
                    "return_id": return_plan.return_id,
                    "shipment_id": shipment.shipment_id,
                    "initiated_at": return_plan.initiated_at,
                    "received_at": return_plan.received_at,
                    "declared_reason": return_plan.declared_reason,
                    "inspection_outcome": return_plan.inspection_outcome,
                    "return_status": return_plan.return_status,
                    "condition_on_return": return_plan.condition_on_return,
                    "created_at": return_plan.created_at,
                }
            )

    for scenario in scenarios:
        rows["synthetic_scenarios"].append(
            {
                "scenario_id": scenario.scenario_id,
                "scenario_code": scenario.scenario_code,
                "scenario_type": scenario.scenario_type,
                "description": scenario.description,
                "split": scenario.split,
                "start_at": scenario.start_at,
                "end_at": scenario.end_at,
                "affected_entity_type": scenario.affected_entity_type,
                "affected_entity_id": scenario.affected_entity_id,
                "expected_detection": scenario.expected_detection,
                "expected_signals": scenario.expected_signals,
                "difficulty": scenario.difficulty,
            }
        )

    return rows


def _build_truth_links(
    config: SyntheticDataConfig,
    shipments: list[ShipmentPlan],
    scenarios: list[ScenarioPlan],
    rng: random.Random,
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_link(
        scenario: ScenarioPlan,
        entity_type: str,
        entity_id: UUID,
        truth_role: str,
    ) -> None:
        key = (str(scenario.scenario_id), entity_type, str(entity_id))
        if key in seen:
            return
        seen.add(key)
        links.append(
            {
                "truth_link_id": deterministic_uuid(config.seed, "truth_link", ":".join(key)),
                "scenario_id": scenario.scenario_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "truth_role": truth_role,
            }
        )

    for scenario in scenarios:
        affected = [
            shipment
            for shipment in shipments
            if any(
                matched.scenario_id == scenario.scenario_id
                for matched in shipment.matched_scenarios
            )
        ]
        for shipment in affected:
            add_link(scenario, "shipment", shipment.shipment_id, "affected")
            for event in shipment.events:
                if event.scenario_id == scenario.scenario_id:
                    add_link(
                        scenario,
                        "event",
                        deterministic_uuid(config.seed, "event", f"{shipment.key}:{event.key}"),
                        "affected",
                    )
            for incident in shipment.incidents:
                if incident.scenario_id == scenario.scenario_id:
                    add_link(scenario, "incident", incident.incident_id, "affected")
            for return_plan in shipment.returns:
                if return_plan.scenario_id == scenario.scenario_id:
                    add_link(scenario, "return", return_plan.return_id, "affected")

        controls = [
            shipment
            for shipment in shipments
            if scenario.start_at <= shipment.created_at < scenario.end_at
            and not any(
                matched.scenario_id == scenario.scenario_id
                for matched in shipment.matched_scenarios
            )
        ]
        sample_size = min(config.control_sample_size, len(controls))
        if sample_size:
            for shipment in rng.sample(controls, sample_size):
                add_link(scenario, "shipment", shipment.shipment_id, "control")

    return links


def _data_quality_findings(shipments: list[ShipmentPlan]) -> dict[str, int]:
    findings = Counter(
        {
            "late_recorded_events": 0,
            "timestamp_conflicts": 0,
            "shipments_with_duplicate_event_codes": 0,
            "events_missing_facility": 0,
            "events_missing_carrier": 0,
            "shipments_missing_dimensions": 0,
            "data_gap_events": 0,
        }
    )
    for shipment in shipments:
        event_groups: Counter[tuple[str, datetime]] = Counter()
        for event in shipment.events:
            if event.recorded_at > event.occurred_at + timedelta(hours=24):
                findings["late_recorded_events"] += 1
            if event.recorded_at < event.occurred_at:
                findings["timestamp_conflicts"] += 1
            if event.facility_id is None:
                findings["events_missing_facility"] += 1
            if event.carrier_id is None:
                findings["events_missing_carrier"] += 1
            if event.event_code == "DATA_GAP_DETECTED":
                findings["data_gap_events"] += 1
            event_groups[(event.event_code, event.occurred_at)] += 1
        if any(count > 1 for count in event_groups.values()):
            findings["shipments_with_duplicate_event_codes"] += 1
        if any(
            value is None
            for value in (
                shipment.weight_g,
                shipment.length_mm,
                shipment.width_mm,
                shipment.height_mm,
            )
        ):
            findings["shipments_missing_dimensions"] += 1
    return dict(findings)


def _observed_rates(shipments: list[ShipmentPlan]) -> dict[str, float]:
    total = len(shipments)
    if total == 0:
        return {
            "damage_incident_rate": 0.0,
            "shipment_return_rate": 0.0,
            "scenario_affected_rate": 0.0,
        }
    return {
        "damage_incident_rate": round(
            sum(1 for shipment in shipments if shipment.incidents) / total, 6
        ),
        "shipment_return_rate": round(
            sum(1 for shipment in shipments if shipment.returns) / total, 6
        ),
        "scenario_affected_rate": round(
            sum(1 for shipment in shipments if shipment.matched_scenarios) / total, 6
        ),
    }
