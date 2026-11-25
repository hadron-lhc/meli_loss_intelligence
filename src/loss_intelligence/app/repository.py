"""Read and write operations used by the dashboard.

Streamlit page modules should not contain SQL or business rules. Keeping the
data access here also makes the dashboard queries testable without a running
Streamlit server.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from loss_intelligence.analytics.metrics import (
    SCOPE_TYPES,
    build_rate_stats,
    get_daily_metrics,
    get_data_quality,
    get_loss_by_currency,
    get_overview,
    get_scope_hotspots,
    resolve_cohort_range,
)
from loss_intelligence.detection.evaluation import evaluate_validation

DEMO_REVIEWER = "demo_reviewer (synthetic)"

HOTSPOT_SCOPE_TYPES: tuple[str, ...] = (*SCOPE_TYPES, "carrier_zone")
INVESTIGATION_STATUSES = ("open", "in_review", "closed", "dismissed")
INVESTIGATION_OUTCOMES = (
    "confirmed_issue",
    "no_issue_found",
    "data_quality_issue",
    "needs_more_evidence",
    "other",
)
ALERT_STATUSES = ("new", "acknowledged", "investigating", "resolved", "dismissed")
ALERT_PRIORITIES = ("critical", "high", "medium", "low")

SCOPE_NAME_EXPR = """
CASE a.scope_type
    WHEN 'facility' THEN (
        SELECT f.facility_name FROM facilities f WHERE f.facility_id::text = a.scope_id
    )
    WHEN 'carrier' THEN (
        SELECT c.carrier_name FROM carriers c WHERE c.carrier_id::text = a.scope_id
    )
    WHEN 'zone' THEN (
        SELECT z.zone_name FROM zones z WHERE z.zone_id::text = a.scope_id
    )
    WHEN 'product_category' THEN (
        SELECT pc.category_name
        FROM product_categories pc
        WHERE pc.product_category_id::text = a.scope_id
    )
    WHEN 'packaging_type' THEN (
        SELECT pt.packaging_name
        FROM packaging_types pt
        WHERE pt.packaging_type_id::text = a.scope_id
    )
    WHEN 'stage' THEN a.scope_id
    WHEN 'carrier_zone' THEN (
        SELECT c.carrier_name || ' / ' || z.zone_name
        FROM carriers c, zones z
        WHERE c.carrier_id::text = split_part(a.scope_id, ':', 1)
          AND z.zone_id::text = split_part(a.scope_id, ':', 2)
    )
    ELSE a.scope_id
END
"""


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(row._mapping) for row in result]


def cohort_bounds(engine: Engine) -> tuple[date | None, date | None]:
    return resolve_cohort_range(engine)


def data_freshness(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    (
                        SELECT max(created_at)
                        FROM shipments
                        WHERE is_test_record = FALSE
                    ) AS latest_shipment_at,
                    (
                        SELECT max(generated_at)
                        FROM anomaly_alerts
                    ) AS latest_alert_at,
                    (
                        SELECT completed_at
                        FROM meta.generation_runs
                        WHERE status = 'completed'
                        ORDER BY completed_at DESC NULLS LAST, started_at DESC
                        LIMIT 1
                    ) AS latest_generation_at,
                    (
                        SELECT generator_version
                        FROM meta.generation_runs
                        WHERE status = 'completed'
                        ORDER BY completed_at DESC NULLS LAST, started_at DESC
                        LIMIT 1
                    ) AS generator_version
                """
            )
        ).one()
    return dict(row._mapping)


def overview(
    engine: Engine,
    start_date: date | None,
    end_date: date | None,
    *,
    minimum_volume: int,
    confidence: float = 0.95,
    maturity_days: int = 14,
) -> dict[str, Any]:
    return asdict(
        get_overview(
            engine,
            start_date,
            end_date,
            minimum_volume=minimum_volume,
            confidence=confidence,
            maturity_days=maturity_days,
        )
    )


def daily_metrics(
    engine: Engine,
    start_date: date | None,
    end_date: date | None,
    *,
    minimum_volume: int,
    confidence: float = 0.95,
) -> list[dict[str, Any]]:
    return [
        asdict(item)
        for item in get_daily_metrics(
            engine,
            start_date,
            end_date,
            minimum_volume=minimum_volume,
            confidence=confidence,
        )
    ]


