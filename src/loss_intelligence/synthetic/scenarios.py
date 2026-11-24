from collections import Counter
from datetime import datetime, timedelta
from uuid import UUID

from loss_intelligence.synthetic.common import deterministic_uuid, utc_start
from loss_intelligence.synthetic.config import SyntheticDataConfig
from loss_intelligence.synthetic.models import ReferenceData, ScenarioPlan, ShipmentPlan

SPLIT_TYPES = {
    "train": [
        "facility_rate_shift",
        "carrier_zone_shift",
        "packaging_risk_shift",
    ],
    "validation": [
        "event_sequence_shift",
        "return_pattern_shift",
        "data_quality_shift",
    ],
    "test": [
        "facility_rate_shift",
        "carrier_zone_shift",
        "packaging_risk_shift",
    ],
}

WINDOW_DAYS = {
    "facility_rate_shift": 21,
    "carrier_zone_shift": 45,
    "packaging_risk_shift": 30,
    "event_sequence_shift": 30,
    "return_pattern_shift": 30,
    "data_quality_shift": 21,
}

DIFFICULTY = {
    "facility_rate_shift": "easy",
    "carrier_zone_shift": "medium",
    "packaging_risk_shift": "easy",
    "event_sequence_shift": "medium",
    "return_pattern_shift": "medium",
    "data_quality_shift": "easy",
}

CODE_LABELS = {
    "facility_rate_shift": "FACILITY",
    "carrier_zone_shift": "CARRIER-ZONE",
    "packaging_risk_shift": "PACKAGING",
    "event_sequence_shift": "SEQUENCE",
    "return_pattern_shift": "RETURN",
    "data_quality_shift": "DATA-QUALITY",
}


def split_ranges(config: SyntheticDataConfig) -> dict[str, tuple[datetime, datetime]]:
    start = utc_start(config.start_date)
    end = utc_start(config.end_date + timedelta(days=1))
    analysis_start = min(start + timedelta(days=config.clean_baseline_days), end)
    duration = end - analysis_start
    train_end = analysis_start + duration * 0.5
    validation_end = train_end + duration * 0.25
    return {
        "train": (analysis_start, train_end),
        "validation": (train_end, validation_end),
        "test": (validation_end, end),
    }


def _facility_counts(shipments: list[ShipmentPlan]) -> Counter[UUID]:
    counts: Counter[UUID] = Counter()
    for shipment in shipments:
        counts[shipment.origin_facility_id] += 1
        counts[shipment.destination_facility_id] += 1
    return counts


def _carrier_zone_counts(shipments: list[ShipmentPlan]) -> Counter[tuple[UUID, UUID]]:
    return Counter(
        (shipment.carrier_id, shipment.destination_zone_id)
        for shipment in shipments
        if shipment.carrier_id is not None
    )


def _packaging_counts(shipments: list[ShipmentPlan]) -> Counter[UUID]:
    return Counter(shipment.packaging_type_id for shipment in shipments)


def _category_counts(shipments: list[ShipmentPlan]) -> Counter[UUID]:
    return Counter(shipment.product_category_id for shipment in shipments)


def _pick_first_unused(candidates: list, used: set) -> object:
    for candidate in candidates:
        if candidate not in used:
            used.add(candidate)
            return candidate
    value = candidates[0]
    used.add(value)
    return value


def _window_for_split(
    split_start: datetime,
    split_end: datetime,
    scenario_index: int,
    scenario_count: int,
    window_days: int,
) -> tuple[datetime, datetime]:
    split_days = (split_end - split_start).total_seconds() / 86_400
    effective_window = min(window_days, max(7, int(split_days * 0.8)))
    if scenario_count <= 1:
        offset_days = 0.0
    else:
        available = max(0.0, split_days - effective_window)
        offset_days = available * scenario_index / (scenario_count - 1)
    start = split_start + timedelta(days=offset_days)
    end = min(start + timedelta(days=effective_window), split_end)
    if end <= start:
        end = min(start + timedelta(days=1), split_end)
    return start, end


