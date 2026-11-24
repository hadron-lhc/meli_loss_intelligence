# 08 — Synthetic Data Generation Specification

## Objective

Generate a reproducible but operationally plausible synthetic dataset that supports analysis, detection and end-to-end dashboard workflows.

## Data volume (initial target, adjustable after performance test)

- 20,000–50,000 shipments.
- 5–10 fictional facilities.
- 4–8 fictional carriers.
- 6–10 zones.
- 8–12 product categories.
- 4–6 packaging profiles.
- 5–12 events per shipment on average, with realistic variation.
- Damage incidents should be relatively rare; choose prevalence as an explicit simulation parameter, not as an asserted industry benchmark.
- Returns should be a subset of shipments and include multiple legitimate reasons.

The agent must explain and document the selected prevalence and why it was chosen for simulation. Do not present it as a real-world rate.

## Reproducibility

- Use an explicit random seed.
- Store generator version and configuration.
- Same seed + same version + same config must produce the same logical dataset.
- Use deterministic synthetic IDs where practical, or persist a manifest.
- Support `generate`, `load`, and `reset` commands.
- Include a small fixture dataset for tests.

## Normal operating process

Model plausible stages:
1. Shipment created.
2. Pickup / origin processing.
3. Linehaul.
4. Destination processing.
5. Last-mile handoff.
6. Delivery attempt / delivered.
7. Optional reverse logistics.

Not every shipment follows every event. Include failed attempts, delays, retries, cancellations and missing telemetry at low, documented rates.

## Scenario injection

Create controlled scenarios with explicit ground truth isolated from operational features:
- `facility_rate_shift`: temporary increase in confirmed damage incidence at one facility.
- `carrier_zone_shift`: increase associated with a carrier-zone combination.
- `packaging_risk_shift`: higher incident rate for a packaging/product profile.
- `event_sequence_shift`: unusual event timing/sequence correlated with incident risk.
- `return_pattern_shift`: unusual return timing/repetition/discrepancy patterns.
- `data_quality_shift`: delayed/missing/duplicated events without necessarily implying damage.

For every scenario, define:
- start/end time,
- affected entity,
- affected population,
- expected observable signals,
- expected detection difficulty,
- held-out split,
- truth links.

## Avoid synthetic leakage

- Do not put `scenario_type`, `is_anomalous`, `is_damaged_by_injection`, or similar truth labels into `shipments`, `shipment_events`, or production feature tables.
- Keep scenario truth in a separate evaluation schema or separate file/database.
- Do not create a unique code/event that directly reveals the injected scenario.
- Do not make all affected rows share an obvious identifier or constant value.
- Use realistic overlap and background noise.
- Ensure test scenarios differ from the exact patterns used for development.

## Data quality scenarios

Include explicit but bounded cases:
- event recorded late,
- missing expected event,
- duplicate event,
- timestamp order conflict,
- unknown carrier/facility attribution,
- incomplete package dimensions.

These should be discoverable by data-quality checks, not automatically labelled as damage.

## Validation checks

- Foreign keys resolve.
- Event sequences are unique per shipment.
- Event timestamps are plausible or explicitly flagged.
- Confirmed incidents have confirmation timestamps.
- Shipment-level damage rate counts distinct shipments.
- Monetary fields have currency.
- Returns link to existing shipments.
- Evaluation truth links point to existing entities.
- No truth labels appear in production features or user-facing pages.
