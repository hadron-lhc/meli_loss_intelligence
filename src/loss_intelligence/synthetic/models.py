from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class ReferenceData:
    zones: list[dict[str, Any]]
    facilities: list[dict[str, Any]]
    carriers: list[dict[str, Any]]
    product_categories: list[dict[str, Any]]
    packaging_types: list[dict[str, Any]]
    facilities_by_zone: dict[UUID, list[UUID]]
    zone_by_facility: dict[UUID, UUID]
    zone_by_id: dict[UUID, dict[str, Any]]
    carrier_by_id: dict[UUID, dict[str, Any]]
    category_by_id: dict[UUID, dict[str, Any]]
    packaging_by_id: dict[UUID, dict[str, Any]]
    carrier_effect: dict[UUID, float]
    facility_effect: dict[UUID, float]
    zone_effect: dict[UUID, float]


@dataclass
class EventPlan:
    key: str
    event_code: str
    occurred_at: datetime
    recorded_at: datetime
    facility_id: UUID | None = None
    zone_id: UUID | None = None
    carrier_id: UUID | None = None
    metadata: dict[str, Any] | None = None
    scenario_id: UUID | None = None


@dataclass
class IncidentPlan:
    key: str
    incident_id: UUID
    incident_type: str
    damage_type: str
    severity: str
    reported_at: datetime
    confirmed_at: datetime | None
    incident_status: str
    estimated_loss_amount: Decimal | None
    currency_code: str | None
    evidence_type: str
    related_event_key: str
    created_at: datetime
    scenario_id: UUID | None = None


@dataclass
class ReturnPlan:
    key: str
    return_id: UUID
    initiated_at: datetime
    received_at: datetime | None
    declared_reason: str
    inspection_outcome: str
    return_status: str
    condition_on_return: str | None
    created_at: datetime
    scenario_id: UUID | None = None


@dataclass
class ScenarioPlan:
    scenario_id: UUID
    scenario_code: str
    scenario_type: str
    description: str
    split: str
    start_at: datetime
    end_at: datetime
    affected_entity_type: str
    affected_entity_id: str
    expected_detection: bool
    expected_signals: dict[str, Any]
    difficulty: str
    affected_facility_id: UUID | None = None
    affected_carrier_id: UUID | None = None
    affected_zone_id: UUID | None = None
    affected_packaging_id: UUID | None = None
    affected_category_id: UUID | None = None


@dataclass
class ShipmentPlan:
    index: int
    key: str
    shipment_id: UUID
    shipment_code: str
    created_at: datetime
    origin_facility_id: UUID
    origin_zone_id: UUID
    destination_zone_id: UUID
    destination_facility_id: UUID
    carrier_id: UUID | None
    product_category_id: UUID
    packaging_type_id: UUID
    weight_g: int | None
    length_mm: int | None
    width_mm: int | None
    height_mm: int | None
    declared_value: Decimal | None
    currency_code: str | None
    outcome: str
    events: list[EventPlan] = field(default_factory=list)
    incidents: list[IncidentPlan] = field(default_factory=list)
    returns: list[ReturnPlan] = field(default_factory=list)
    matched_scenarios: list[ScenarioPlan] = field(default_factory=list)
    data_quality_scenario_id: UUID | None = None
    event_sequence_scenario_id: UUID | None = None
    delivered_at: datetime | None = None
    dispatched_at: datetime | None = None
    shipment_status: str = "unknown"


@dataclass
class GeneratedDataset:
    manifest: dict[str, Any]
    rows: dict[str, list[dict[str, Any]]]


@dataclass(frozen=True)
class GenerationResult:
    run_id: UUID
    dataset_dir: Path
    row_counts: dict[str, int]
    scenario_counts: dict[str, int]
    data_quality_findings: dict[str, int]