def _carrier_zone_hotspots(
    engine: Engine,
    start_date: date | None,
    end_date: date | None,
    *,
    minimum_volume: int,
    confidence: float,
    limit: int | None,
) -> list[dict[str, Any]]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least one")

    conditions: list[str] = []
    parameters: dict[str, Any] = {"minimum_volume": minimum_volume}
    if start_date is not None:
        conditions.append("cohort_date >= :start_date")
        parameters["start_date"] = start_date
    if end_date is not None:
        conditions.append("cohort_date <= :end_date")
        parameters["end_date"] = end_date
    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    and_clause = " AND " + " AND ".join(conditions) if conditions else ""
    limit_clause = " LIMIT :limit" if limit is not None else ""
    if limit is not None:
        parameters["limit"] = limit

    sql = f"""
        WITH exposure AS (
            SELECT
                es.carrier_id::text || ':' || es.destination_zone_id::text AS scope_id,
                c.carrier_name || ' / ' || z.zone_name AS scope_name,
                count(*)::bigint AS denominator
            FROM analytics.eligible_shipments es
            JOIN carriers c ON c.carrier_id = es.carrier_id
            JOIN zones z ON z.zone_id = es.destination_zone_id
            WHERE es.carrier_id IS NOT NULL
              AND es.destination_zone_id IS NOT NULL
              {and_clause}
            GROUP BY es.carrier_id, es.destination_zone_id, c.carrier_name, z.zone_name
        ),
        damage AS (
            SELECT
                cdi.shipment_carrier_id::text || ':' || cdi.destination_zone_id::text AS scope_id,
                count(DISTINCT cdi.shipment_id)::bigint AS numerator,
                count(*)::bigint AS incident_count
            FROM analytics.confirmed_damage_incidents cdi
            WHERE cdi.shipment_carrier_id IS NOT NULL
              AND cdi.destination_zone_id IS NOT NULL
              {and_clause}
            GROUP BY cdi.shipment_carrier_id, cdi.destination_zone_id
        ),
        combined AS (
            SELECT
                COALESCE(x.scope_id, d.scope_id) AS scope_id,
                x.scope_name,
                COALESCE(x.denominator, 0)::bigint AS denominator,
                COALESCE(d.numerator, 0)::bigint AS numerator,
                COALESCE(d.incident_count, 0)::bigint AS incident_count
            FROM exposure x
            LEFT JOIN damage d ON d.scope_id = x.scope_id
        )
        SELECT scope_id, scope_name, denominator, numerator, incident_count
        FROM combined
        ORDER BY
            CASE WHEN denominator >= :minimum_volume THEN 0 ELSE 1 END,
            CASE
                WHEN denominator > 0 THEN numerator::numeric / denominator
                ELSE NULL
            END DESC NULLS LAST,
            denominator DESC,
            scope_id
        {limit_clause}
    """
    with engine.connect() as connection:
        total_incidents = connection.execute(
            text(
                "SELECT count(*)::bigint FROM analytics.confirmed_damage_incidents" + where_clause
            ),
            parameters,
        ).scalar_one()
        rows = connection.execute(text(sql), parameters).all()

    results: list[dict[str, Any]] = []
    for row in rows:
        incident_share = row.incident_count / total_incidents if total_incidents > 0 else None
        stats = build_rate_stats(
            row.numerator,
            row.denominator,
            minimum_volume=minimum_volume,
            confidence=confidence,
        )
        results.append(
            {
                "scope_type": "carrier_zone",
                "scope_id": row.scope_id,
                "scope_name": row.scope_name,
                "eligible_shipments": row.denominator,
                "confirmed_damage_shipments": row.numerator,
                "confirmed_damage_incidents": row.incident_count,
                "incident_share": incident_share,
                "damage": asdict(stats),
            }
        )
    return results


