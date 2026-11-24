-- 003 — Phase 3 analytics layer
-- KPI definitions follow 04_DATA_DICTIONARY.md and 07_METRICS_AND_DETECTION.md.
-- All rates use shipment-created UTC date cohorts and distinct shipment counts.
-- Evaluation truth is deliberately not referenced here.

CREATE SCHEMA IF NOT EXISTS analytics;

-- Eligible cohort: completed delivery, non-test shipments.
-- A shipment is counted once per cohort date, even if it has multiple incidents.
CREATE OR REPLACE VIEW analytics.eligible_shipments AS
SELECT
    s.shipment_id,
    s.created_at,
    (s.created_at AT TIME ZONE 'UTC')::date AS cohort_date,
    s.delivered_at,
    s.origin_facility_id,
    s.destination_zone_id,
    s.carrier_id,
    s.product_category_id,
    s.packaging_type_id,
    s.shipment_status
FROM shipments s
WHERE s.delivered_at IS NOT NULL
  AND s.shipment_status IN ('delivered', 'returned')
  AND s.is_test_record = FALSE;

-- Confirmed package-damage incidents with defensible operational attribution.
-- related_* values come from the incident's related event and may be null.
CREATE OR REPLACE VIEW analytics.confirmed_damage_incidents AS
SELECT
    i.incident_id,
    i.shipment_id,
    i.reported_at,
    i.confirmed_at,
    i.severity,
    i.damage_type,
    i.estimated_loss_amount,
    i.currency_code,
    e.facility_id AS related_facility_id,
    e.zone_id AS related_zone_id,
    e.carrier_id AS related_carrier_id,
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
    s.origin_facility_id,
    s.destination_zone_id,
    s.carrier_id AS shipment_carrier_id,
    s.product_category_id,
    s.packaging_type_id,
    s.created_at AS shipment_created_at,
    (s.created_at AT TIME ZONE 'UTC')::date AS cohort_date
FROM incidents i
JOIN shipments s ON s.shipment_id = i.shipment_id
LEFT JOIN shipment_events e ON e.event_id = i.related_event_id
WHERE i.incident_type = 'package_damage'
  AND i.incident_status = 'confirmed'
  AND s.delivered_at IS NOT NULL
  AND s.shipment_status IN ('delivered', 'returned')
  AND s.is_test_record = FALSE;

CREATE OR REPLACE VIEW analytics.daily_metrics AS
WITH eligible AS (
    SELECT cohort_date, count(*) AS eligible_shipments
    FROM analytics.eligible_shipments
    GROUP BY cohort_date
),
damage AS (
    SELECT
        cohort_date,
        count(DISTINCT shipment_id) AS confirmed_damage_shipments,
        count(*) AS confirmed_damage_incidents
    FROM analytics.confirmed_damage_incidents
    GROUP BY cohort_date
)
SELECT
    COALESCE(e.cohort_date, d.cohort_date) AS cohort_date,
    COALESCE(e.eligible_shipments, 0)::bigint AS eligible_shipments,
    COALESCE(d.confirmed_damage_shipments, 0)::bigint AS confirmed_damage_shipments,
    COALESCE(d.confirmed_damage_incidents, 0)::bigint AS confirmed_damage_incidents,
    CASE
        WHEN COALESCE(e.eligible_shipments, 0) > 0
        THEN COALESCE(d.confirmed_damage_shipments, 0)::numeric / e.eligible_shipments
        ELSE NULL
    END AS damage_rate,
    CASE
        WHEN COALESCE(e.eligible_shipments, 0) > 0
        THEN (COALESCE(d.confirmed_damage_shipments, 0)::numeric / e.eligible_shipments) * 1000
        ELSE NULL
    END AS damages_per_1000
FROM eligible e
FULL OUTER JOIN damage d ON d.cohort_date = e.cohort_date;

CREATE OR REPLACE VIEW analytics.loss_by_currency_daily AS
SELECT
    cohort_date,
    currency_code,
    count(*)::bigint AS confirmed_damage_incidents,
    sum(estimated_loss_amount) AS estimated_loss_amount
FROM analytics.confirmed_damage_incidents
WHERE estimated_loss_amount IS NOT NULL
  AND currency_code IS NOT NULL
