# 04 — Data Dictionary

## Conventions

- Database: PostgreSQL.
- Primary keys: UUID unless otherwise stated.
- Timestamps: `TIMESTAMPTZ`, stored in UTC.
- Dates shown in UI: converted to the selected operating timezone.
- Currency: store `currency_code` (ISO 4217) with monetary amounts. Do not mix currencies in an aggregate without explicit conversion.
- Units: weight in grams (`weight_g`); dimensions in millimetres (`length_mm`, `width_mm`, `height_mm`).
- IDs: synthetic opaque identifiers. Do not use real Mercado Libre shipment IDs.
- Nullable fields: allowed only when the information is genuinely unknown/not applicable.
- `created_at` and `updated_at`: UTC audit timestamps where applicable.

## A. Reference dimensions

### `facilities`
**Grain:** one row per synthetic logistics facility / operational node.

| Field | Type | Required | Meaning / rules |
|---|---|---:|---|
| facility_id | UUID | Yes | PK. |
| facility_code | TEXT | Yes | Unique synthetic code, e.g. `FC-BA-001`. |
| facility_name | TEXT | Yes | Fictional display name. |
| facility_type | TEXT | Yes | `fulfillment`, `cross_dock`, `sortation`, `last_mile_hub`, `pickup_point`, `other`. |
| zone_id | UUID | No | FK to `zones`; may be null for non-geographic nodes. |
| active_from | DATE | Yes | Start of simulated operation. |
| active_to | DATE | No | End date if inactive. |
| is_active | BOOLEAN | Yes | Current synthetic status. |

### `zones`
**Grain:** one row per synthetic operating zone.

| Field | Type | Required | Meaning / rules |
|---|---|---:|---|
| zone_id | UUID | Yes | PK. |
| zone_code | TEXT | Yes | Unique synthetic code. |
| zone_name | TEXT | Yes | Fictional zone name. |
| region | TEXT | Yes | Fictional region/province grouping. |
| country_code | CHAR(2) | Yes | ISO country code; synthetic geography only. |

### `carriers`
**Grain:** one row per synthetic carrier.

| Field | Type | Required | Meaning / rules |
|---|---|---:|---|
| carrier_id | UUID | Yes | PK. |
| carrier_code | TEXT | Yes | Unique synthetic code. |
| carrier_name | TEXT | Yes | Fictional carrier name. |
| carrier_type | TEXT | Yes | `third_party`, `owned_fleet`, `postal`, `other`. |
| active_from | DATE | Yes | Start of simulated operation. |
| active_to | DATE | No | End date if inactive. |

### `product_categories`
**Grain:** one row per synthetic product category.

| Field | Type | Required | Meaning / rules |
|---|---|---:|---|
| product_category_id | UUID | Yes | PK. |
| category_code | TEXT | Yes | Unique code. |
| category_name | TEXT | Yes | Generic category, not real SKU/brand. |
| fragility_class | TEXT | Yes | `low`, `medium`, `high`, `unknown`. |

### `packaging_types`
**Grain:** one row per synthetic packaging profile.

| Field | Type | Required | Meaning / rules |
|---|---|---:|---|
| packaging_type_id | UUID | Yes | PK. |
| packaging_code | TEXT | Yes | Unique code. |
| packaging_name | TEXT | Yes | e.g. `corrugated_box`, `poly_mailer`, `protective_wrap`, `rigid_container`. |
| protection_level | TEXT | Yes | `low`, `medium`, `high`, `unknown`. |

## B. Core facts

### `shipments`
**Grain:** one row per shipment, not one row per package item.