def hotspots(
    engine: Engine,
    scope_type: str,
    start_date: date | None,
    end_date: date | None,
    *,
    minimum_volume: int,
    confidence: float = 0.95,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if scope_type == "carrier_zone":
        return _carrier_zone_hotspots(
            engine,
            start_date,
            end_date,
            minimum_volume=minimum_volume,
            confidence=confidence,
            limit=limit,
        )
    return [
        asdict(item)
        for item in get_scope_hotspots(
            engine,
            scope_type,  # type: ignore[arg-type]
            start_date,
            end_date,
            minimum_volume=minimum_volume,
            confidence=confidence,
            limit=limit,
        )
    ]


def hotspot_drilldown(
    engine: Engine,
    scope_type: str,
    scope_id: str,
    start_date: date | None,
    end_date: date | None,
    *,
    limit: int = 25,
) -> dict[str, Any]:
    if scope_type not in HOTSPOT_SCOPE_TYPES:
        raise ValueError(f"unsupported scope_type: {scope_type}")

    scope_conditions = {
        "facility": "cdi.related_facility_id::text = :scope_id",
        "carrier": "cdi.shipment_carrier_id::text = :scope_id",
        "carrier_zone": (
            "cdi.shipment_carrier_id::text = split_part(:scope_id, ':', 1) "
            "AND cdi.destination_zone_id::text = split_part(:scope_id, ':', 2)"
        ),
        "zone": "cdi.destination_zone_id::text = :scope_id",
        "product_category": "cdi.product_category_id::text = :scope_id",
        "packaging_type": "cdi.packaging_type_id::text = :scope_id",
        "stage": "cdi.related_stage::text = :scope_id",
    }
    parameters: dict[str, Any] = {"scope_type": scope_type, "scope_id": scope_id, "limit": limit}
    date_filters = []
    if start_date is not None:
        date_filters.append("cdi.cohort_date >= :start_date")
        parameters["start_date"] = start_date
    if end_date is not None:
        date_filters.append("cdi.cohort_date <= :end_date")
        parameters["end_date"] = end_date
    date_clause = (" AND " + " AND ".join(date_filters)) if date_filters else ""

    shipments_sql = f"""
        WITH scoped AS (
            SELECT
                cdi.shipment_id,
                cdi.confirmed_at,
                cdi.estimated_loss_amount,
                cdi.currency_code
            FROM analytics.confirmed_damage_incidents cdi
            WHERE {scope_conditions[scope_type]}
            {date_clause}
        ),
        shipment_incidents AS (
            SELECT
                shipment_id,
                count(*)::bigint AS incident_count,
                max(confirmed_at) AS latest_confirmed_at
            FROM scoped
            GROUP BY shipment_id
        ),
        currency_losses AS (
            SELECT
                shipment_id,
                currency_code,
                sum(estimated_loss_amount) AS estimated_loss_amount
            FROM scoped
            WHERE estimated_loss_amount IS NOT NULL
              AND currency_code IS NOT NULL
            GROUP BY shipment_id, currency_code
        ),
        shipment_losses AS (
            SELECT
                shipment_id,
                jsonb_agg(
                    jsonb_build_object(
                        'currency_code', currency_code,
                        'estimated_loss_amount', estimated_loss_amount
                    )
                    ORDER BY currency_code
                ) AS loss_by_currency
            FROM currency_losses
            GROUP BY shipment_id
        )
        SELECT
            s.shipment_id,
            s.shipment_code,
            s.shipment_status,
            s.created_at,
            c.carrier_name,
            z.zone_name AS destination_zone,
            pc.category_name AS product_category,
            si.incident_count,
            si.latest_confirmed_at,
            COALESCE(sl.loss_by_currency, '[]'::jsonb) AS loss_by_currency
        FROM shipment_incidents si
        JOIN shipments s ON s.shipment_id = si.shipment_id
        LEFT JOIN carriers c ON c.carrier_id = s.carrier_id
        LEFT JOIN zones z ON z.zone_id = s.destination_zone_id
        LEFT JOIN product_categories pc ON pc.product_category_id = s.product_category_id
        LEFT JOIN shipment_losses sl ON sl.shipment_id = si.shipment_id
        ORDER BY si.latest_confirmed_at DESC NULLS LAST, s.created_at DESC, s.shipment_code
        LIMIT :limit
    """
    alerts_sql = f"""
        WITH alert_scope AS (
            SELECT a.*, {SCOPE_NAME_EXPR} AS scope_name
            FROM anomaly_alerts a
        )
        SELECT
            a.alert_id,
            a.alert_type,
            a.scope_type,
            a.scope_name,
            a.priority,
            a.status,
            a.observed_rate,
            a.baseline_rate,
            a.generated_at
        FROM alert_scope a
        WHERE a.scope_type = :scope_type
          AND a.scope_id = :scope_id
        ORDER BY a.generated_at DESC, a.alert_id
        LIMIT :limit
    """
    with engine.connect() as connection:
        shipments = _rows(connection.execute(text(shipments_sql), parameters))
        alerts = _rows(connection.execute(text(alerts_sql), parameters))
    return {"shipments": shipments, "alerts": alerts}


def loss_by_currency(
    engine: Engine,
    start_date: date | None,
    end_date: date | None,
) -> list[dict[str, Any]]:
    return [
        asdict(item)
        for item in get_loss_by_currency(engine, start_date=start_date, end_date=end_date)
    ]


def data_quality(
    engine: Engine,
    start_date: date | None,
    end_date: date | None,
) -> dict[str, Any]:
    report = get_data_quality(engine, start_date=start_date, end_date=end_date)
    return asdict(report)


def operational_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    count(*) FILTER (
                        WHERE status IN ('new', 'acknowledged', 'investigating')
                    )::bigint AS open_alerts,
                    count(*) FILTER (WHERE status = 'new')::bigint AS new_alerts,
                    count(*) FILTER (WHERE status = 'investigating')::bigint
                        AS investigating_alerts,
                    (
                        SELECT count(*)::bigint FROM investigations
                        WHERE status IN ('open', 'in_review')
                    ) AS investigation_backlog,
                    (
                        SELECT count(*)::bigint FROM investigations WHERE status = 'open'
                    ) AS open_investigations,
                    (
                        SELECT count(*)::bigint FROM investigations
                        WHERE status = 'in_review'
                    ) AS in_review_investigations
                FROM anomaly_alerts
                """
            )
        ).one()
    return {key: int(value) for key, value in row._mapping.items()}


def alert_filter_options(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    min(generated_at)::date AS first_generated,
                    max(generated_at)::date AS last_generated,
                    array_agg(DISTINCT alert_type ORDER BY alert_type) AS alert_types
                FROM anomaly_alerts
                """
            )
        ).one()
    return dict(row._mapping)