GROUP BY cohort_date, currency_code;

-- One row per scope/date with shipment-level damage numerator and exposure denominator.
-- incident_count is provided separately so incident concentration is never confused
-- with the shipment-level damage rate.
CREATE OR REPLACE VIEW analytics.scope_damage_daily AS
WITH
facility_exposure AS (
    SELECT
        e.facility_id AS scope_id,
        es.cohort_date,
        count(DISTINCT es.shipment_id) AS denominator
    FROM analytics.eligible_shipments es
    JOIN shipment_events e ON e.shipment_id = es.shipment_id
    WHERE e.facility_id IS NOT NULL
    GROUP BY e.facility_id, es.cohort_date
),
facility_damage AS (
    SELECT
        related_facility_id AS scope_id,
        cohort_date,
        count(DISTINCT shipment_id) AS numerator,
        count(*) AS incident_count
    FROM analytics.confirmed_damage_incidents
    WHERE related_facility_id IS NOT NULL
    GROUP BY related_facility_id, cohort_date
),
facility_scope AS (
    SELECT
        'facility'::text AS scope_type,
        COALESCE(x.scope_id, d.scope_id)::text AS scope_id,
        f.facility_name AS scope_name,
        COALESCE(x.cohort_date, d.cohort_date) AS cohort_date,
        COALESCE(d.numerator, 0)::bigint AS numerator,
        COALESCE(x.denominator, 0)::bigint AS denominator,
        COALESCE(d.incident_count, 0)::bigint AS incident_count
    FROM facility_exposure x
    FULL OUTER JOIN facility_damage d
        ON d.scope_id = x.scope_id AND d.cohort_date = x.cohort_date
    LEFT JOIN facilities f ON f.facility_id = COALESCE(x.scope_id, d.scope_id)
),
carrier_exposure AS (
    SELECT
        carrier_id AS scope_id,
        cohort_date,
        count(*) AS denominator
    FROM analytics.eligible_shipments
    WHERE carrier_id IS NOT NULL
    GROUP BY carrier_id, cohort_date
),
carrier_damage AS (
    SELECT
        shipment_carrier_id AS scope_id,
        cohort_date,
        count(DISTINCT shipment_id) AS numerator,
        count(*) AS incident_count
    FROM analytics.confirmed_damage_incidents
    WHERE shipment_carrier_id IS NOT NULL
    GROUP BY shipment_carrier_id, cohort_date
),
carrier_scope AS (
    SELECT
        'carrier'::text AS scope_type,
        COALESCE(x.scope_id, d.scope_id)::text AS scope_id,
        c.carrier_name AS scope_name,
        COALESCE(x.cohort_date, d.cohort_date) AS cohort_date,
        COALESCE(d.numerator, 0)::bigint AS numerator,
        COALESCE(x.denominator, 0)::bigint AS denominator,
        COALESCE(d.incident_count, 0)::bigint AS incident_count
    FROM carrier_exposure x
    FULL OUTER JOIN carrier_damage d
        ON d.scope_id = x.scope_id AND d.cohort_date = x.cohort_date
    LEFT JOIN carriers c ON c.carrier_id = COALESCE(x.scope_id, d.scope_id)
),
zone_exposure AS (
    SELECT
        destination_zone_id AS scope_id,
        cohort_date,
        count(*) AS denominator
    FROM analytics.eligible_shipments
    WHERE destination_zone_id IS NOT NULL
    GROUP BY destination_zone_id, cohort_date
),
zone_damage AS (
    SELECT
        destination_zone_id AS scope_id,
        cohort_date,
        count(DISTINCT shipment_id) AS numerator,
        count(*) AS incident_count
    FROM analytics.confirmed_damage_incidents
    WHERE destination_zone_id IS NOT NULL
    GROUP BY destination_zone_id, cohort_date
),
zone_scope AS (
    SELECT
        'zone'::text AS scope_type,
        COALESCE(x.scope_id, d.scope_id)::text AS scope_id,
        z.zone_name AS scope_name,
        COALESCE(x.cohort_date, d.cohort_date) AS cohort_date,
        COALESCE(d.numerator, 0)::bigint AS numerator,
        COALESCE(x.denominator, 0)::bigint AS denominator,
        COALESCE(d.incident_count, 0)::bigint AS incident_count
    FROM zone_exposure x
    FULL OUTER JOIN zone_damage d
        ON d.scope_id = x.scope_id AND d.cohort_date = x.cohort_date
    LEFT JOIN zones z ON z.zone_id = COALESCE(x.scope_id, d.scope_id)
),
category_exposure AS (
    SELECT
        product_category_id AS scope_id,
        cohort_date,
        count(*) AS denominator
    FROM analytics.eligible_shipments
    WHERE product_category_id IS NOT NULL
    GROUP BY product_category_id, cohort_date
),
category_damage AS (
    SELECT
        product_category_id AS scope_id,
        cohort_date,
        count(DISTINCT shipment_id) AS numerator,
        count(*) AS incident_count
    FROM analytics.confirmed_damage_incidents
    WHERE product_category_id IS NOT NULL
    GROUP BY product_category_id, cohort_date
),
category_scope AS (
    SELECT
        'product_category'::text AS scope_type,
        COALESCE(x.scope_id, d.scope_id)::text AS scope_id,
        pc.category_name AS scope_name,
        COALESCE(x.cohort_date, d.cohort_date) AS cohort_date,
        COALESCE(d.numerator, 0)::bigint AS numerator,
        COALESCE(x.denominator, 0)::bigint AS denominator,
        COALESCE(d.incident_count, 0)::bigint AS incident_count
    FROM category_exposure x
    FULL OUTER JOIN category_damage d
        ON d.scope_id = x.scope_id AND d.cohort_date = x.cohort_date
    LEFT JOIN product_categories pc
        ON pc.product_category_id = COALESCE(x.scope_id, d.scope_id)
),
packaging_exposure AS (
    SELECT
        packaging_type_id AS scope_id,
        cohort_date,
        count(*) AS denominator
    FROM analytics.eligible_shipments
    WHERE packaging_type_id IS NOT NULL
    GROUP BY packaging_type_id, cohort_date
),
packaging_damage AS (
    SELECT
        packaging_type_id AS scope_id,
        cohort_date,
        count(DISTINCT shipment_id) AS numerator,
        count(*) AS incident_count
    FROM analytics.confirmed_damage_incidents
    WHERE packaging_type_id IS NOT NULL
    GROUP BY packaging_type_id, cohort_date
),
packaging_scope AS (
    SELECT
        'packaging_type'::text AS scope_type,
        COALESCE(x.scope_id, d.scope_id)::text AS scope_id,
        pt.packaging_name AS scope_name,
        COALESCE(x.cohort_date, d.cohort_date) AS cohort_date,
        COALESCE(d.numerator, 0)::bigint AS numerator,
        COALESCE(x.denominator, 0)::bigint AS denominator,
        COALESCE(d.incident_count, 0)::bigint AS incident_count
    FROM packaging_exposure x
    FULL OUTER JOIN packaging_damage d
        ON d.scope_id = x.scope_id AND d.cohort_date = x.cohort_date
    LEFT JOIN packaging_types pt
        ON pt.packaging_type_id = COALESCE(x.scope_id, d.scope_id)
),
stage_exposure AS (
    SELECT
        e.stage::text AS scope_id,
        es.cohort_date,
        count(DISTINCT es.shipment_id) AS denominator
    FROM analytics.eligible_shipments es
    JOIN shipment_events e ON e.shipment_id = es.shipment_id
    WHERE e.stage IS NOT NULL
    GROUP BY e.stage, es.cohort_date
),
stage_damage AS (
    SELECT
        related_stage::text AS scope_id,
        cohort_date,
        count(DISTINCT shipment_id) AS numerator,
        count(*) AS incident_count
    FROM analytics.confirmed_damage_incidents
    WHERE related_stage IS NOT NULL
    GROUP BY related_stage, cohort_date
),
stage_scope AS (
    SELECT
        'stage'::text AS scope_type,
        COALESCE(x.scope_id, d.scope_id)::text AS scope_id,
        COALESCE(x.scope_id, d.scope_id)::text AS scope_name,
        COALESCE(x.cohort_date, d.cohort_date) AS cohort_date,
        COALESCE(d.numerator, 0)::bigint AS numerator,
        COALESCE(x.denominator, 0)::bigint AS denominator,
        COALESCE(d.incident_count, 0)::bigint AS incident_count
    FROM stage_exposure x
    FULL OUTER JOIN stage_damage d
        ON d.scope_id = x.scope_id AND d.cohort_date = x.cohort_date
)
SELECT * FROM facility_scope
UNION ALL SELECT * FROM carrier_scope
UNION ALL SELECT * FROM zone_scope
UNION ALL SELECT * FROM category_scope
UNION ALL SELECT * FROM packaging_scope
UNION ALL SELECT * FROM stage_scope;

