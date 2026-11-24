from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import Engine, text

from loss_intelligence.detection.config import DetectionConfig
from loss_intelligence.detection.models import DetectionHit, DetectionRunResult, EvidenceRef
from loss_intelligence.detection.queries import (
    DATA_QUALITY_EVIDENCE_SQL,
    RETURN_EVIDENCE_SQL,
    SEQUENCE_EVIDENCE_SQL,
    MetricRow,
    collect_metric_rows,
    damage_evidence,
    shipment_evidence,
)
from loss_intelligence.detection.statistics import (
    benjamini_hochberg,
    relative_lift,
    two_proportion_z,
)

METRIC_LABELS = {
    "damage_rate": "confirmed damage rate",
    "sequence_anomaly_rate": "sequence anomaly rate",
    "return_rate": "return rate",
    "data_quality_issue_rate": "data-quality issue rate",
}


@dataclass(frozen=True, slots=True)
class _Candidate:
    observed: MetricRow
    baseline: MetricRow
    z_score: float
    p_value: float
    q_value: float
    lift: float | None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def resolve_window(
    engine: Engine,
    config: DetectionConfig,
    observed_start: datetime | None = None,
    observed_end: datetime | None = None,
    baseline_start: datetime | None = None,
    baseline_end: datetime | None = None,
) -> tuple[datetime, datetime, datetime, datetime]:
    if (observed_start is None) != (observed_end is None):
        raise ValueError("observed start and end must be provided together")
    if (baseline_start is None) != (baseline_end is None):
        raise ValueError("baseline start and end must be provided together")

    if observed_start is None or observed_end is None:
        with engine.connect() as connection:
            latest = connection.execute(
                text("SELECT max(created_at) FROM shipments WHERE is_test_record = FALSE")
            ).scalar_one()
        if latest is None:
            raise ValueError("no non-test shipments are available for detection")
        end_date = latest.date() + timedelta(days=1)
        observed_end = datetime.combine(end_date, time.min, tzinfo=UTC)
        observed_start = observed_end - timedelta(days=config.lookback_days)

    observed_start = _utc(observed_start)
    observed_end = _utc(observed_end)
    if observed_end <= observed_start:
        raise ValueError("observed end must be after observed start")

    if baseline_start is None or baseline_end is None:
        baseline_end = observed_start
        baseline_start = baseline_end - timedelta(days=config.lookback_days)
    else:
        baseline_start = _utc(baseline_start)
        baseline_end = _utc(baseline_end)
        if baseline_end <= baseline_start:
            raise ValueError("baseline end must be after baseline start")
        if baseline_end > observed_start:
            raise ValueError("baseline must not overlap the observed window")

    return observed_start, observed_end, baseline_start, baseline_end


def _latest_generation_run_id(engine: Engine) -> UUID | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                """
                SELECT generation_run_id
                FROM meta.generation_runs
                WHERE status = 'completed'
                ORDER BY completed_at DESC NULLS LAST, started_at DESC
                LIMIT 1
                """
            )
        ).scalar_one_or_none()


def _create_detection_run(
    engine: Engine,
    config: DetectionConfig,
    dataset_generation_run_id: UUID | None,
) -> UUID:
    with engine.begin() as connection:
        return connection.execute(
            text(
                """
                INSERT INTO meta.detection_runs (
                    dataset_generation_run_id,
                    model_name,
                    model_version,
                    config,
                    config_hash,
                    status
                ) VALUES (
                    :dataset_generation_run_id,
                    :model_name,
                    :model_version,
                    CAST(:config AS JSONB),
                    :config_hash,
                    'pending'
                )
                RETURNING detection_run_id
                """
            ),
            {
                "dataset_generation_run_id": dataset_generation_run_id,
                "model_name": config.model_name,
                "model_version": config.model_version,
                "config": json.dumps(config.model_dump(mode="json"), sort_keys=True),
                "config_hash": config.config_hash,
            },
        ).scalar_one()


