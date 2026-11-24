from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

Priority = Literal["low", "medium", "high", "critical"]
EvidenceEntityType = Literal["shipment", "incident", "return", "event"]


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    entity_type: EvidenceEntityType
    entity_id: UUID
    evidence_role: str = "primary"


@dataclass(frozen=True, slots=True)
class DetectionHit:
    metric_key: str
    alert_type: str
    scope_type: str
    scope_id: str
    scope_name: str | None
    observed_start: datetime
    observed_end: datetime
    baseline_start: datetime
    baseline_end: datetime
    observed_numerator: int
    observed_denominator: int
    baseline_numerator: int
    baseline_denominator: int
    observed_rate: float
    baseline_rate: float
    relative_lift: float | None
    z_score: float
    p_value: float
    q_value: float
    priority: Priority
    explanation: str
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class DetectionRunResult:
    detection_run_id: UUID
    config_hash: str
    observed_start: datetime
    observed_end: datetime
    baseline_start: datetime
    baseline_end: datetime
    hits: tuple[DetectionHit, ...]
    tested_hypotheses: int = 0
    significant_hypotheses: int = 0
    suppressed_hypotheses: int = 0


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_code: str
    scenario_type: str
    expected_scope_type: str
    expected_scope_id: str
    expected_alert_type: str
    detected: bool
    matching_alert_count: int
    alert_count: int


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    split: str
    expected_scenarios: int
    detected_scenarios: int
    recall: float | None
    negative_scenarios: int
    false_positive_scenarios: int
    false_positive_rate: float | None
    total_alerts: int
    false_alerts: int
    false_discovery_proportion: float | None
    precision_at_k: float | None
    k: int
    k_effective: int
    scenarios: tuple[ScenarioResult, ...]
