from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, text

ELIGIBLE_CTE = """
eligible AS (
    SELECT
        s.shipment_id,
        s.carrier_id,
        s.destination_zone_id,
        s.product_category_id,
        s.packaging_type_id
    FROM shipments s
    WHERE s.created_at >= :start
      AND s.created_at < :end
      AND s.delivered_at IS NOT NULL
      AND s.shipment_status IN ('delivered', 'returned')
      AND s.is_test_record = FALSE
)
"""

CONFIRMED_DAMAGE_CTE = """
damage AS (
    SELECT
        i.incident_id,
        i.shipment_id,
        e.facility_id AS related_facility_id,
        CASE
            WHEN e.event_id IS NULL THEN NULL
            ELSE COALESCE(
                NULLIF(e.stage, 'other'),
                (
                    SELECT prev.stage
                    FROM shipment_events prev
                    WHERE prev.shipment_id = i.shipment_id
                      AND prev.stage <> 'other'
                      AND prev.occurred_at <= COALESCE(i.confirmed_at, i.reported_at)
                    ORDER BY prev.occurred_at DESC, prev.sequence_number DESC
                    LIMIT 1
                )
            )
        END AS related_stage,
        s.carrier_id,
        s.destination_zone_id,
        s.product_category_id,
        s.packaging_type_id
    FROM incidents i
    JOIN shipments s ON s.shipment_id = i.shipment_id
    LEFT JOIN shipment_events e ON e.event_id = i.related_event_id
    WHERE i.incident_type = 'package_damage'
      AND i.incident_status = 'confirmed'
      AND s.created_at >= :start
      AND s.created_at < :end
      AND s.delivered_at IS NOT NULL
      AND s.shipment_status IN ('delivered', 'returned')
      AND s.is_test_record = FALSE
)
"""

