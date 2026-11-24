# Analytics Layer

> Independent proof of concept. Synthetic data only. Not affiliated with or endorsed by Mercado Libre.

The Phase 3 analytics layer exposes shipment-level damage KPIs, hotspots, currency-separated
loss estimates and data-quality observability. It reads operational tables only. Synthetic
scenario truth in `evaluation.*` is never referenced by analytics SQL or Python.

## Commands

```bash
make migrate
make analytics
```

`make analytics` prints the full JSON snapshot from the main database. Useful overrides:

```bash
make analytics ANALYTICS_COMMAND=overview
make analytics ANALYTICS_COMMAND=daily START_DATE=2026-02-01 END_DATE=2026-02-28
make analytics ANALYTICS_COMMAND=hotspots SCOPE_TYPE=facility MIN_VOLUME=50 LIMIT=10
make analytics ANALYTICS_COMMAND=loss
make analytics ANALYTICS_COMMAND=data-quality
make analytics ANALYTICS_DB=test
```

Valid `ANALYTICS_COMMAND` values are `snapshot`, `overview`, `daily`, `hotspots`, `loss`
and `data-quality`. Valid `SCOPE_TYPE` values are `facility`, `carrier`, `zone`,
`product_category`, `packaging_type` and `stage`.

The equivalent Python entry point is:

```bash
uv run python -m loss_intelligence.analytics.cli hotspots \
  --database main --scope-type facility --start-date 2026-02-01 \
  --end-date 2026-02-28 --minimum-volume 50 --limit 10
```

## Cohort and eligibility

- Cohort date is the UTC date of `shipments.created_at`.
- Incidents are assigned to the cohort of their shipment, not to `reported_at` or
  `confirmed_at`.
- Eligible shipments have `delivered_at IS NOT NULL`, status `delivered` or `returned`,
  and `is_test_record = FALSE`.
- Cancelled, lost, in-transit and test shipments are excluded from denominators.
- A shipment appears once in its cohort even when it has multiple events or incidents.
- Overview and snapshot output include a maturity split with a default 14-day horizon:
  `mature` cohorts are at or before `end_date - 14 days`; later cohorts are `immature`.
  The all-cohort rate remains available, but recent immature cohorts should not be
  interpreted as a decline. Use `--maturity-days` to override the horizon.

## Confirmed damage

A confirmed damage incident requires:

- `incident_type = 'package_damage'`
- `incident_status = 'confirmed'`
- an eligible shipment under the cohort rules above

`confirmed_damage_shipments` counts distinct shipments. `confirmed_damage_incidents`
counts incident rows. Shipment-level rates always use the distinct-shipment numerator.

## Primary metrics

```text
damage_rate       = distinct confirmed-damage shipments / eligible shipments
damages_per_1000  = damage_rate * 1000
incident_share    = incidents in scope / all confirmed damage incidents in the period
```

`incident_share` is concentration, not a shipment rate. It is returned as a separate
field and is never substituted for `damage_rate`.

## Uncertainty and minimum volume

- Every rate includes a 95% Wilson score interval by default.
- The interval is computed on the shipment-level numerator and denominator.
- `minimum_volume` defaults to `30` and is configurable.
- Groups below the threshold are retained with `low_volume = true`.
- Hotspot results put sufficient-volume groups first; insufficient groups are never
  silently presented as directly comparable leaders.
- A zero denominator returns null rate, null interval and `low_volume = true`.

## Hotspot attribution

| Scope | Numerator attribution | Exposure denominator |
|---|---|---|
| `facility` | Facility on the incident's related event | Eligible shipments with any event at the facility |
| `carrier` | Carrier on the shipment | Eligible shipments assigned to the carrier |
| `zone` | Destination zone on the shipment | Eligible shipments assigned to the zone |
| `product_category` | Product category on the shipment | Eligible shipments in the category |
| `packaging_type` | Packaging type on the shipment | Eligible shipments using the packaging type |
| `stage` | Stage on the incident's related event, or the latest non-`other` operational stage before confirmation when the related event is a damage event | Eligible shipments with any event in the stage |

Missing attribution stays missing. An incident without a related event is not assigned to
a facility or stage. When the related event is `DAMAGE_REPORTED` or `DAMAGE_CONFIRMED`
(which belong to the `other` stage), attribution falls back to the latest non-`other`
operational event at or before confirmation, so damage is not automatically attributed to
`other`. Facility and stage denominators can overlap across rows because one shipment may
visit multiple facilities or stages; each row has its own documented exposure.

## Loss amounts

Estimated loss is reported separately by currency. Amounts are never summed across
currencies and no exchange-rate source is assumed. Incidents with a null amount or
currency are omitted from monetary totals but remain in incident/rate counts.

## Data quality

`analytics.data_quality_daily` reports declared synthetic anomalies by shipment cohort:

- events recorded more than 24 hours after they occurred
- events recorded before they occurred
- duplicate event records sharing shipment, event code and occurrence timestamp
- shipments with duplicate event code/timestamp groups

Duplicate metrics use the same strict `(shipment, event_code, occurred_at)` definition in
the SQL view, generator manifest and dataset validator. Repeated event codes at different
timestamps are not counted as duplicate records.
- events missing facility or carrier attribution
- shipments missing one or more package dimensions
- `DATA_GAP_DETECTED` events

Data-quality anomalies are observability signals. They do not imply damage and do not
remove otherwise eligible shipments from the denominator.

## SQL objects

Migration `sql/003_analytics_views.sql` creates:

- `analytics.eligible_shipments`
- `analytics.confirmed_damage_incidents`
- `analytics.daily_metrics`
- `analytics.loss_by_currency_daily`
- `analytics.scope_damage_daily`
- `analytics.data_quality_daily`

The Python layer in `src/loss_intelligence/analytics/` applies date filters, Wilson
intervals, minimum-volume flags and incident-share calculations. SQL keeps the reusable
cohorts and aggregations; Python keeps uncertainty and presentation-oriented decisions
testable.

## Known limitations

- Analytics describe synthetic records only and are not real operational performance.
- The eligible cohort excludes undelivered shipments, so all rates are conditional on
  completed delivery or return.
- Facility and stage exposure can double-count a shipment across scope rows by design.
- No causal or carrier-culpability claim is made.
- Minimum-volume filtering is a presentation guard, not statistical significance.
