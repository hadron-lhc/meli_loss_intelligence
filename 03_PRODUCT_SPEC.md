# 03 — Product Requirements & Dashboard Specification

## Product objective

Build an end-to-end operational analytics PoC that ingests shipment and event records, calculates damage metrics, detects unusual patterns, and provides an analyst with a prioritized, explainable investigation workflow.

## Product promise

A user should be able to:
- See the current synthetic operating picture.
- Identify facilities, carriers, stages or product profiles with unusual damage rates.
- Understand the denominator and comparison baseline behind each metric.
- Open a generated alert and inspect its contributing records.
- Review a shipment's chronological event timeline.
- Record an investigation decision, notes and follow-up action.
- See the outcome of evaluation scenarios.

## Main navigation / dashboard pages

### 1. Operations Overview
Required:
- Processed shipments.
- Confirmed damage incidents.
- Damage rate and damages per 1,000 shipments.
- Estimated synthetic loss amount (currency explicitly shown).
- Open alerts and investigation backlog.
- Time-series trend with selected date range.
- Clear “Synthetic data — independent PoC” notice.

### 2. Damage Hotspots
Required:
- Damage rate by facility, carrier, stage, zone and product category.
- Incident count and processed-shipment denominator shown together.
- Minimum-volume filtering.
- Time comparison and confidence/uncertainty cues.
- Do not rank groups with insufficient exposure as if comparable.

### 3. Alerts & Anomalies
Required:
- Alert ID, generated date, scope, entity, alert type, severity/priority, score, status.
- Reason codes / human-readable explanation.
- Baseline window and observed window.
- Observed numerator, denominator, rate and reference rate.
- Link to contributing shipments/incidents.
- Filters by status, priority, alert type and date.

### 4. Shipment Explorer
Required:
- Search/filter by synthetic shipment ID.
- Shipment characteristics.
- Chronological event timeline.
- Associated confirmed incident(s), if any.
- Associated alert(s), if any.
- Do not expose hidden synthetic ground-truth labels in the operational UI.

### 5. Investigation Workspace
Required:
- Create or open investigation from an alert.
- Status: `open`, `in_review`, `closed`, `dismissed`.
- Outcome: `confirmed_issue`, `no_issue_found`, `data_quality_issue`, `needs_more_evidence`, `other`.
- Notes and action recommendation.
- Reviewer identity should be clearly synthetic/demo, not a real employee.
- Audit timestamps and status changes.

### 6. Returns Intelligence (secondary)
Required only after core MVP:
- Return volume and reason distribution.
- Unusual repeat patterns / timing / discrepancy signals.
- Clear label: “review signal, not fraud determination”.
- No automatic customer accusation, blocking or enforcement.

### 7. Model & Evaluation
Required:
- Compare statistical baseline/rules with Isolation Forest.
- Show evaluation on held-out synthetic scenarios.
- Precision@K, recall, false-discovery proportion, false-positive rate on negative controls and detection delay where definable.
- Explain that synthetic performance does not establish real-world performance.

## UX principles

- Business-first, clean, restrained enterprise dashboard.
- Avoid excessive gradients, decorative AI motifs and meaningless gauges.
- Every chart must answer a question.
- Always show metric definition or tooltip and denominator.
- Use accessible labels and consistent units.
- Avoid maps unless geographic data is meaningful and sufficiently granular.
- Provide drill-down from aggregate metric to underlying records.
- Show data freshness / generation timestamp.
- Show synthetic-data warning persistently.

## Primary user journey

1. Analyst notices a facility's damage rate is outside its expected range.
2. Analyst checks the processed volume and comparison period.
3. Analyst drills into stage, carrier and product mix.
4. Analyst opens the alert's contributing shipments.
5. Analyst inspects event timelines and incident details.
6. Analyst records investigation outcome and next action.
7. Manager reviews aggregate alert outcomes and backlog.

## Definition of product success

The PoC succeeds if this journey can be completed reliably, with transparent calculations and traceable records, using synthetic data and repeatable tests.
