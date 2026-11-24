from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal
from statistics import NormalDist

from sqlalchemy import Engine, text

from loss_intelligence.analytics.models import (
    AnalyticsSnapshot,
    CurrencyLoss,
    DailyMetric,
    DataQualityDaily,
    DataQualityMetrics,
    DataQualityReport,
    MaturityMetrics,
    OverviewMetrics,
    RateStats,
    ScopeMetric,
    ScopeType,
)

SCOPE_TYPES: tuple[ScopeType, ...] = (
    "facility",
    "carrier",
    "zone",
    "product_category",
    "packaging_type",
    "stage",
)


def wilson_interval(
    successes: int,
    trials: int,
    confidence: float = 0.95,
) -> tuple[float | None, float | None]:
    if trials < 0:
        raise ValueError("trials must be non-negative")
    if successes < 0 or successes > trials:
        raise ValueError("successes must be between zero and trials")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    if trials == 0:
        return None, None

    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    proportion = successes / trials
    denominator = 1 + (z * z / trials)
    centre = (proportion + (z * z / (2 * trials))) / denominator
    margin = (
        z
        * math.sqrt((proportion * (1 - proportion) + (z * z / (4 * trials))) / trials)
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def build_rate_stats(
    numerator: int,
    denominator: int,
    *,
    minimum_volume: int = 30,
    confidence: float = 0.95,
) -> RateStats:
    if minimum_volume < 1:
        raise ValueError("minimum_volume must be at least one")
    if numerator < 0 or denominator < 0:
        raise ValueError("numerator and denominator must be non-negative")
    if numerator > denominator:
        raise ValueError("numerator cannot exceed denominator")

    if denominator == 0:
        return RateStats(
            numerator=numerator,
            denominator=denominator,
            rate=None,
            per_1000=None,
            ci_low=None,
            ci_high=None,
            minimum_volume=minimum_volume,
            low_volume=True,
        )

    rate = numerator / denominator
    ci_low, ci_high = wilson_interval(numerator, denominator, confidence)
    return RateStats(
        numerator=numerator,
        denominator=denominator,
        rate=rate,
        per_1000=rate * 1000,
        ci_low=ci_low,
        ci_high=ci_high,
        minimum_volume=minimum_volume,
        low_volume=denominator < minimum_volume,
    )


def _validate_date_range(start_date: date | None, end_date: date | None) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")


def _date_conditions(
    start_date: date | None,
    end_date: date | None,
    parameters: dict[str, object],
) -> str:
    _validate_date_range(start_date, end_date)
    conditions: list[str] = []
    if start_date is not None:
        conditions.append("cohort_date >= :start_date")
        parameters["start_date"] = start_date
    if end_date is not None:
        conditions.append("cohort_date <= :end_date")
        parameters["end_date"] = end_date
    if not conditions:
        return ""
    return " WHERE " + " AND ".join(conditions)


def resolve_cohort_range(
    engine: Engine,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[date | None, date | None]:
    parameters: dict[str, object] = {}
    where_clause = _date_conditions(start_date, end_date, parameters)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT min(cohort_date) AS start_date, max(cohort_date) AS end_date "
                f"FROM analytics.eligible_shipments{where_clause}"
            ),
            parameters,
        ).one()
    return row.start_date, row.end_date