def plan_scenarios(
    config: SyntheticDataConfig,
    reference: ReferenceData,
    shipments: list[ShipmentPlan],
) -> list[ScenarioPlan]:
    if config.scenarios_per_split == 0:
        return []

    facility_counts = _facility_counts(shipments)
    pair_counts = _carrier_zone_counts(shipments)
    packaging_counts = _packaging_counts(shipments)
    category_counts = _category_counts(shipments)

    sorted_facilities = [item for item, _ in facility_counts.most_common()]
    sorted_pairs = [item for item, _ in pair_counts.most_common()]
    sorted_packaging = [item for item, _ in packaging_counts.most_common()]
    sorted_categories = [item for item, _ in category_counts.most_common()]

    fallback_facilities = [facility["facility_id"] for facility in reference.facilities]
    fallback_packaging = [packaging["packaging_type_id"] for packaging in reference.packaging_types]
    fallback_categories = [
        category["product_category_id"] for category in reference.product_categories
    ]
    fallback_pairs = [
        (carrier["carrier_id"], zone["zone_id"])
        for carrier in reference.carriers
        for zone in reference.zones
    ]

    def candidates(values: list, fallback: list) -> list:
        return values or fallback

    used_facility: set[UUID] = set()
    used_pair: set[tuple[UUID, UUID]] = set()
    used_packaging: set[UUID] = set()
    used_return_category: set[UUID] = set()
    used_control_facility: set[UUID] = set()

    scenarios: list[ScenarioPlan] = []
    ranges = split_ranges(config)

    for split, (split_start, split_end) in ranges.items():
        types = SPLIT_TYPES[split][: config.scenarios_per_split]
        for scenario_index, scenario_type in enumerate(types):
            start_at, end_at = _window_for_split(
                split_start,
                split_end,
                scenario_index,
                len(types),
                WINDOW_DAYS[scenario_type],
            )

            facility_id: UUID | None = None
            carrier_id: UUID | None = None
            zone_id: UUID | None = None
            packaging_id: UUID | None = None
            category_id: UUID | None = None
            affected_entity_type = "facility"
            affected_entity_id = ""

            if scenario_type == "facility_rate_shift":
                facility_id = _pick_first_unused(
                    candidates(sorted_facilities, fallback_facilities), used_facility
                )
                affected_entity_id = str(facility_id)
            elif scenario_type == "carrier_zone_shift":
                carrier_id, zone_id = _pick_first_unused(
                    candidates(sorted_pairs, fallback_pairs), used_pair
                )
                affected_entity_type = "carrier_zone"
                affected_entity_id = f"{carrier_id}:{zone_id}"
            elif scenario_type == "packaging_risk_shift":
                packaging_id = _pick_first_unused(
                    candidates(sorted_packaging, fallback_packaging), used_packaging
                )
                affected_entity_type = "packaging_type"
                affected_entity_id = str(packaging_id)
            elif scenario_type == "event_sequence_shift":
                facility_id = _pick_first_unused(
                    candidates(sorted_facilities, fallback_facilities),
                    used_facility,
                )
                affected_entity_id = str(facility_id)
            elif scenario_type == "return_pattern_shift":
                category_id = _pick_first_unused(
                    candidates(sorted_categories, fallback_categories),
                    used_return_category,
                )
                affected_entity_type = "product_category"
                affected_entity_id = str(category_id)
            elif scenario_type == "data_quality_shift":
                facility_id = _pick_first_unused(
                    candidates(sorted_facilities, fallback_facilities),
                    used_facility,
                )
                affected_entity_id = str(facility_id)

            scenario_id = deterministic_uuid(
                config.seed,
                "scenario",
                f"{split}:{scenario_type}:{scenario_index}:{affected_entity_id}",
            )
            expected_signals = _expected_signals(
                scenario_type, facility_id, carrier_id, zone_id, packaging_id, category_id
            )
            scenarios.append(
                ScenarioPlan(
                    scenario_id=scenario_id,
                    scenario_code=(
                        f"SCEN-{split.upper()}-{CODE_LABELS[scenario_type]}-"
                        f"{scenario_index + 1:02d}"
                    ),
                    scenario_type=scenario_type,
                    description=_description(
                        scenario_type,
                        start_at,
                        end_at,
                        facility_id,
                        carrier_id,
                        zone_id,
                        packaging_id,
                        category_id,
                    ),
                    split=split,
                    start_at=start_at,
                    end_at=end_at,
                    affected_entity_type=affected_entity_type,
                    affected_entity_id=affected_entity_id,
                    expected_detection=True,
                    expected_signals=expected_signals,
                    difficulty=DIFFICULTY[scenario_type],
                    affected_facility_id=facility_id,
                    affected_carrier_id=carrier_id,
                    affected_zone_id=zone_id,
                    affected_packaging_id=packaging_id,
                    affected_category_id=category_id,
                )
            )

        used_control_facility.update(used_facility)
        for control_index in range(config.negative_scenarios_per_split):
            scenario_type = SPLIT_TYPES[split][0]
            start_at, end_at = _window_for_split(
                split_start,
                split_end,
                control_index,
                config.negative_scenarios_per_split,
                WINDOW_DAYS[scenario_type],
            )
            facility_id = _pick_first_unused(
                candidates(sorted_facilities, fallback_facilities),
                used_control_facility,
            )
            used_facility.add(facility_id)
            scenario_id = deterministic_uuid(
                config.seed,
                "scenario",
                f"{split}:negative:{control_index}:{facility_id}",
            )
            scenarios.append(
                ScenarioPlan(
                    scenario_id=scenario_id,
                    scenario_code=(f"SCEN-{split.upper()}-CONTROL-{control_index + 1:02d}"),
                    scenario_type=scenario_type,
                    description=(
                        "Negative control with no injected effect at "
                        f"{facility_id} during "
                        f"{start_at.date().isoformat()} to {end_at.date().isoformat()}."
                    ),
                    split=split,
                    start_at=start_at,
                    end_at=end_at,
                    affected_entity_type="facility",
                    affected_entity_id=str(facility_id),
                    expected_detection=False,
                    expected_signals={
                        **_expected_signals(
                            scenario_type,
                            facility_id,
                            None,
                            None,
                            None,
                            None,
                        ),
                        "direction": "none",
                    },
                    difficulty=DIFFICULTY[scenario_type],
                    affected_facility_id=facility_id,
                )
            )

    return scenarios


