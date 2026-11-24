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
    get_daily_metrics,
    get_data_quality,
    get_loss_by_currency,
    get_overview,
    get_scope_hotspots,
    resolve_cohort_range,
)
from loss_intelligence.detection.evaluation import evaluate_validation

DEMO_REVIEWER = "demo_reviewer (synthetic)"

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
            COALESCE(s.shipment_id, si.shipment_id) AS shipment_id,
            COALESCE(s.shipment_code, si.shipment_code) AS shipment_code,
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
            i.currency_code
        FROM anomaly_alert_evidence ev
        LEFT JOIN shipments s
            ON ev.entity_type = 'shipment' AND s.shipment_id = ev.entity_id
        LEFT JOIN incidents i
            ON ev.entity_type = 'incident' AND i.incident_id = ev.entity_id
        LEFT JOIN shipments si ON si.shipment_id = i.shipment_id
        WHERE ev.alert_id = :alert_id
        ORDER BY ev.evidence_role, ev.entity_type, ev.created_at
    """
    with engine.connect() as connection:
        return _rows(connection.execute(text(sql), {"alert_id": alert_id}))


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
    limit: int = 25,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    parameters: dict[str, Any] = {"limit": limit}
    if query and query.strip():
        conditions.append("(s.shipment_code ILIKE :pattern OR s.shipment_id::text ILIKE :pattern)")
        parameters["pattern"] = f"%{query.strip()}%"
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
            i.related_event_id
        FROM incidents i
        WHERE i.shipment_id = :shipment_id
        ORDER BY i.reported_at, i.incident_id
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
            SELECT es.shipment_id
            FROM analytics.eligible_shipments es
            WHERE TRUE
            {filters}
        ),
        returns_window AS (
            SELECT r.*
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

    with engine.connect() as connection:
        totals = dict(connection.execute(text(totals_sql), parameters).one()._mapping)
        reasons = _rows(connection.execute(text(reason_sql), parameters))
        inspections = _rows(connection.execute(text(inspection_sql), parameters))
        conditions = _rows(connection.execute(text(condition_sql), parameters))
        daily = _rows(connection.execute(text(daily_sql), parameters))
        discrepancies = _rows(connection.execute(text(discrepancy_sql), parameters))

    return {
        "totals": totals,
        "by_reason": reasons,
        "by_inspection": inspections,
        "by_condition": conditions,
        "daily": daily,
        "discrepancy_by_reason": discrepancies,
    }


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
            count(a.alert_id)::bigint AS alert_count
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