DAMAGE_SCOPE_SQL: dict[str, str] = {
    "facility": f"""
        WITH {ELIGIBLE_CTE}, {CONFIRMED_DAMAGE_CTE},
        exposure AS (
            SELECT
                e.facility_id::text AS scope_id,
                f.facility_name AS scope_name,
                count(DISTINCT es.shipment_id) AS denominator
            FROM eligible es
            JOIN shipment_events e ON e.shipment_id = es.shipment_id
            JOIN facilities f ON f.facility_id = e.facility_id
            WHERE e.facility_id IS NOT NULL
            GROUP BY e.facility_id, f.facility_name
        ),
        damage_scope AS (
            SELECT
                related_facility_id::text AS scope_id,
                count(DISTINCT shipment_id) AS numerator
            FROM damage
            WHERE related_facility_id IS NOT NULL
            GROUP BY related_facility_id
        )
        SELECT
            x.scope_id,
            x.scope_name,
            x.denominator,
            COALESCE(d.numerator, 0)::bigint AS numerator
        FROM exposure x
        LEFT JOIN damage_scope d ON d.scope_id = x.scope_id
    """,
    "carrier": f"""
        WITH {ELIGIBLE_CTE}, {CONFIRMED_DAMAGE_CTE},
        exposure AS (
            SELECT
                es.carrier_id::text AS scope_id,
                c.carrier_name AS scope_name,
                count(DISTINCT es.shipment_id) AS denominator
            FROM eligible es
            JOIN carriers c ON c.carrier_id = es.carrier_id
            WHERE es.carrier_id IS NOT NULL
            GROUP BY es.carrier_id, c.carrier_name
        ),
        damage_scope AS (
            SELECT
                carrier_id::text AS scope_id,
                count(DISTINCT shipment_id) AS numerator
            FROM damage
            WHERE carrier_id IS NOT NULL
            GROUP BY carrier_id
        )
        SELECT
            x.scope_id,
            x.scope_name,
            x.denominator,
            COALESCE(d.numerator, 0)::bigint AS numerator
        FROM exposure x
        LEFT JOIN damage_scope d ON d.scope_id = x.scope_id
    """,
    "carrier_zone": f"""
        WITH {ELIGIBLE_CTE}, {CONFIRMED_DAMAGE_CTE},
        exposure AS (
            SELECT
                es.carrier_id::text || ':' || es.destination_zone_id::text AS scope_id,
                c.carrier_name || ' / ' || z.zone_name AS scope_name,
                count(DISTINCT es.shipment_id) AS denominator
            FROM eligible es
            JOIN carriers c ON c.carrier_id = es.carrier_id
            JOIN zones z ON z.zone_id = es.destination_zone_id
            WHERE es.carrier_id IS NOT NULL
            GROUP BY
                es.carrier_id,
                es.destination_zone_id,
                c.carrier_name,
                z.zone_name
        ),
        damage_scope AS (
            SELECT
                carrier_id::text || ':' || destination_zone_id::text AS scope_id,
                count(DISTINCT shipment_id) AS numerator
            FROM damage
            WHERE carrier_id IS NOT NULL
              AND destination_zone_id IS NOT NULL
            GROUP BY carrier_id, destination_zone_id
        )
        SELECT
            x.scope_id,
            x.scope_name,
            x.denominator,
            COALESCE(d.numerator, 0)::bigint AS numerator
        FROM exposure x
        LEFT JOIN damage_scope d ON d.scope_id = x.scope_id
    """,
    "zone": f"""
        WITH {ELIGIBLE_CTE}, {CONFIRMED_DAMAGE_CTE},
        exposure AS (
            SELECT
                es.destination_zone_id::text AS scope_id,
                z.zone_name AS scope_name,
                count(DISTINCT es.shipment_id) AS denominator
            FROM eligible es
            JOIN zones z ON z.zone_id = es.destination_zone_id
            GROUP BY es.destination_zone_id, z.zone_name
        ),
        damage_scope AS (
            SELECT
                destination_zone_id::text AS scope_id,
                count(DISTINCT shipment_id) AS numerator
            FROM damage
            GROUP BY destination_zone_id
        )
        SELECT
            x.scope_id,
            x.scope_name,
            x.denominator,
            COALESCE(d.numerator, 0)::bigint AS numerator
        FROM exposure x
        LEFT JOIN damage_scope d ON d.scope_id = x.scope_id
    """,
    "product_category": f"""
        WITH {ELIGIBLE_CTE}, {CONFIRMED_DAMAGE_CTE},
        exposure AS (
            SELECT
                es.product_category_id::text AS scope_id,
                pc.category_name AS scope_name,
                count(DISTINCT es.shipment_id) AS denominator
            FROM eligible es
            JOIN product_categories pc
                ON pc.product_category_id = es.product_category_id
            GROUP BY es.product_category_id, pc.category_name
        ),
        damage_scope AS (
            SELECT
                product_category_id::text AS scope_id,
                count(DISTINCT shipment_id) AS numerator
            FROM damage
            GROUP BY product_category_id
        )
        SELECT
            x.scope_id,
            x.scope_name,
            x.denominator,
            COALESCE(d.numerator, 0)::bigint AS numerator
        FROM exposure x
        LEFT JOIN damage_scope d ON d.scope_id = x.scope_id
    """,
    "packaging_type": f"""
        WITH {ELIGIBLE_CTE}, {CONFIRMED_DAMAGE_CTE},
        exposure AS (
            SELECT
                es.packaging_type_id::text AS scope_id,
                pt.packaging_name AS scope_name,
                count(DISTINCT es.shipment_id) AS denominator
            FROM eligible es
            JOIN packaging_types pt ON pt.packaging_type_id = es.packaging_type_id
            GROUP BY es.packaging_type_id, pt.packaging_name
        ),
        damage_scope AS (
            SELECT
                packaging_type_id::text AS scope_id,
                count(DISTINCT shipment_id) AS numerator
            FROM damage
            GROUP BY packaging_type_id
        )
        SELECT
            x.scope_id,
            x.scope_name,
            x.denominator,
            COALESCE(d.numerator, 0)::bigint AS numerator
        FROM exposure x
        LEFT JOIN damage_scope d ON d.scope_id = x.scope_id
    """,
    "stage": f"""
        WITH {ELIGIBLE_CTE}, {CONFIRMED_DAMAGE_CTE},
        exposure AS (
            SELECT
                e.stage::text AS scope_id,
                e.stage::text AS scope_name,
                count(DISTINCT es.shipment_id) AS denominator
            FROM eligible es
            JOIN shipment_events e ON e.shipment_id = es.shipment_id
            WHERE e.stage IS NOT NULL
            GROUP BY e.stage
        ),
        damage_scope AS (
            SELECT
                related_stage::text AS scope_id,
                count(DISTINCT shipment_id) AS numerator
            FROM damage
            WHERE related_stage IS NOT NULL
            GROUP BY related_stage
        )
        SELECT
            x.scope_id,
            x.scope_name,
            x.denominator,
            COALESCE(d.numerator, 0)::bigint AS numerator
        FROM exposure x
        LEFT JOIN damage_scope d ON d.scope_id = x.scope_id
    """,
}