| Field | Type | Required | Meaning / rules |
|---|---|---:|---|
| shipment_id | UUID | Yes | PK. |
| shipment_code | TEXT | Yes | Unique synthetic human-readable ID. |
| created_at | TIMESTAMPTZ | Yes | Shipment creation time. |
| dispatched_at | TIMESTAMPTZ | No | Dispatch time. |
| delivered_at | TIMESTAMPTZ | No | Delivery time. |
| origin_facility_id | UUID | No | FK `facilities`; nullable if unknown. |
| destination_zone_id | UUID | Yes | FK `zones`. |
| carrier_id | UUID | No | FK `carriers`; nullable if not assigned. |
| product_category_id | UUID | Yes | FK `product_categories`. |
| packaging_type_id | UUID | Yes | FK `packaging_types`. |
| weight_g | INTEGER | No | Positive weight in grams. |
| length_mm | INTEGER | No | Positive length. |
| width_mm | INTEGER | No | Positive width. |
| height_mm | INTEGER | No | Positive height. |
| declared_value | NUMERIC(14,2) | No | Synthetic declared/estimated value; not necessarily loss amount. |
| currency_code | CHAR(3) | No | ISO currency for declared_value. |
| shipment_status | TEXT | Yes | `created`, `in_transit`, `delivered`, `returned`, `cancelled`, `lost`, `unknown`. |
| is_test_record | BOOLEAN | Yes | Default false; true only for explicitly marked fixtures. |
| created_record_at | TIMESTAMPTZ | Yes | Row creation timestamp. |

Constraints:
- Dimensions and weight must be positive when present.
- `delivered_at >= dispatched_at` when both are present.
- `declared_value >= 0`.
- `currency_code` required when `declared_value` is present.
- Shipment status is a latest-state convenience only; event history is authoritative for chronology.

### `shipment_events`
**Grain:** one row per event emitted/recorded for one shipment.

| Field | Type | Required | Meaning / rules |
|---|---|---:|---|
| event_id | UUID | Yes | PK. |
| shipment_id | UUID | Yes | FK `shipments`. |
| event_code | TEXT | Yes | Canonical PoC code from `06_EVENT_TAXONOMY.md`; not an official Mercado Libre code. |
| event_name | TEXT | Yes | Human-readable canonical event name. |
| stage | TEXT | Yes | `origin_processing`, `linehaul`, `destination_processing`, `last_mile`, `delivery`, `reverse_logistics`, `other`. |
| event_status | TEXT | Yes | `normal`, `exception`, `informational`, `unknown`. |
| occurred_at | TIMESTAMPTZ | Yes | When event occurred. |
| recorded_at | TIMESTAMPTZ | Yes | When event was recorded; may be later than occurred_at. |
| facility_id | UUID | No | FK `facilities`; null if event not tied to a facility. |
| zone_id | UUID | No | FK `zones`; null if unknown. |
| carrier_id | UUID | No | FK `carriers`; null if not applicable/known. |
| sequence_number | INTEGER | Yes | Deterministic sequence within shipment; unique per shipment. |
| source_system | TEXT | Yes | Synthetic source label, e.g. `simulator_tracking`. |
| event_metadata | JSONB | No | Small, documented, non-sensitive event attributes. |

Constraints:
- Unique `(shipment_id, sequence_number)`.
- `recorded_at >= occurred_at` is preferred; allow violations only if explicitly modelled as clock/data-quality anomalies and documented.
- Never store hidden scenario truth in event metadata.
- Do not encode the target label in event codes.

### `incidents`
**Grain:** one row per confirmed operational incident. A shipment can have more than one incident if genuinely distinct incidents occur.