def _overview_counts(
    engine: Engine,
    start_date: date | None,
    end_date: date | None,
) -> tuple[int, int, int]:
    parameters: dict[str, object] = {}
    where_clause = _date_conditions(start_date, end_date, parameters)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                WITH eligible AS (
                    SELECT count(*)::bigint AS eligible_shipments
                    FROM analytics.eligible_shipments
                    """
                + where_clause
                + """
                ),
                damage AS (
                    SELECT
                        count(DISTINCT shipment_id)::bigint AS damaged_shipments,
                        count(*)::bigint AS damage_incidents
                    FROM analytics.confirmed_damage_incidents
                    """
                + where_clause
                + """
                )
                SELECT
                    eligible.eligible_shipments,
                    damage.damaged_shipments,
                    damage.damage_incidents
                FROM eligible CROSS JOIN damage
                """
            ),
            parameters,
        ).one()
    return row.eligible_shipments, row.damaged_shipments, row.damage_incidents


def get_overview(
    engine: Engine,
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    minimum_volume: int = 30,
    confidence: float = 0.95,
    maturity_days: int = 14,
) -> OverviewMetrics:
    if maturity_days < 0:
        raise ValueError("maturity_days must be non-negative")

    actual_start, actual_end = resolve_cohort_range(engine, start_date, end_date)
    if actual_start is None:
        actual_start = start_date
    if actual_end is None:
        actual_end = end_date

    eligible, damaged, incidents = _overview_counts(engine, start_date, end_date)
    mature_end = actual_end - timedelta(days=maturity_days) if actual_end is not None else None
    if mature_end is not None and actual_start is not None and mature_end >= actual_start:
        mature_eligible, mature_damaged, mature_incidents = _overview_counts(
            engine,
            actual_start,
            mature_end,
        )
    else:
        mature_eligible = mature_damaged = mature_incidents = 0

    return OverviewMetrics(
        start_date=actual_start,
        end_date=actual_end,
        eligible_shipments=eligible,
        confirmed_damage_incidents=incidents,
        damage=build_rate_stats(
            damaged,
            eligible,
            minimum_volume=minimum_volume,
            confidence=confidence,
        ),
        maturity=MaturityMetrics(
            maturity_days=maturity_days,
            mature_end_date=mature_end,
            mature=build_rate_stats(
                mature_damaged,
                mature_eligible,
                minimum_volume=minimum_volume,
                confidence=confidence,
            ),
            immature=build_rate_stats(
                damaged - mature_damaged,
                eligible - mature_eligible,
                minimum_volume=minimum_volume,
                confidence=confidence,
            ),
            mature_damage_incidents=mature_incidents,
            immature_damage_incidents=incidents - mature_incidents,
        ),
    )


def get_daily_metrics(
    engine: Engine,
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    minimum_volume: int = 30,
    confidence: float = 0.95,
) -> tuple[DailyMetric, ...]:
    parameters: dict[str, object] = {}
    where_clause = _date_conditions(start_date, end_date, parameters)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    cohort_date,
                    eligible_shipments,
                    confirmed_damage_shipments,
                    confirmed_damage_incidents
                FROM analytics.daily_metrics
                """
                + where_clause
                + " ORDER BY cohort_date"
            ),
            parameters,
        ).all()

    return tuple(
        DailyMetric(
            cohort_date=row.cohort_date,
            eligible_shipments=row.eligible_shipments,
            confirmed_damage_shipments=row.confirmed_damage_shipments,
            confirmed_damage_incidents=row.confirmed_damage_incidents,
            damage=build_rate_stats(
                row.confirmed_damage_shipments,
                row.eligible_shipments,
                minimum_volume=minimum_volume,
                confidence=confidence,
            ),
        )
        for row in rows
    )


def get_scope_hotspots(
    engine: Engine,
    scope_type: ScopeType,
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    minimum_volume: int = 30,
    confidence: float = 0.95,
    limit: int | None = None,
) -> tuple[ScopeMetric, ...]:
    if scope_type not in SCOPE_TYPES:
        raise ValueError(f"unsupported scope_type: {scope_type}")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least one")

    parameters: dict[str, object] = {"scope_type": scope_type}
    where_clause = _date_conditions(start_date, end_date, parameters)
    with engine.connect() as connection:
        total_incidents = connection.execute(
            text(
                "SELECT count(*)::bigint FROM analytics.confirmed_damage_incidents" + where_clause
            ),
            parameters,
        ).scalar_one()
        query = (
            """
            SELECT
                scope_id,
                scope_name,
                sum(denominator)::bigint AS denominator,
                sum(numerator)::bigint AS numerator,
                sum(incident_count)::bigint AS incident_count
            FROM analytics.scope_damage_daily
            WHERE scope_type = :scope_type
            """
            + (where_clause.replace(" WHERE ", " AND ", 1) if where_clause else "")
            + """
            GROUP BY scope_id, scope_name
            ORDER BY
                CASE WHEN sum(denominator) >= :minimum_volume THEN 0 ELSE 1 END,
                CASE
                    WHEN sum(denominator) > 0
                    THEN sum(numerator)::numeric / sum(denominator)
                    ELSE NULL
                END DESC NULLS LAST,
                sum(denominator) DESC,
                scope_id
            """
        )
        if limit is not None:
            query += " LIMIT :limit"
            parameters["limit"] = limit
        parameters["minimum_volume"] = minimum_volume
        rows = connection.execute(text(query), parameters).all()

    metrics: list[ScopeMetric] = []
    for row in rows:
        incident_share = row.incident_count / total_incidents if total_incidents > 0 else None
        metrics.append(
            ScopeMetric(
                scope_type=scope_type,
                scope_id=row.scope_id,
                scope_name=row.scope_name,
                eligible_shipments=row.denominator,
                confirmed_damage_shipments=row.numerator,
                confirmed_damage_incidents=row.incident_count,
                incident_share=incident_share,
                damage=build_rate_stats(
                    row.numerator,
                    row.denominator,
                    minimum_volume=minimum_volume,
                    confidence=confidence,
                ),
            )
        )
    return tuple(metrics)