def list_alerts(
    engine: Engine,
    *,
    statuses: Iterable[str] | None = None,
    priorities: Iterable[str] | None = None,
    alert_types: Iterable[str] | None = None,
    generated_start: date | None = None,
    generated_end: date | None = None,
    search: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    statuses = list(statuses or [])
    priorities = list(priorities or [])
    alert_types = list(alert_types or [])

    conditions: list[str] = []
    parameters: dict[str, Any] = {}
    if statuses:
        conditions.append("a.status = ANY(:statuses)")
        parameters["statuses"] = statuses
    if priorities:
        conditions.append("a.priority = ANY(:priorities)")
        parameters["priorities"] = priorities
    if alert_types:
        conditions.append("a.alert_type = ANY(:alert_types)")
        parameters["alert_types"] = alert_types
    if generated_start is not None:
        conditions.append("a.generated_at::date >= :generated_start")
        parameters["generated_start"] = generated_start
    if generated_end is not None:
        conditions.append("a.generated_at::date <= :generated_end")
        parameters["generated_end"] = generated_end
    if search:
        conditions.append(
            "(a.scope_name ILIKE :search OR a.alert_id::text ILIKE :search "
            "OR a.explanation ILIKE :search)"
        )
        parameters["search"] = f"%{search.strip()}%"

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    limit_clause = " LIMIT :limit" if limit is not None else ""
    if limit is not None:
        parameters["limit"] = limit

    sql = f"""
        WITH alert_scope AS (
            SELECT a.*, {SCOPE_NAME_EXPR} AS scope_name
            FROM anomaly_alerts a
        )
        SELECT
            a.alert_id,
            a.alert_type,
            a.scope_type,
            a.scope_id,
            a.scope_name,
            a.observed_start,
            a.observed_end,
            a.baseline_start,
            a.baseline_end,
            a.observed_numerator,
            a.observed_denominator,
            a.observed_rate,
            a.baseline_rate,
            a.anomaly_score,
            a.priority,
            a.status,
            a.explanation,
            a.model_name,
            a.model_version,
            a.generated_at,
            a.detection_run_id,
            inv.investigation_id,
            inv.investigation_status
        FROM alert_scope a
        LEFT JOIN LATERAL (
            SELECT
                i.investigation_id,
                i.status AS investigation_status
            FROM investigations i
            WHERE i.alert_id = a.alert_id
            ORDER BY i.updated_at DESC, i.created_at DESC
            LIMIT 1
        ) inv ON TRUE
        {where_clause}
        ORDER BY
            CASE a.priority
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                ELSE 4
            END,
            a.generated_at DESC,
            a.alert_id
        {limit_clause}
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), parameters))


def get_alert(engine: Engine, alert_id: UUID) -> dict[str, Any] | None:
    sql = f"""
        WITH alert_scope AS (
            SELECT a.*, {SCOPE_NAME_EXPR} AS scope_name
            FROM anomaly_alerts a
        )
        SELECT
            a.*,
            dr.model_name AS run_model_name,
            dr.model_version AS run_model_version,
            dr.completed_at AS run_completed_at,
            inv.investigation_id,
            inv.investigation_status
        FROM alert_scope a
        LEFT JOIN meta.detection_runs dr
            ON dr.detection_run_id = a.detection_run_id
        LEFT JOIN LATERAL (
            SELECT
                i.investigation_id,
                i.status AS investigation_status
            FROM investigations i
            WHERE i.alert_id = a.alert_id
            ORDER BY i.updated_at DESC, i.created_at DESC
            LIMIT 1
        ) inv ON TRUE
        WHERE a.alert_id = :alert_id
    """
    with engine.connect() as connection:
        row = connection.execute(text(sql), {"alert_id": alert_id}).one_or_none()
    return dict(row._mapping) if row is not None else None


def alert_evidence(engine: Engine, alert_id: UUID) -> list[dict[str, Any]]:
    sql = """
        SELECT
            ev.evidence_id,
            ev.entity_type,
            ev.entity_id,
            ev.evidence_role,
            ev.contribution,
            ev.created_at,
            COALESCE(s.shipment_id, si.shipment_id, sr.shipment_id, se.shipment_id)
                AS shipment_id,
            COALESCE(s.shipment_code, si.shipment_code, sr.shipment_code, se.shipment_code)
                AS shipment_code,
            s.shipment_status,
            s.created_at AS shipment_created_at,
            s.delivered_at AS shipment_delivered_at,
            i.incident_id,
            i.incident_type,
            i.incident_status,
            i.severity,
            i.reported_at,
            i.confirmed_at,
            i.estimated_loss_amount,
            i.currency_code,
            r.return_id,
            r.declared_reason AS return_declared_reason,
            r.inspection_outcome AS return_inspection_outcome,
            r.condition_on_return AS return_condition,
            evt.event_id,
            evt.event_code,
            evt.stage AS event_stage
        FROM anomaly_alert_evidence ev
        LEFT JOIN shipments s
            ON ev.entity_type = 'shipment' AND s.shipment_id = ev.entity_id
        LEFT JOIN incidents i
            ON ev.entity_type = 'incident' AND i.incident_id = ev.entity_id
        LEFT JOIN shipments si ON si.shipment_id = i.shipment_id
        LEFT JOIN returns r
            ON ev.entity_type = 'return' AND r.return_id = ev.entity_id
        LEFT JOIN shipments sr ON sr.shipment_id = r.shipment_id
        LEFT JOIN shipment_events evt
            ON ev.entity_type = 'event' AND evt.event_id = ev.entity_id
        LEFT JOIN shipments se ON se.shipment_id = evt.shipment_id
        WHERE ev.alert_id = :alert_id
        ORDER BY ev.evidence_role, ev.entity_type, ev.created_at
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), {"alert_id": alert_id}))


def update_alert_status(
    engine: Engine,
    alert_id: UUID,
    *,
    status: str,
) -> None:
    allowed = {"acknowledged", "dismissed"}
    if status not in allowed:
        raise ValueError(f"unsupported alert triage status: {status}")

    with engine.begin() as connection:
        active_investigation = connection.execute(
            text(
                """
                SELECT 1
                FROM investigations
                WHERE alert_id = :alert_id
                  AND status IN ('open', 'in_review')
                LIMIT 1
                """
            ),
            {"alert_id": alert_id},
        ).scalar_one_or_none()
        if status == "dismissed" and active_investigation is not None:
            raise ValueError(
                "cannot dismiss an alert directly while an active investigation is open"
            )

        updated = connection.execute(
            text(
                """
                UPDATE anomaly_alerts
                SET status = :status
                WHERE alert_id = :alert_id
                RETURNING alert_id
                """
            ),
            {"alert_id": alert_id, "status": status},
        ).one_or_none()
        if updated is None:
            raise ValueError("alert not found")