| Field | Type | Required | Meaning / rules |
|---|---|---:|---|
| incident_id | UUID | Yes | PK. |
| shipment_id | UUID | Yes | FK `shipments`. |
| related_event_id | UUID | No | FK `shipment_events`; event associated with incident if known. |
| incident_type | TEXT | Yes | MVP: `package_damage`; later may include `package_loss`, `tampering`, `other`. |
| damage_type | TEXT | No | `crushed`, `torn`, `punctured`, `wet`, `broken_contents`, `deformed`, `other`, `unknown`. Required for package_damage unless unknown. |
| severity | TEXT | Yes | `low`, `medium`, `high`, `critical`, `unknown`. |
| reported_at | TIMESTAMPTZ | Yes | When reported. |
| confirmed_at | TIMESTAMPTZ | No | When reviewed/confirmed; null while pending. |
| incident_status | TEXT | Yes | `reported`, `under_review`, `confirmed`, `rejected`, `closed`. |
| estimated_loss_amount | NUMERIC(14,2) | No | Synthetic estimate, not actual MELI loss. |
| currency_code | CHAR(3) | No | Currency for estimated loss. |
| evidence_type | TEXT | Yes | `photo`, `inspection`, `customer_report`, `carrier_report`, `multiple`, `unknown`. |
| notes | TEXT | No | Synthetic neutral notes; no personal data. |
| created_at | TIMESTAMPTZ | Yes | Record creation time. |

Constraints:
- Only `incident_status='confirmed'` contributes to confirmed damage KPI.
- `confirmed_at` required for confirmed status.
- Amount must be non-negative; currency required when amount exists.
- A damage incident must not be inferred solely from an anomaly alert.

### `returns`
**Grain:** one row per return process linked to an original shipment.

| Field | Type | Required | Meaning / rules |
|---|---|---:|---|
| return_id | UUID | Yes | PK. |
| shipment_id | UUID | Yes | FK `shipments`. |
| initiated_at | TIMESTAMPTZ | Yes | Return initiation time. |
| received_at | TIMESTAMPTZ | No | Return received time. |
| declared_reason | TEXT | Yes | `damaged`, `wrong_item`, `not_as_described`, `changed_mind`, `size_fit`, `missing_parts`, `other`, `unknown`. |
| inspection_outcome | TEXT | Yes | `not_inspected`, `matches_declaration`, `does_not_match_declaration`, `inconclusive`, `unknown`. |
| return_status | TEXT | Yes | `initiated`, `in_transit`, `received`, `inspected`, `closed`, `cancelled`. |
| condition_on_return | TEXT | No | `new`, `used`, `damaged`, `incomplete`, `unknown`. |
| created_at | TIMESTAMPTZ | Yes | Record creation time. |

Constraints:
- A return declaration is not proof of fraud or even proof that the original shipment was damaged.
- `does_not_match_declaration` is an inspection discrepancy, not a fraud verdict.

## C. Detection and human workflow

### `anomaly_alerts`
**Grain:** one row per generated alert for a scope/entity/window/model run.

| Field | Type | Required | Meaning / rules |
|---|---|---:|---|
| alert_id | UUID | Yes | PK. |
| alert_type | TEXT | Yes | `damage_rate_spike`, `stage_concentration`, `carrier_deviation`, `product_profile_deviation`, `event_sequence_outlier`, `return_pattern_outlier`, `data_quality`. |
| scope_type | TEXT | Yes | `facility`, `carrier`, `carrier_zone`, `zone`, `stage`, `product_category`, `packaging_type`, `shipment`, `return`, `global`. |
| scope_id | TEXT | No | String representation of entity key; null for global. |
| observed_start | TIMESTAMPTZ | Yes | Observed window start. |
| observed_end | TIMESTAMPTZ | Yes | Observed window end. |
| baseline_start | TIMESTAMPTZ | No | Baseline window start. |
| baseline_end | TIMESTAMPTZ | No | Baseline window end. |
| observed_numerator | INTEGER | No | Incident count / anomaly count. |
| observed_denominator | INTEGER | No | Eligible shipment count. |
| observed_rate | NUMERIC(12,6) | No | Observed rate. |
| baseline_rate | NUMERIC(12,6) | No | Reference rate. |
| anomaly_score | NUMERIC(12,6) | No | Model score, not probability unless calibrated. |
| priority | TEXT | Yes | `low`, `medium`, `high`, `critical`. |
| explanation | TEXT | Yes | Human-readable reason, with metric context. |
| model_name | TEXT | Yes | `statistical_rules`, `isolation_forest`, etc. |
| model_version | TEXT | Yes | Version / run identifier. |
| status | TEXT | Yes | `new`, `acknowledged`, `investigating`, `resolved`, `dismissed`. |
| generated_at | TIMESTAMPTZ | Yes | Alert creation time. |