SEQUENCE_SQL = f"""
    WITH {ELIGIBLE_CTE},
    flags AS (
        SELECT
            es.shipment_id,
            (
                count(*) FILTER (WHERE e.event_code = 'LINEHAUL_IN_TRANSIT') > 1
                OR count(*) FILTER (WHERE e.event_code = 'DELIVERY_ATTEMPTED') > 1
            ) AS is_anomalous
        FROM eligible es
        JOIN shipment_events e ON e.shipment_id = es.shipment_id
        GROUP BY es.shipment_id
    )
    SELECT
        e.facility_id::text AS scope_id,
        f.facility_name AS scope_name,
        count(DISTINCT es.shipment_id) AS denominator,
        count(DISTINCT es.shipment_id) FILTER (WHERE flags.is_anomalous)::bigint
            AS numerator
    FROM eligible es
    JOIN shipment_events e ON e.shipment_id = es.shipment_id
    JOIN facilities f ON f.facility_id = e.facility_id
    JOIN flags ON flags.shipment_id = es.shipment_id
    WHERE e.facility_id IS NOT NULL
    GROUP BY e.facility_id, f.facility_name
"""

RETURN_SQL = f"""
    WITH {ELIGIBLE_CTE},
    returned AS (
        SELECT DISTINCT shipment_id FROM returns
    )
    SELECT
        es.product_category_id::text AS scope_id,
        pc.category_name AS scope_name,
        count(DISTINCT es.shipment_id) AS denominator,
        count(DISTINCT es.shipment_id) FILTER (WHERE r.shipment_id IS NOT NULL)::bigint
            AS numerator
    FROM eligible es
    JOIN product_categories pc ON pc.product_category_id = es.product_category_id
    LEFT JOIN returned r ON r.shipment_id = es.shipment_id
    GROUP BY es.product_category_id, pc.category_name
"""

DATA_QUALITY_SQL = """
    WITH base AS (
        SELECT
            s.shipment_id,
            s.weight_g,
            s.length_mm,
            s.width_mm,
            s.height_mm
        FROM shipments s
        WHERE s.created_at >= :start
          AND s.created_at < :end
          AND s.is_test_record = FALSE
    ),
    flags AS (
        SELECT
            b.shipment_id,
            (
                b.weight_g IS NULL
                OR b.length_mm IS NULL
                OR b.width_mm IS NULL
                OR b.height_mm IS NULL
            ) AS missing_dimensions,
            bool_or(e.recorded_at > e.occurred_at + interval '24 hours') AS late,
            bool_or(e.recorded_at < e.occurred_at) AS timestamp_conflict,
            bool_or(e.event_code = 'DATA_GAP_DETECTED') AS data_gap,
            count(*) > count(DISTINCT (e.event_code, e.occurred_at)) AS duplicate
        FROM base b
        JOIN shipment_events e ON e.shipment_id = b.shipment_id
        GROUP BY
            b.shipment_id,
            b.weight_g,
            b.length_mm,
            b.width_mm,
            b.height_mm
    )
    SELECT
        e.facility_id::text AS scope_id,
        f.facility_name AS scope_name,
        count(DISTINCT b.shipment_id) AS denominator,
        count(DISTINCT b.shipment_id) FILTER (
            WHERE flags.missing_dimensions
               OR flags.late
               OR flags.timestamp_conflict
               OR flags.data_gap
               OR flags.duplicate
        )::bigint AS numerator
    FROM base b
    JOIN shipment_events e ON e.shipment_id = b.shipment_id
    JOIN facilities f ON f.facility_id = e.facility_id
    JOIN flags ON flags.shipment_id = b.shipment_id
    WHERE e.facility_id IS NOT NULL
    GROUP BY e.facility_id, f.facility_name
"""