def _finish_run(engine: Engine, detection_run_id: UUID, status: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE meta.detection_runs
                SET status = :status, completed_at = NOW()
                WHERE detection_run_id = :detection_run_id
                """
            ),
            {"status": status, "detection_run_id": detection_run_id},
        )


def _passes_minimums(observed: MetricRow, baseline: MetricRow, config: DetectionConfig) -> bool:
    return (
        observed.denominator >= config.min_observed_denominator
        and baseline.denominator >= config.min_baseline_denominator
        and observed.numerator >= config.min_observed_numerator
    )


def _passes_lift(observed_rate: float, baseline_rate: float, config: DetectionConfig) -> bool:
    lift = relative_lift(observed_rate, baseline_rate)
    if lift is None:
        return observed_rate >= config.min_zero_baseline_rate
    return lift >= config.min_relative_lift


def _priority(candidate: _Candidate) -> str:
    observed_rate = candidate.observed.numerator / candidate.observed.denominator
    lift = candidate.lift
    if (lift is None and observed_rate >= 0.5) or (lift is not None and lift >= 5):
        return "critical"
    if (lift is not None and lift >= 3) or candidate.q_value < 0.01:
        return "high"
    return "medium"


def _explanation(candidate: _Candidate) -> str:
    observed = candidate.observed
    baseline = candidate.baseline
    observed_rate = observed.numerator / observed.denominator
    baseline_rate = baseline.numerator / baseline.denominator
    lift_text = (
        f"{candidate.lift:.2f}x baseline"
        if candidate.lift is not None
        else "baseline rate was zero"
    )
    return (
        f"{METRIC_LABELS[observed.metric_key]} for {observed.scope_type} "
        f"{observed.scope_name or observed.scope_id}: "
        f"{observed.numerator}/{observed.denominator} ({observed_rate:.2%}) vs baseline "
        f"{baseline.numerator}/{baseline.denominator} ({baseline_rate:.2%}); "
        f"lift {lift_text}; q={candidate.q_value:.4f}. "
        "Statistical association only; no causal or culpability conclusion."
    )


def _evidence_for(
    engine: Engine,
    candidate: _Candidate,
    config: DetectionConfig,
    observed_start: datetime,
    observed_end: datetime,
) -> tuple[EvidenceRef, ...]:
    if config.max_evidence == 0:
        return ()

    observed = candidate.observed
    if observed.metric_key == "damage_rate":
        pairs = damage_evidence(
            engine,
            observed.scope_type,
            observed.scope_id,
            observed_start,
            observed_end,
            config.max_evidence,
        )
        evidence: list[EvidenceRef] = []
        for shipment_id, incident_id in pairs:
            if len(evidence) >= config.max_evidence:
                break
            evidence.append(EvidenceRef("shipment", shipment_id))
            if len(evidence) < config.max_evidence:
                evidence.append(EvidenceRef("incident", incident_id))
        return tuple(evidence)

    if observed.metric_key == "sequence_anomaly_rate":
        sql = SEQUENCE_EVIDENCE_SQL
    elif observed.metric_key == "return_rate":
        sql = RETURN_EVIDENCE_SQL
    elif observed.metric_key == "data_quality_issue_rate":
        sql = DATA_QUALITY_EVIDENCE_SQL
    else:
        raise ValueError(f"unsupported metric key: {observed.metric_key}")

    shipment_ids = shipment_evidence(
        engine,
        sql,
        observed.scope_id,
        observed_start,
        observed_end,
        config.max_evidence,
    )
    return tuple(EvidenceRef("shipment", shipment_id) for shipment_id in shipment_ids)


def _build_hit(
    engine: Engine,
    candidate: _Candidate,
    config: DetectionConfig,
    observed_start: datetime,
    observed_end: datetime,
    baseline_start: datetime,
    baseline_end: datetime,
) -> DetectionHit:
    observed = candidate.observed
    baseline = candidate.baseline
    return DetectionHit(
        metric_key=observed.metric_key,
        alert_type=observed.alert_type,
        scope_type=observed.scope_type,
        scope_id=observed.scope_id,
        scope_name=observed.scope_name,
        observed_start=observed_start,
        observed_end=observed_end,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        observed_numerator=observed.numerator,
        observed_denominator=observed.denominator,
        baseline_numerator=baseline.numerator,
        baseline_denominator=baseline.denominator,
        observed_rate=observed.numerator / observed.denominator,
        baseline_rate=baseline.numerator / baseline.denominator,
        relative_lift=candidate.lift,
        z_score=candidate.z_score,
        p_value=candidate.p_value,
        q_value=candidate.q_value,
        priority=_priority(candidate),
        explanation=_explanation(candidate),
        evidence=_evidence_for(
            engine,
            candidate,
            config,
            observed_start,
            observed_end,
        ),
    )


def _persist_hits(
    engine: Engine,
    detection_run_id: UUID,
    hits: tuple[DetectionHit, ...],
    config: DetectionConfig,
) -> None:
    with engine.begin() as connection:
        for hit in hits:
            alert_id = connection.execute(
                text(
                    """
                    INSERT INTO anomaly_alerts (
                        alert_type,
                        scope_type,
                        scope_id,
                        observed_start,
                        observed_end,
                        baseline_start,
                        baseline_end,
                        observed_numerator,
                        observed_denominator,
                        observed_rate,
                        baseline_rate,
                        anomaly_score,
                        priority,
                        explanation,
                        model_name,
                        model_version,
                        status,
                        detection_run_id
                    ) VALUES (
                        :alert_type,
                        :scope_type,
                        :scope_id,
                        :observed_start,
                        :observed_end,
                        :baseline_start,
                        :baseline_end,
                        :observed_numerator,
                        :observed_denominator,
                        :observed_rate,
                        :baseline_rate,
                        :anomaly_score,
                        :priority,
                        :explanation,
                        :model_name,
                        :model_version,
                        'new',
                        :detection_run_id
                    )
                    RETURNING alert_id
                    """
                ),
                {
                    "alert_type": hit.alert_type,
                    "scope_type": hit.scope_type,
                    "scope_id": hit.scope_id,
                    "observed_start": hit.observed_start,
                    "observed_end": hit.observed_end,
                    "baseline_start": hit.baseline_start,
                    "baseline_end": hit.baseline_end,
                    "observed_numerator": hit.observed_numerator,
                    "observed_denominator": hit.observed_denominator,
                    "observed_rate": hit.observed_rate,
                    "baseline_rate": hit.baseline_rate,
                    "anomaly_score": hit.z_score,
                    "priority": hit.priority,
                    "explanation": hit.explanation,
                    "model_name": config.model_name,
                    "model_version": config.model_version,
                    "detection_run_id": detection_run_id,
                },
            ).scalar_one()

            for evidence in hit.evidence:
                connection.execute(
                    text(
                        """
                        INSERT INTO anomaly_alert_evidence (
                            alert_id,
                            entity_type,
                            entity_id,
                            evidence_role
                        ) VALUES (
                            :alert_id,
                            :entity_type,
                            CAST(:entity_id AS UUID),
                            :evidence_role
                        )
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "alert_id": alert_id,
                        "entity_type": evidence.entity_type,
                        "entity_id": evidence.entity_id,
                        "evidence_role": evidence.evidence_role,
                    },
                )