def alerts_without_active_investigation(
    engine: Engine,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    sql = f"""
        WITH alert_scope AS (
            SELECT a.*, {SCOPE_NAME_EXPR} AS scope_name
            FROM anomaly_alerts a
        )
        SELECT
            a.alert_id,
            a.alert_type,
            a.scope_type,
            a.scope_name,
            a.priority,
            a.status,
            a.generated_at,
            a.explanation
        FROM alert_scope a
        WHERE a.status IN ('new', 'acknowledged', 'investigating')
          AND NOT EXISTS (
              SELECT 1
              FROM investigations i
              WHERE i.alert_id = a.alert_id
                AND i.status IN ('open', 'in_review')
          )
        ORDER BY
            CASE a.priority
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                ELSE 4
            END,
            a.generated_at DESC
        LIMIT :limit
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), {"limit": limit}))


def shipment_search(
    engine: Engine,
    query: str | None = None,
    *,
    status: str | None = None,
    damaged_only: bool = False,
    limit: int = 25,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    parameters: dict[str, Any] = {"limit": limit}
    if query and query.strip():
        conditions.append("(s.shipment_code ILIKE :pattern OR s.shipment_id::text ILIKE :pattern)")
        parameters["pattern"] = f"%{query.strip()}%"
    if status:
        conditions.append("s.shipment_status = :status")
        parameters["status"] = status
    if damaged_only:
        conditions.append(
            """
            EXISTS (
                SELECT 1
                FROM incidents i
                WHERE i.shipment_id = s.shipment_id
                  AND i.incident_type = 'package_damage'
                  AND i.incident_status = 'confirmed'
            )
            """
        )
    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"""
        SELECT
            s.shipment_id,
            s.shipment_code,
            s.shipment_status,
            s.created_at,
            s.delivered_at,
            s.origin_facility_id,
            f.facility_name AS origin_facility,
            c.carrier_name,
            pc.category_name AS product_category,
            pt.packaging_name,
            z.zone_name AS destination_zone
        FROM shipments s
        LEFT JOIN facilities f ON f.facility_id = s.origin_facility_id
        LEFT JOIN carriers c ON c.carrier_id = s.carrier_id
        LEFT JOIN product_categories pc ON pc.product_category_id = s.product_category_id
        LEFT JOIN packaging_types pt ON pt.packaging_type_id = s.packaging_type_id
        LEFT JOIN zones z ON z.zone_id = s.destination_zone_id
        {where_clause}
        ORDER BY s.created_at DESC, s.shipment_code
        LIMIT :limit
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), parameters))


def shipment_detail(engine: Engine, shipment_id: UUID) -> dict[str, Any] | None:
    sql = """
        SELECT
            s.*,
            f.facility_code AS origin_facility_code,
            f.facility_name AS origin_facility,
            z.zone_code AS destination_zone_code,
            z.zone_name AS destination_zone,
            c.carrier_code,
            c.carrier_name,
            pc.category_code,
            pc.category_name AS product_category,
            pc.fragility_class,
            pt.packaging_code,
            pt.packaging_name,
            pt.protection_level
        FROM shipments s
        LEFT JOIN facilities f ON f.facility_id = s.origin_facility_id
        LEFT JOIN zones z ON z.zone_id = s.destination_zone_id
        LEFT JOIN carriers c ON c.carrier_id = s.carrier_id
        LEFT JOIN product_categories pc ON pc.product_category_id = s.product_category_id
        LEFT JOIN packaging_types pt ON pt.packaging_type_id = s.packaging_type_id
        WHERE s.shipment_id = :shipment_id
    """
    with engine.connect() as connection:
        row = connection.execute(text(sql), {"shipment_id": shipment_id}).one_or_none()
    return dict(row._mapping) if row is not None else None


def shipment_events(engine: Engine, shipment_id: UUID) -> list[dict[str, Any]]:
    sql = """
        SELECT
            e.sequence_number,
            e.occurred_at,
            e.recorded_at,
            e.event_code,
            e.event_name,
            e.stage,
            e.event_status,
            e.source_system,
            f.facility_name,
            c.carrier_name,
            z.zone_name,
            e.event_metadata
        FROM shipment_events e
        LEFT JOIN facilities f ON f.facility_id = e.facility_id
        LEFT JOIN carriers c ON c.carrier_id = e.carrier_id
        LEFT JOIN zones z ON z.zone_id = e.zone_id
        WHERE e.shipment_id = :shipment_id
        ORDER BY e.occurred_at, e.sequence_number
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), {"shipment_id": shipment_id}))


def shipment_incidents(engine: Engine, shipment_id: UUID) -> list[dict[str, Any]]:
    sql = """
        SELECT
            i.incident_id,
            i.incident_type,
            i.damage_type,
            i.severity,
            i.incident_status,
            i.reported_at,
            i.confirmed_at,
            i.estimated_loss_amount,
            i.currency_code,
            i.evidence_type,
            i.notes,
            i.related_event_id,
            e.sequence_number AS related_event_sequence,
            e.event_code AS related_event_code,
            e.stage AS related_event_stage
        FROM incidents i
        LEFT JOIN shipment_events e ON e.event_id = i.related_event_id
        WHERE i.shipment_id = :shipment_id
        ORDER BY i.reported_at, i.incident_id
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), {"shipment_id": shipment_id}))