-- Data-quality observability uses the same UTC shipment-created date cohort.
CREATE OR REPLACE VIEW analytics.data_quality_daily AS
WITH base AS (
    SELECT
        s.shipment_id,
        (s.created_at AT TIME ZONE 'UTC')::date AS cohort_date,
        s.weight_g,
        s.length_mm,
        s.width_mm,
        s.height_mm
    FROM shipments s
    WHERE s.is_test_record = FALSE
),
event_metrics AS (
    SELECT
        b.cohort_date,
        count(*) FILTER (
            WHERE e.recorded_at > e.occurred_at + interval '24 hours'
        )::bigint AS late_recorded_events,
        count(*) FILTER (WHERE e.recorded_at < e.occurred_at)::bigint
            AS timestamp_conflicts,
        count(*) FILTER (WHERE e.facility_id IS NULL)::bigint
            AS events_missing_facility,
        count(*) FILTER (WHERE e.carrier_id IS NULL)::bigint
            AS events_missing_carrier,
        count(*) FILTER (WHERE e.event_code = 'DATA_GAP_DETECTED')::bigint
            AS data_gap_events
    FROM base b
    JOIN shipment_events e ON e.shipment_id = b.shipment_id
    GROUP BY b.cohort_date
),
duplicate_groups AS (
    SELECT
        b.cohort_date,
        e.shipment_id,
        e.event_code,
        e.occurred_at,
        count(*) AS event_count
    FROM base b
    JOIN shipment_events e ON e.shipment_id = b.shipment_id
    GROUP BY b.cohort_date, e.shipment_id, e.event_code, e.occurred_at
),
duplicate_metrics AS (
    SELECT
        cohort_date,
        sum(GREATEST(event_count - 1, 0))::bigint AS duplicate_event_records,
        count(DISTINCT shipment_id) FILTER (WHERE event_count > 1)::bigint
            AS shipments_with_duplicate_event_codes
    FROM duplicate_groups
    GROUP BY cohort_date
),
dimension_metrics AS (
    SELECT
        cohort_date,
        count(*) FILTER (
            WHERE weight_g IS NULL
               OR length_mm IS NULL
               OR width_mm IS NULL
               OR height_mm IS NULL
        )::bigint AS shipments_missing_dimensions
    FROM base
    GROUP BY cohort_date
),
dates AS (
    SELECT cohort_date FROM event_metrics
    UNION
    SELECT cohort_date FROM duplicate_metrics
    UNION
    SELECT cohort_date FROM dimension_metrics
)
SELECT
    dt.cohort_date,
    COALESCE(em.late_recorded_events, 0)::bigint AS late_recorded_events,
    COALESCE(em.timestamp_conflicts, 0)::bigint AS timestamp_conflicts,
    COALESCE(dm.duplicate_event_records, 0)::bigint AS duplicate_event_records,
    COALESCE(dm.shipments_with_duplicate_event_codes, 0)::bigint
        AS shipments_with_duplicate_event_codes,
    COALESCE(em.events_missing_facility, 0)::bigint AS events_missing_facility,
    COALESCE(em.events_missing_carrier, 0)::bigint AS events_missing_carrier,
    COALESCE(dim.shipments_missing_dimensions, 0)::bigint
        AS shipments_missing_dimensions,
    COALESCE(em.data_gap_events, 0)::bigint AS data_gap_events
FROM dates dt
LEFT JOIN event_metrics em ON em.cohort_date = dt.cohort_date
LEFT JOIN duplicate_metrics dm ON dm.cohort_date = dt.cohort_date
LEFT JOIN dimension_metrics dim ON dim.cohort_date = dt.cohort_date;