Constraints:
- Alert does not assert incident or culpability.
- `observed_end > observed_start`.
- If numerator and denominator exist, denominator must be > 0 and numerator >= 0.
- Score must not be labelled probability unless calibration is demonstrated.

### `investigations`
**Grain:** one row per human review case. An alert may have one or more investigations only if the workflow explicitly supports it; MVP should enforce one active investigation per alert.

| Field | Type | Required | Meaning / rules |
|---|---|---:|---|
| investigation_id | UUID | Yes | PK. |
| alert_id | UUID | No | FK `anomaly_alerts`; may be null for manually opened incident review. |
| incident_id | UUID | No | FK `incidents`; optional. |
| status | TEXT | Yes | `open`, `in_review`, `closed`, `dismissed`. |
| outcome | TEXT | No | `confirmed_issue`, `no_issue_found`, `data_quality_issue`, `needs_more_evidence`, `other`. |
| reviewer_label | TEXT | Yes | Synthetic/demo reviewer label. |
| opened_at | TIMESTAMPTZ | Yes | Open time. |
| closed_at | TIMESTAMPTZ | No | Close time. |
| notes | TEXT | No | Neutral review notes. |
| recommended_action | TEXT | No | Suggested operational follow-up, not automated enforcement. |
| created_at | TIMESTAMPTZ | Yes | Record creation time. |
| updated_at | TIMESTAMPTZ | Yes | Last update. |

Constraints:
- At least one of `alert_id` or `incident_id` must be non-null.
- Closed/dismissed cases should have an outcome and closed_at.
- No personal data.

## D. Evaluation-only data (must not leak into production features)

### `synthetic_scenarios`
**Grain:** one row per intentionally injected synthetic scenario.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| scenario_id | UUID | Yes | PK. |
| scenario_code | TEXT | Yes | Unique scenario identifier. |
| scenario_type | TEXT | Yes | e.g. `facility_rate_shift`, `carrier_zone_shift`, `packaging_risk_shift`, `event_sequence_shift`, `return_pattern_shift`. |
| description | TEXT | Yes | What was injected. |
| split | TEXT | Yes | `train`, `validation`, `test`. |
| start_at | TIMESTAMPTZ | Yes | Scenario start. |
| end_at | TIMESTAMPTZ | Yes | Scenario end. |
| affected_entity_type | TEXT | Yes | Facility/carrier/zone/category etc. |
| affected_entity_id | TEXT | Yes | Synthetic entity identifier. |
| expected_detection | BOOLEAN | Yes | Whether detection is expected. `FALSE` marks a negative control with no injected effect. |

### `synthetic_truth_links`
**Grain:** one row per link between a scenario and an affected shipment/event/incident.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| truth_link_id | UUID | Yes | PK. |
| scenario_id | UUID | Yes | FK `synthetic_scenarios`. |
| entity_type | TEXT | Yes | `shipment`, `event`, `incident`, `return`. |
| entity_id | UUID | Yes | ID of affected synthetic record. |
| truth_role | TEXT | Yes | `affected`, `control`, `background`. |

These tables belong in a separate evaluation schema or isolated files. They must never be joined into feature-generation queries, model training features, operational dashboard filters, or alert explanations. Only the evaluation module may read them.

## E. Derived analytics models (views/dbt models, not necessarily OLTP tables)

Recommended:
- `fct_shipment_daily`: one row per date × facility × carrier × zone × product category (only dimensions with defensible attribution).
- `fct_damage_incidents`: one row per confirmed incident.
- `fct_shipment_event_sequences`: one row per shipment with derived sequence features.
- `mart_damage_rates`: numerator, denominator, rate and uncertainty by comparison group/window.
- `mart_alert_performance`: alert outcomes and evaluation metrics.

Do not pre-aggregate away the event-level data needed for drill-down.