def shipment_returns(engine: Engine, shipment_id: UUID) -> list[dict[str, Any]]:
    sql = """
        SELECT
            return_id,
            initiated_at,
            received_at,
            declared_reason,
            inspection_outcome,
            return_status,
            condition_on_return
        FROM returns
        WHERE shipment_id = :shipment_id
        ORDER BY initiated_at, return_id
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), {"shipment_id": shipment_id}))


def shipment_alerts(engine: Engine, shipment_id: UUID) -> list[dict[str, Any]]:
    sql = f"""
        WITH alert_scope AS (
            SELECT a.*, {SCOPE_NAME_EXPR} AS scope_name
            FROM anomaly_alerts a
        )
        SELECT DISTINCT
            a.alert_id,
            a.alert_type,
            a.scope_type,
            a.scope_name,
            a.priority,
            a.status,
            a.observed_start,
            a.observed_end,
            a.generated_at,
            ev.evidence_role
        FROM anomaly_alert_evidence ev
        JOIN alert_scope a ON a.alert_id = ev.alert_id
        WHERE (ev.entity_type = 'shipment' AND ev.entity_id = :shipment_id)
           OR (
               ev.entity_type = 'incident'
               AND ev.entity_id IN (
                   SELECT incident_id FROM incidents WHERE shipment_id = :shipment_id
               )
           )
        ORDER BY a.generated_at DESC, a.alert_id
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), {"shipment_id": shipment_id}))


def investigation_filter_options(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    array_agg(DISTINCT status ORDER BY status) AS statuses,
                    array_agg(DISTINCT outcome ORDER BY outcome)
                        FILTER (WHERE outcome IS NOT NULL) AS outcomes
                FROM investigations
                """
            )
        ).one()
    return dict(row._mapping)


def list_investigations(
    engine: Engine,
    *,
    statuses: Iterable[str] | None = None,
    outcomes: Iterable[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    statuses = list(statuses or [])
    outcomes = list(outcomes or [])
    conditions: list[str] = []
    parameters: dict[str, Any] = {"limit": limit}
    if statuses:
        conditions.append("i.status = ANY(:statuses)")
        parameters["statuses"] = statuses
    if outcomes:
        conditions.append("i.outcome = ANY(:outcomes)")
        parameters["outcomes"] = outcomes
    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

    sql = f"""
        WITH alert_scope AS (
            SELECT a.*, {SCOPE_NAME_EXPR} AS scope_name
            FROM anomaly_alerts a
        )
        SELECT
            i.investigation_id,
            i.alert_id,
            i.incident_id,
            i.status,
            i.outcome,
            i.reviewer_label,
            i.opened_at,
            i.closed_at,
            i.updated_at,
            i.notes,
            i.recommended_action,
            a.alert_type,
            a.scope_type,
            a.scope_name,
            a.priority AS alert_priority,
            a.status AS alert_status
        FROM investigations i
        LEFT JOIN alert_scope a ON a.alert_id = i.alert_id
        {where_clause}
        ORDER BY
            CASE i.status
                WHEN 'open' THEN 1
                WHEN 'in_review' THEN 2
                WHEN 'closed' THEN 3
                ELSE 4
            END,
            i.updated_at DESC,
            i.investigation_id
        LIMIT :limit
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), parameters))


def investigation_detail(engine: Engine, investigation_id: UUID) -> dict[str, Any] | None:
    sql = f"""
        WITH alert_scope AS (
            SELECT a.*, {SCOPE_NAME_EXPR} AS scope_name
            FROM anomaly_alerts a
        )
        SELECT
            i.*,
            a.alert_type,
            a.scope_type,
            a.scope_name,
            a.priority AS alert_priority,
            a.status AS alert_status,
            a.observed_start,
            a.observed_end,
            a.baseline_start,
            a.baseline_end,
            a.observed_numerator,
            a.observed_denominator,
            a.observed_rate,
            a.baseline_rate,
            a.explanation
        FROM investigations i
        LEFT JOIN alert_scope a ON a.alert_id = i.alert_id
        WHERE i.investigation_id = :investigation_id
    """
    with engine.connect() as connection:
        row = connection.execute(text(sql), {"investigation_id": investigation_id}).one_or_none()
    return dict(row._mapping) if row is not None else None


