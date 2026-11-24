from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, text

from loss_intelligence.detection.config import DetectionConfig
from loss_intelligence.detection.detector import detect
from loss_intelligence.detection.models import (
    DetectionRunResult,
    EvaluationSummary,
    ScenarioResult,
)

SCENARIO_EXPECTATIONS = {
    "event_sequence_shift": ("facility", "event_sequence_outlier"),
    "return_pattern_shift": ("product_category", "return_pattern_outlier"),
    "data_quality_shift": ("facility", "data_quality"),
    "facility_rate_shift": ("facility", "damage_rate_spike"),
    "carrier_zone_shift": ("carrier_zone", "carrier_deviation"),
    "packaging_risk_shift": ("packaging_type", "product_profile_deviation"),
}


@dataclass(frozen=True, slots=True)
class _AlertRow:
    alert_id: UUID
    alert_type: str
    scope_type: str
    scope_id: str | None
    observed_start: datetime
    observed_end: datetime


@dataclass(frozen=True, slots=True)
class _ScenarioRow:
    scenario_code: str
    scenario_type: str
    start_at: datetime
    end_at: datetime
    affected_entity_type: str
    affected_entity_id: str
    expected_detection: bool


def _latest_completed_run(engine: Engine) -> UUID | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                """
                SELECT detection_run_id
                FROM meta.detection_runs
                WHERE status = 'completed'
                ORDER BY completed_at DESC NULLS LAST, started_at DESC
                LIMIT 1
                """
            )
        ).scalar_one_or_none()


def _load_alerts(engine: Engine, detection_run_id: UUID) -> list[_AlertRow]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    alert_id,
                    alert_type,
                    scope_type,
                    scope_id,
                    observed_start,
                    observed_end
                FROM anomaly_alerts
                WHERE detection_run_id = :detection_run_id
                ORDER BY anomaly_score DESC, generated_at DESC, alert_id
                """
            ),
            {"detection_run_id": detection_run_id},
        ).all()
    return [
        _AlertRow(
            alert_id=row.alert_id,
            alert_type=row.alert_type,
            scope_type=row.scope_type,
            scope_id=row.scope_id,
            observed_start=row.observed_start,
            observed_end=row.observed_end,
        )
        for row in rows
    ]


def _load_scenarios(engine: Engine) -> list[_ScenarioRow]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    scenario_code,
                    scenario_type,
                    start_at,
                    end_at,
                    affected_entity_type,
                    affected_entity_id,
                    expected_detection
                FROM evaluation.synthetic_scenarios
                WHERE split = 'validation'
                ORDER BY scenario_code
                """
            )
        ).all()
    return [
        _ScenarioRow(
            scenario_code=row.scenario_code,
            scenario_type=row.scenario_type,
            start_at=row.start_at,
            end_at=row.end_at,
            affected_entity_type=row.affected_entity_type,
            affected_entity_id=row.affected_entity_id,
            expected_detection=row.expected_detection,
        )
        for row in rows
    ]


def _overlaps(alert: _AlertRow, scenario: _ScenarioRow) -> bool:
    return alert.observed_start < scenario.end_at and alert.observed_end > scenario.start_at


def clean_baseline_span(
    engine: Engine,
    lookback_days: int,
) -> tuple[datetime, datetime]:
    with engine.connect() as connection:
        earliest = connection.execute(
            text(
                """
                SELECT min(start_at)
                FROM evaluation.synthetic_scenarios
                """
            )
        ).scalar_one()
    if earliest is None:
        raise ValueError("no scenarios are available to define a clean baseline")
    return earliest - timedelta(days=lookback_days), earliest


def validation_span(engine: Engine) -> tuple[datetime, datetime]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT min(start_at) AS start_at, max(end_at) AS end_at
                FROM evaluation.synthetic_scenarios
                WHERE split = 'validation'
                  AND expected_detection = TRUE
                """
            )
        ).one()
    if row.start_at is None or row.end_at is None:
        raise ValueError("no validation scenarios are available for detection")
    return row.start_at, row.end_at


def detect_and_evaluate_validation(
    engine: Engine,
    config: DetectionConfig | None = None,
    *,
    k: int = 10,
) -> tuple[DetectionRunResult, EvaluationSummary]:
    start_at, end_at = validation_span(engine)
    effective_config = config or DetectionConfig()
    baseline_start, baseline_end = clean_baseline_span(
        engine,
        effective_config.lookback_days,
    )
    detection = detect(
        engine,
        effective_config,
        observed_start=start_at,
        observed_end=end_at,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
    )
    summary = evaluate_validation(
        engine,
        detection_run_id=detection.detection_run_id,
        k=k,
    )
    return detection, summary


def evaluate_validation(
    engine: Engine,
    *,
    detection_run_id: UUID | None = None,
    k: int = 10,
) -> EvaluationSummary:
    if k < 1:
        raise ValueError("k must be at least 1")

    if detection_run_id is None:
        detection_run_id = _latest_completed_run(engine)
    if detection_run_id is None:
        raise ValueError("no completed detection run is available for evaluation")

    alerts = _load_alerts(engine, detection_run_id)
    scenarios = _load_scenarios(engine)

    scenario_results: list[ScenarioResult] = []
    matched_alert_ids: set[UUID] = set()
    negative_scenarios = 0
    false_positive_scenarios = 0
    for scenario in scenarios:
        try:
            expected_scope_type, expected_alert_type = SCENARIO_EXPECTATIONS[scenario.scenario_type]
        except KeyError as exc:
            raise ValueError(
                f"unsupported validation scenario type: {scenario.scenario_type}"
            ) from exc
        matching = [
            alert
            for alert in alerts
            if alert.alert_type == expected_alert_type
            and alert.scope_type == expected_scope_type
            and alert.scope_id == scenario.affected_entity_id
        ]
        overlapping = [alert for alert in matching if _overlaps(alert, scenario)]
        if not scenario.expected_detection:
            negative_scenarios += 1
            if overlapping:
                false_positive_scenarios += 1
            continue

        matched_alert_ids.update(alert.alert_id for alert in overlapping)
        scenario_results.append(
            ScenarioResult(
                scenario_code=scenario.scenario_code,
                scenario_type=scenario.scenario_type,
                expected_scope_type=expected_scope_type,
                expected_scope_id=scenario.affected_entity_id,
                expected_alert_type=expected_alert_type,
                detected=bool(overlapping),
                matching_alert_count=len(matching),
                alert_count=len(overlapping),
            )
        )

    expected = len(scenario_results)
    detected = sum(result.detected for result in scenario_results)
    total_alerts = len(alerts)
    false_alerts = sum(alert.alert_id not in matched_alert_ids for alert in alerts)
    top_k = alerts[:k]
    k_effective = len(top_k)

    return EvaluationSummary(
        split="validation",
        expected_scenarios=expected,
        detected_scenarios=detected,
        recall=(detected / expected) if expected else None,
        negative_scenarios=negative_scenarios,
        false_positive_scenarios=false_positive_scenarios,
        false_positive_rate=(
            false_positive_scenarios / negative_scenarios if negative_scenarios else None
        ),
        total_alerts=total_alerts,
        false_alerts=false_alerts,
        false_discovery_proportion=(false_alerts / total_alerts) if total_alerts else None,
        precision_at_k=(
            sum(alert.alert_id in matched_alert_ids for alert in top_k) / k_effective
            if k_effective
            else None
        ),
        k=k,
        k_effective=k_effective,
        scenarios=tuple(scenario_results),
    )