def _expected_signals(
    scenario_type: str,
    facility_id: UUID | None,
    carrier_id: UUID | None,
    zone_id: UUID | None,
    packaging_id: UUID | None,
    category_id: UUID | None,
) -> dict:
    if scenario_type == "facility_rate_shift":
        return {
            "metric": "facility_damage_rate",
            "direction": "increase",
            "scope_type": "facility",
            "facility_id": str(facility_id),
        }
    if scenario_type == "carrier_zone_shift":
        return {
            "metric": "carrier_zone_damage_rate",
            "direction": "increase",
            "scope_type": "carrier_zone",
            "carrier_id": str(carrier_id),
            "zone_id": str(zone_id),
        }
    if scenario_type == "packaging_risk_shift":
        return {
            "metric": "packaging_damage_rate",
            "direction": "increase",
            "scope_type": "packaging_type",
            "packaging_type_id": str(packaging_id),
        }
    if scenario_type == "event_sequence_shift":
        return {
            "metric": "event_sequence_outlier",
            "direction": "increase",
            "scope_type": "facility",
            "facility_id": str(facility_id),
        }
    if scenario_type == "return_pattern_shift":
        return {
            "metric": "return_pattern_outlier",
            "direction": "increase",
            "scope_type": "product_category",
            "product_category_id": str(category_id),
        }
    return {
        "metric": "data_quality_gap_rate",
        "direction": "increase",
        "scope_type": "facility",
        "facility_id": str(facility_id),
    }


def _description(
    scenario_type: str,
    start_at: datetime,
    end_at: datetime,
    facility_id: UUID | None,
    carrier_id: UUID | None,
    zone_id: UUID | None,
    packaging_id: UUID | None,
    category_id: UUID | None,
) -> str:
    window = f"{start_at.date().isoformat()} to {end_at.date().isoformat()}"
    if scenario_type == "facility_rate_shift":
        return f"Facility damage-rate increase at {facility_id} during {window}."
    if scenario_type == "carrier_zone_shift":
        return f"Carrier-zone damage-rate increase for {carrier_id} in {zone_id} during {window}."
    if scenario_type == "packaging_risk_shift":
        return f"Packaging-profile damage-rate increase for {packaging_id} during {window}."
    if scenario_type == "event_sequence_shift":
        return f"Unusual event timing and sequence at {facility_id} during {window}."
    if scenario_type == "return_pattern_shift":
        return f"Return-pattern shift for {category_id} during {window}."
    return f"Data-quality gaps at {facility_id} during {window}."


def scenario_matches(scenario: ScenarioPlan, shipment: ShipmentPlan) -> bool:
    if not (scenario.start_at <= shipment.created_at < scenario.end_at):
        return False

    if scenario.scenario_type in (
        "facility_rate_shift",
        "event_sequence_shift",
        "data_quality_shift",
    ):
        return (
            shipment.origin_facility_id == scenario.affected_facility_id
            or shipment.destination_facility_id == scenario.affected_facility_id
        )
    if scenario.scenario_type == "carrier_zone_shift":
        return (
            shipment.carrier_id == scenario.affected_carrier_id
            and shipment.destination_zone_id == scenario.affected_zone_id
        )
    if scenario.scenario_type == "packaging_risk_shift":
        return shipment.packaging_type_id == scenario.affected_packaging_id
    if scenario.scenario_type == "return_pattern_shift":
        return shipment.product_category_id == scenario.affected_category_id
    return False


def match_scenarios(
    shipments: list[ShipmentPlan],
    scenarios: list[ScenarioPlan],
) -> None:
    for shipment in shipments:
        shipment.matched_scenarios.clear()
        shipment.data_quality_scenario_id = None
        shipment.event_sequence_scenario_id = None
        for scenario in scenarios:
            if scenario_matches(scenario, shipment):
                if not scenario.expected_detection:
                    continue
                shipment.matched_scenarios.append(scenario)
                if scenario.scenario_type == "data_quality_shift":
                    shipment.data_quality_scenario_id = scenario.scenario_id
                elif scenario.scenario_type == "event_sequence_shift":
                    shipment.event_sequence_scenario_id = scenario.scenario_id