def investigation_audit(engine: Engine, investigation_id: UUID) -> list[dict[str, Any]]:
    sql = """
        SELECT
            audit_id,
            changed_at,
            changed_by,
            from_status,
            to_status,
            outcome,
            note
        FROM investigation_audit
        WHERE investigation_id = :investigation_id
        ORDER BY changed_at, audit_id
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), {"investigation_id": investigation_id}))


def create_investigation(
    engine: Engine,
    alert_id: UUID,
    *,
    reviewer_label: str = DEMO_REVIEWER,
) -> UUID:
    try:
        with engine.begin() as connection:
            alert_exists = connection.execute(
                text("SELECT 1 FROM anomaly_alerts WHERE alert_id = :alert_id"),
                {"alert_id": alert_id},
            ).scalar_one_or_none()
            if alert_exists is None:
                raise ValueError("alert not found")

            investigation_id = connection.execute(
                text(
                    """
                    INSERT INTO investigations (
                        alert_id,
                        status,
                        reviewer_label,
                        opened_at,
                        created_at,
                        updated_at
                    ) VALUES (
                        :alert_id,
                        'open',
                        :reviewer_label,
                        NOW(),
                        NOW(),
                        NOW()
                    )
                    RETURNING investigation_id
                    """
                ),
                {"alert_id": alert_id, "reviewer_label": reviewer_label},
            ).scalar_one()

            connection.execute(
                text(
                    """
                    UPDATE anomaly_alerts
                    SET status = 'investigating'
                    WHERE alert_id = :alert_id
                      AND status IN ('new', 'acknowledged')
                    """
                ),
                {"alert_id": alert_id},
            )
    except IntegrityError as exc:
        raise ValueError("an active investigation already exists for this alert") from exc
    return investigation_id


def update_investigation(
    engine: Engine,
    investigation_id: UUID,
    *,
    status: str,
    outcome: str | None,
    notes: str | None,
    recommended_action: str | None,
    reviewer_label: str = DEMO_REVIEWER,
) -> None:
    if status not in INVESTIGATION_STATUSES:
        raise ValueError(f"unsupported investigation status: {status}")
    if outcome is not None and outcome not in INVESTIGATION_OUTCOMES:
        raise ValueError(f"unsupported investigation outcome: {outcome}")
    closing = status in {"closed", "dismissed"}
    if closing and outcome is None:
        raise ValueError("closed or dismissed investigations require an outcome")
    if not closing:
        outcome = None

    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    UPDATE investigations
                    SET
                        status = :status,
                        outcome = :outcome,
                        notes = :notes,
                        recommended_action = :recommended_action,
                        reviewer_label = :reviewer_label,
                        closed_at = CASE WHEN :closing THEN NOW() ELSE NULL END
                    WHERE investigation_id = :investigation_id
                    RETURNING alert_id
                    """
                ),
                {
                    "status": status,
                    "outcome": outcome,
                    "notes": notes,
                    "recommended_action": recommended_action,
                    "reviewer_label": reviewer_label,
                    "closing": closing,
                    "investigation_id": investigation_id,
                },
            ).one_or_none()
            if row is None:
                raise ValueError("investigation not found")

            if row.alert_id is not None:
                if status == "dismissed":
                    alert_status = "dismissed"
                elif status == "closed":
                    alert_status = "resolved"
                else:
                    alert_status = "investigating"
                connection.execute(
                    text(
                        """
                        UPDATE anomaly_alerts
                        SET status = :alert_status
                        WHERE alert_id = :alert_id
                        """
                    ),
                    {"alert_status": alert_status, "alert_id": row.alert_id},
                )
    except IntegrityError as exc:
        raise ValueError("an active investigation already exists for this alert") from exc