def get_loss_by_currency(
    engine: Engine,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[CurrencyLoss, ...]:
    parameters: dict[str, object] = {}
    where_clause = _date_conditions(start_date, end_date, parameters)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    currency_code,
                    sum(confirmed_damage_incidents)::bigint AS damage_incidents,
                    sum(estimated_loss_amount) AS estimated_loss_amount
                FROM analytics.loss_by_currency_daily
                """
                + where_clause
                + """
                GROUP BY currency_code
                ORDER BY currency_code
                """
            ),
            parameters,
        ).all()

    return tuple(
        CurrencyLoss(
            currency_code=row.currency_code,
            confirmed_damage_incidents=row.damage_incidents,
            estimated_loss_amount=Decimal(row.estimated_loss_amount),
        )
        for row in rows
    )


def get_data_quality(
    engine: Engine,
    start_date: date | None = None,
    end_date: date | None = None,
) -> DataQualityReport:
    parameters: dict[str, object] = {}
    where_clause = _date_conditions(start_date, end_date, parameters)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    cohort_date,
                    late_recorded_events,
                    timestamp_conflicts,
                    duplicate_event_records,
                    shipments_with_duplicate_event_codes,
                    events_missing_facility,
                    events_missing_carrier,
                    shipments_missing_dimensions,
                    data_gap_events
                FROM analytics.data_quality_daily
                """
                + where_clause
                + " ORDER BY cohort_date"
            ),
            parameters,
        ).all()

    daily = tuple(
        DataQualityDaily(
            cohort_date=row.cohort_date,
            metrics=DataQualityMetrics(
                late_recorded_events=row.late_recorded_events,
                timestamp_conflicts=row.timestamp_conflicts,
                duplicate_event_records=row.duplicate_event_records,
                shipments_with_duplicate_event_codes=(row.shipments_with_duplicate_event_codes),
                events_missing_facility=row.events_missing_facility,
                events_missing_carrier=row.events_missing_carrier,
                shipments_missing_dimensions=row.shipments_missing_dimensions,
                data_gap_events=row.data_gap_events,
            ),
        )
        for row in rows
    )
    totals = DataQualityMetrics(
        late_recorded_events=sum(item.metrics.late_recorded_events for item in daily),
        timestamp_conflicts=sum(item.metrics.timestamp_conflicts for item in daily),
        duplicate_event_records=sum(item.metrics.duplicate_event_records for item in daily),
        shipments_with_duplicate_event_codes=sum(
            item.metrics.shipments_with_duplicate_event_codes for item in daily
        ),
        events_missing_facility=sum(item.metrics.events_missing_facility for item in daily),
        events_missing_carrier=sum(item.metrics.events_missing_carrier for item in daily),
        shipments_missing_dimensions=sum(
            item.metrics.shipments_missing_dimensions for item in daily
        ),
        data_gap_events=sum(item.metrics.data_gap_events for item in daily),
    )
    return DataQualityReport(totals=totals, daily=daily)


def get_snapshot(
    engine: Engine,
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    minimum_volume: int = 30,
    confidence: float = 0.95,
    maturity_days: int = 14,
    hotspot_limit: int | None = None,
) -> AnalyticsSnapshot:
    effective_start, effective_end = resolve_cohort_range(engine, start_date, end_date)
    query_start = effective_start or start_date
    query_end = effective_end or end_date

    return AnalyticsSnapshot(
        overview=get_overview(
            engine,
            query_start,
            query_end,
            minimum_volume=minimum_volume,
            confidence=confidence,
            maturity_days=maturity_days,
        ),
        daily=get_daily_metrics(
            engine,
            query_start,
            query_end,
            minimum_volume=minimum_volume,
            confidence=confidence,
        ),
        hotspots={
            scope_type: get_scope_hotspots(
                engine,
                scope_type,
                query_start,
                query_end,
                minimum_volume=minimum_volume,
                confidence=confidence,
                limit=hotspot_limit,
            )
            for scope_type in SCOPE_TYPES
        },
        loss_by_currency=get_loss_by_currency(engine, query_start, query_end),
        data_quality=get_data_quality(engine, query_start, query_end),
    )