def detect(
    engine: Engine,
    config: DetectionConfig | None = None,
    *,
    observed_start: datetime | None = None,
    observed_end: datetime | None = None,
    baseline_start: datetime | None = None,
    baseline_end: datetime | None = None,
) -> DetectionRunResult:
    config = config or DetectionConfig()
    observed_start, observed_end, baseline_start, baseline_end = resolve_window(
        engine,
        config,
        observed_start,
        observed_end,
        baseline_start,
        baseline_end,
    )
    generation_run_id = _latest_generation_run_id(engine)
    detection_run_id = _create_detection_run(engine, config, generation_run_id)

    try:
        observed_rows = collect_metric_rows(engine, observed_start, observed_end)
        baseline_rows = collect_metric_rows(engine, baseline_start, baseline_end)
        baseline_by_key = {
            (row.metric_key, row.scope_type, row.scope_id): row for row in baseline_rows
        }

        tested: list[_Candidate] = []
        for observed in observed_rows:
            baseline = baseline_by_key.get(
                (observed.metric_key, observed.scope_type, observed.scope_id)
            )
            if baseline is None or not _passes_minimums(observed, baseline, config):
                continue
            z_score, p_value = two_proportion_z(
                observed.numerator,
                observed.denominator,
                baseline.numerator,
                baseline.denominator,
            )
            tested.append(
                _Candidate(
                    observed=observed,
                    baseline=baseline,
                    z_score=z_score,
                    p_value=p_value,
                    q_value=1.0,
                    lift=relative_lift(
                        observed.numerator / observed.denominator,
                        baseline.numerator / baseline.denominator,
                    ),
                )
            )

        q_values = benjamini_hochberg([candidate.p_value for candidate in tested])
        tested = [
            replace(candidate, q_value=q_value)
            for candidate, q_value in zip(tested, q_values, strict=True)
        ]

        significant = [candidate for candidate in tested if candidate.q_value <= config.alpha]
        selected = [
            candidate
            for candidate in significant
            if _passes_lift(
                candidate.observed.numerator / candidate.observed.denominator,
                candidate.baseline.numerator / candidate.baseline.denominator,
                config,
            )
        ]
        selected.sort(key=lambda candidate: (candidate.q_value, -candidate.z_score))

        hits = tuple(
            _build_hit(
                engine,
                candidate,
                config,
                observed_start,
                observed_end,
                baseline_start,
                baseline_end,
            )
            for candidate in selected
        )
        _persist_hits(engine, detection_run_id, hits, config)
        _finish_run(engine, detection_run_id, "completed")
    except Exception:
        _finish_run(engine, detection_run_id, "failed")
        raise

    return DetectionRunResult(
        detection_run_id=detection_run_id,
        config_hash=config.config_hash,
        observed_start=observed_start,
        observed_end=observed_end,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        hits=hits,
        tested_hypotheses=len(tested),
        significant_hypotheses=len(significant),
        suppressed_hypotheses=len(significant) - len(selected),
    )