EVIDENCE_DAMAGE_CONDITIONS = {
    "facility": "e.facility_id = CAST(:scope_id AS UUID)",
    "stage": "e.stage = :scope_id",
    "carrier": "s.carrier_id = CAST(:scope_id AS UUID)",
    "carrier_zone": (
        "s.carrier_id = CAST(split_part(:scope_id, ':', 1) AS UUID) "
        "AND s.destination_zone_id = CAST(split_part(:scope_id, ':', 2) AS UUID)"
    ),
    "zone": "s.destination_zone_id = CAST(:scope_id AS UUID)",
    "product_category": "s.product_category_id = CAST(:scope_id AS UUID)",
    "packaging_type": "s.packaging_type_id = CAST(:scope_id AS UUID)",
}

SEQUENCE_EVIDENCE_SQL = f"""
    WITH {ELIGIBLE_CTE},
    flags AS (
        SELECT
            es.shipment_id,
            (
                count(*) FILTER (WHERE e.event_code = 'LINEHAUL_IN_TRANSIT') > 1
                OR count(*) FILTER (WHERE e.event_code = 'DELIVERY_ATTEMPTED') > 1
            ) AS is_anomalous
        FROM eligible es
        JOIN shipment_events e ON e.shipment_id = es.shipment_id
        GROUP BY es.shipment_id
    )
    SELECT DISTINCT es.shipment_id
    FROM eligible es
    JOIN shipment_events e ON e.shipment_id = es.shipment_id
    JOIN flags ON flags.shipment_id = es.shipment_id
    WHERE e.facility_id = CAST(:scope_id AS UUID)
      AND flags.is_anomalous
    ORDER BY es.shipment_id
    LIMIT :limit
"""

RETURN_EVIDENCE_SQL = f"""
    WITH {ELIGIBLE_CTE}
    SELECT DISTINCT es.shipment_id
    FROM eligible es
    JOIN returns r ON r.shipment_id = es.shipment_id
    WHERE es.product_category_id = CAST(:scope_id AS UUID)
    ORDER BY es.shipment_id
    LIMIT :limit
"""

DATA_QUALITY_EVIDENCE_SQL = """
    WITH base AS (
        SELECT
            s.shipment_id,
            s.weight_g,
            s.length_mm,
            s.width_mm,
            s.height_mm
        FROM shipments s
        WHERE s.created_at >= :start
          AND s.created_at < :end
          AND s.is_test_record = FALSE
    ),
    flags AS (
        SELECT
            b.shipment_id,
            (
                b.weight_g IS NULL
                OR b.length_mm IS NULL
                OR b.width_mm IS NULL
                OR b.height_mm IS NULL
            ) AS missing_dimensions,
            bool_or(e.recorded_at > e.occurred_at + interval '24 hours') AS late,
            bool_or(e.recorded_at < e.occurred_at) AS timestamp_conflict,
            bool_or(e.event_code = 'DATA_GAP_DETECTED') AS data_gap,
            count(*) > count(DISTINCT (e.event_code, e.occurred_at)) AS duplicate
        FROM base b
        JOIN shipment_events e ON e.shipment_id = b.shipment_id
        GROUP BY
            b.shipment_id,
            b.weight_g,
            b.length_mm,
            b.width_mm,
            b.height_mm
    )
    SELECT DISTINCT b.shipment_id
    FROM base b
    JOIN shipment_events e ON e.shipment_id = b.shipment_id
    JOIN flags ON flags.shipment_id = b.shipment_id
    WHERE e.facility_id = CAST(:scope_id AS UUID)
      AND (
          flags.missing_dimensions
          OR flags.late
          OR flags.timestamp_conflict
          OR flags.data_gap
          OR flags.duplicate
      )
    ORDER BY b.shipment_id
    LIMIT :limit
"""