def returns_summary(
    engine: Engine,
    start_date: date | None,
    end_date: date | None,
) -> dict[str, Any]:
    filters = """
        AND (:start_date IS NULL OR es.cohort_date >= :start_date)
        AND (:end_date IS NULL OR es.cohort_date <= :end_date)
    """
    parameters = {"start_date": start_date, "end_date": end_date}
    eligible_cte = f"""
        eligible AS (
            SELECT es.shipment_id, es.product_category_id
            FROM analytics.eligible_shipments es
            WHERE TRUE
            {filters}
        ),
        returns_window AS (
            SELECT r.*, e.product_category_id
            FROM returns r
            JOIN eligible e ON e.shipment_id = r.shipment_id
        )
    """

    totals_sql = f"""
        WITH {eligible_cte}
        SELECT
            (SELECT count(*) FROM eligible)::bigint AS eligible_shipments,
            (SELECT count(DISTINCT shipment_id) FROM returns_window)::bigint
                AS shipments_with_return,
            (SELECT count(*) FROM returns_window)::bigint AS return_count,
            (
                SELECT count(*)::bigint
                FROM (
                    SELECT shipment_id
                    FROM returns_window
                    GROUP BY shipment_id
                    HAVING count(*) > 1
                ) repeated
            ) AS repeat_shipments,
            (
                SELECT count(*)::bigint
                FROM returns_window
                WHERE inspection_outcome = 'does_not_match_declaration'
            ) AS discrepancy_returns,
            (
                SELECT count(*)::bigint
                FROM returns_window
                WHERE inspection_outcome <> 'not_inspected'
            ) AS inspected_returns,
            (
                SELECT avg(extract(epoch FROM (rw.initiated_at - s.created_at)) / 86400.0)
                FROM returns_window rw
                JOIN shipments s ON s.shipment_id = rw.shipment_id
            ) AS average_days_to_return
    """
    reason_sql = f"""
        WITH {eligible_cte}
        SELECT
            declared_reason,
            count(*)::bigint AS return_count,
            count(DISTINCT shipment_id)::bigint AS shipment_count
        FROM returns_window
        GROUP BY declared_reason
        ORDER BY return_count DESC, declared_reason
    """
    inspection_sql = f"""
        WITH {eligible_cte}
        SELECT
            inspection_outcome,
            count(*)::bigint AS return_count
        FROM returns_window
        GROUP BY inspection_outcome
        ORDER BY return_count DESC, inspection_outcome
    """
    condition_sql = f"""
        WITH {eligible_cte}
        SELECT
            COALESCE(condition_on_return, 'unknown') AS condition_on_return,
            count(*)::bigint AS return_count
        FROM returns_window
        GROUP BY COALESCE(condition_on_return, 'unknown')
        ORDER BY return_count DESC
    """
    daily_sql = f"""
        WITH {eligible_cte}
        SELECT
            initiated_at::date AS return_date,
            count(*)::bigint AS return_count,
            count(DISTINCT shipment_id)::bigint AS shipment_count
        FROM returns_window
        GROUP BY initiated_at::date
        ORDER BY return_date
    """
    discrepancy_sql = f"""
        WITH {eligible_cte}
        SELECT
            declared_reason,
            count(*)::bigint AS return_count
        FROM returns_window
        WHERE inspection_outcome = 'does_not_match_declaration'
        GROUP BY declared_reason
        ORDER BY return_count DESC, declared_reason
    """
    category_sql = f"""
        WITH {eligible_cte},
        eligible_by_cat AS (
            SELECT product_category_id, count(*)::bigint AS eligible_shipments
            FROM eligible
            GROUP BY product_category_id
        ),
        returns_by_cat AS (
            SELECT
                product_category_id,
                count(*)::bigint AS return_count,
                count(DISTINCT shipment_id)::bigint AS shipments_with_return,
                count(*) FILTER (
                    WHERE inspection_outcome = 'does_not_match_declaration'
                )::bigint AS discrepancy_returns
            FROM returns_window
            GROUP BY product_category_id
        )
        SELECT
            pc.category_name,
            ec.eligible_shipments,
            COALESCE(rc.shipments_with_return, 0)::bigint AS shipments_with_return,
            COALESCE(rc.return_count, 0)::bigint AS return_count,
            COALESCE(rc.discrepancy_returns, 0)::bigint AS discrepancy_returns,
            CASE
                WHEN ec.eligible_shipments > 0
                THEN COALESCE(rc.shipments_with_return, 0)::double precision / ec.eligible_shipments
                ELSE NULL
            END AS return_rate
        FROM eligible_by_cat ec
        JOIN product_categories pc ON pc.product_category_id = ec.product_category_id
        LEFT JOIN returns_by_cat rc ON rc.product_category_id = ec.product_category_id
        ORDER BY return_rate DESC NULLS LAST, return_count DESC, pc.category_name
    """
    flagged_sql = f"""
        WITH {eligible_cte},
        per_shipment AS (
            SELECT
                rw.shipment_id,
                count(*)::bigint AS return_count,
                count(*) FILTER (
                    WHERE rw.inspection_outcome = 'does_not_match_declaration'
                )::bigint AS discrepancy_count,
                max(rw.initiated_at) AS latest_initiated_at
            FROM returns_window rw
            GROUP BY rw.shipment_id
            HAVING count(*) > 1
                OR count(*) FILTER (
                    WHERE rw.inspection_outcome = 'does_not_match_declaration'
                ) > 0
        )
        SELECT
            ps.shipment_id,
            s.shipment_code,
            pc.category_name,
            ps.return_count,
            ps.discrepancy_count,
            ps.latest_initiated_at
        FROM per_shipment ps
        JOIN shipments s ON s.shipment_id = ps.shipment_id
        LEFT JOIN product_categories pc ON pc.product_category_id = s.product_category_id
        ORDER BY ps.discrepancy_count DESC, ps.return_count DESC, ps.latest_initiated_at DESC
        LIMIT 25
    """

    with engine.connect() as connection:
        totals = dict(connection.execute(text(totals_sql), parameters).one()._mapping)
        reasons = _rows(connection.execute(text(reason_sql), parameters))
        inspections = _rows(connection.execute(text(inspection_sql), parameters))
        conditions = _rows(connection.execute(text(condition_sql), parameters))
        daily = _rows(connection.execute(text(daily_sql), parameters))
        discrepancies = _rows(connection.execute(text(discrepancy_sql), parameters))
        by_category = _rows(connection.execute(text(category_sql), parameters))
        flagged_shipments = _rows(connection.execute(text(flagged_sql), parameters))

    return {
        "totals": totals,
        "by_reason": reasons,
        "by_inspection": inspections,
        "by_condition": conditions,
        "daily": daily,
        "discrepancy_by_reason": discrepancies,
        "by_category": by_category,
        "flagged_shipments": flagged_shipments,
    }


def validation_window(engine: Engine) -> dict[str, Any] | None:
    sql = """
        SELECT
            min(start_at) AS start_at,
            max(end_at) AS end_at
        FROM evaluation.synthetic_scenarios
        WHERE split = 'validation'
          AND expected_detection = TRUE
    """
    with engine.connect() as connection:
        row = connection.execute(text(sql)).one()
    if row.start_at is None or row.end_at is None:
        return None
    return {"start_at": row.start_at, "end_at": row.end_at}


def detection_runs(engine: Engine, *, limit: int = 50) -> list[dict[str, Any]]:
    sql = """
        SELECT
            dr.detection_run_id,
            dr.model_name,
            dr.model_version,
            dr.config,
            dr.config_hash,
            dr.status,
            dr.started_at,
            dr.completed_at,
            count(a.alert_id)::bigint AS alert_count,
            min(a.observed_start) AS min_observed_start,
            max(a.observed_end) AS max_observed_end
        FROM meta.detection_runs dr
        LEFT JOIN anomaly_alerts a ON a.detection_run_id = dr.detection_run_id
        GROUP BY
            dr.detection_run_id,
            dr.model_name,
            dr.model_version,
            dr.config,
            dr.config_hash,
            dr.status,
            dr.started_at,
            dr.completed_at
        ORDER BY dr.started_at DESC
        LIMIT :limit
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), {"limit": limit}))


def evaluation_summary(
    engine: Engine,
    *,
    detection_run_id: UUID | None = None,
    k: int = 10,
) -> dict[str, Any]:
    summary = evaluate_validation(engine, detection_run_id=detection_run_id, k=k)
    return asdict(summary)
