from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

ScopeType = Literal[
    "facility",
    "carrier",
    "zone",
    "product_category",
    "packaging_type",
    "stage",
]


@dataclass(frozen=True, slots=True)
class RateStats:
    numerator: int
    denominator: int
    rate: float | None
    per_1000: float | None
    ci_low: float | None
    ci_high: float | None
    minimum_volume: int
    low_volume: bool


@dataclass(frozen=True, slots=True)
class MaturityMetrics:
    maturity_days: int
    mature_end_date: date | None
    mature: RateStats
    immature: RateStats
    mature_damage_incidents: int
    immature_damage_incidents: int


@dataclass(frozen=True, slots=True)
class OverviewMetrics:
    start_date: date | None
    end_date: date | None
    eligible_shipments: int
    confirmed_damage_incidents: int
    damage: RateStats
    maturity: MaturityMetrics


@dataclass(frozen=True, slots=True)
class DailyMetric:
    cohort_date: date
    eligible_shipments: int
    confirmed_damage_shipments: int
    confirmed_damage_incidents: int
    damage: RateStats


@dataclass(frozen=True, slots=True)
class ScopeMetric:
    scope_type: ScopeType
    scope_id: str
    scope_name: str | None
    eligible_shipments: int
    confirmed_damage_shipments: int
    confirmed_damage_incidents: int
    incident_share: float | None
    damage: RateStats


@dataclass(frozen=True, slots=True)
class CurrencyLoss:
    currency_code: str
    confirmed_damage_incidents: int
    estimated_loss_amount: Decimal


@dataclass(frozen=True, slots=True)
class DataQualityMetrics:
    late_recorded_events: int
    timestamp_conflicts: int
    duplicate_event_records: int
    shipments_with_duplicate_event_codes: int
    events_missing_facility: int
    events_missing_carrier: int
    shipments_missing_dimensions: int
    data_gap_events: int


@dataclass(frozen=True, slots=True)
class DataQualityDaily:
    cohort_date: date
    metrics: DataQualityMetrics


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    totals: DataQualityMetrics
    daily: tuple[DataQualityDaily, ...]


@dataclass(frozen=True, slots=True)
class AnalyticsSnapshot:
    overview: OverviewMetrics
    daily: tuple[DailyMetric, ...]
    hotspots: dict[ScopeType, tuple[ScopeMetric, ...]]
    loss_by_currency: tuple[CurrencyLoss, ...]
    data_quality: DataQualityReport