@dataclass(frozen=True, slots=True)
class MetricRow:
    metric_key: str
    alert_type: str
    scope_type: str
    scope_id: str
    scope_name: str | None
    numerator: int
    denominator: int


def _metric_rows(
    engine: Engine,
    sql: str,
    start: datetime,
    end: datetime,
    *,
    metric_key: str,
    alert_type: str,
    scope_type: str,
) -> list[MetricRow]:
    with engine.connect() as connection:
        rows = connection.execute(text(sql), {"start": start, "end": end}).all()
    return [
        MetricRow(
            metric_key=metric_key,
            alert_type=alert_type,
            scope_type=scope_type,
            scope_id=str(row.scope_id),
            scope_name=row.scope_name,
            numerator=row.numerator,
            denominator=row.denominator,
        )
        for row in rows
    ]


def collect_metric_rows(
    engine: Engine,
    start: datetime,
    end: datetime,
) -> list[MetricRow]:
    damage_alert_types = {
        "facility": "damage_rate_spike",
        "carrier": "carrier_deviation",
        "carrier_zone": "carrier_deviation",
        "zone": "damage_rate_spike",
        "product_category": "product_profile_deviation",
        "packaging_type": "product_profile_deviation",
        "stage": "stage_concentration",
    }
    rows: list[MetricRow] = []
    for scope_type, sql in DAMAGE_SCOPE_SQL.items():
        rows.extend(
            _metric_rows(
                engine,
                sql,
                start,
                end,
                metric_key="damage_rate",
                alert_type=damage_alert_types[scope_type],
                scope_type=scope_type,
            )
        )
    rows.extend(
        _metric_rows(
            engine,
            SEQUENCE_SQL,
            start,
            end,
            metric_key="sequence_anomaly_rate",
            alert_type="event_sequence_outlier",
            scope_type="facility",
        )
    )
    rows.extend(
        _metric_rows(
            engine,
            RETURN_SQL,
            start,
            end,
            metric_key="return_rate",
            alert_type="return_pattern_outlier",
            scope_type="product_category",
        )
    )
    rows.extend(
        _metric_rows(
            engine,
            DATA_QUALITY_SQL,
            start,
            end,
            metric_key="data_quality_issue_rate",
            alert_type="data_quality",
            scope_type="facility",
        )
    )
    return rows


def damage_evidence(
    engine: Engine,
    scope_type: str,
    scope_id: str,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[tuple[UUID, UUID]]:
    condition = EVIDENCE_DAMAGE_CONDITIONS[scope_type]
    sql = f"""
        SELECT DISTINCT s.shipment_id, i.incident_id
        FROM incidents i
        JOIN shipments s ON s.shipment_id = i.shipment_id
        LEFT JOIN shipment_events e ON e.event_id = i.related_event_id
        WHERE i.incident_type = 'package_damage'
          AND i.incident_status = 'confirmed'
          AND s.created_at >= :start
          AND s.created_at < :end
          AND s.delivered_at IS NOT NULL
          AND s.shipment_status IN ('delivered', 'returned')
          AND s.is_test_record = FALSE
          AND {condition}
        ORDER BY s.shipment_id
        LIMIT :limit
    """
    with engine.connect() as connection:
        rows = connection.execute(
            text(sql),
            {
                "start": start,
                "end": end,
                "scope_id": scope_id,
                "limit": limit,
            },
        ).all()
    return [(row.shipment_id, row.incident_id) for row in rows]


def shipment_evidence(
    engine: Engine,
    sql: str,
    scope_id: str,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[UUID]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(sql),
                {
                    "start": start,
                    "end": end,
                    "scope_id": scope_id,
                    "limit": limit,
                },
            ).scalars()
        )
