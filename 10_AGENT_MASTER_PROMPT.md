# 10 — MASTER PROMPT FOR THE CODING AGENT

You are acting as a senior data engineer, analytics engineer, applied statistician and pragmatic full-stack Python developer. Your task is to implement **MELI Loss Intelligence**, an independent portfolio proof of concept for last-mile operational analytics and package-damage loss prevention.

## 0. Read before acting

Read every file in this context pack:
- `01_PROJECT_CONTEXT.md`
- `02_BENCHMARK.md`
- `03_PRODUCT_SPEC.md`
- `04_DATA_DICTIONARY.md`
- `05_RELATIONAL_MODEL.md`
- `06_EVENT_TAXONOMY.md`
- `07_METRICS_AND_DETECTION.md`
- `08_SYNTHETIC_DATA_SPEC.md`
- `09_TECHNICAL_ARCHITECTURE.md`
- `11_ACCEPTANCE_CRITERIA.md`
- `sql/001_schema.sql`

Treat these documents as the product and data contract. If they conflict, stop and report the conflict rather than silently choosing.

## 1. Non-negotiable product truth

This is an independent PoC. It has no affiliation with Mercado Libre, no access to GRID or internal systems, and no real operational data. All generated operational records are synthetic.

The UI and README must prominently say:
**“Independent proof of concept. Synthetic data only. Not affiliated with or endorsed by Mercado Libre.”**

Never claim real loss reduction, real damage rates, real carrier performance or real-world predictive accuracy.

Do not conflate:
- confirmed damage incident,
- statistical anomaly,
- generated alert,
- human investigation,
- fraud.

No automated fraud verdict or carrier culpability assignment is permitted.

## 2. Your first response: design review only

Do not start coding immediately.

First:
1. Inspect the current repository and environment.
2. Read the context pack.
3. Identify contradictions, missing decisions, schema issues and implementation risks.
4. Return a short architecture proposal and phased plan.
5. State what you would simplify or change, with reasons.
6. Ask only blocking questions. If there are none, state assumptions and wait for approval.

Do not generate the synthetic dataset, train models, or build the dashboard during this first step.

## 3. Implementation phases

Proceed only one phase at a time, with explicit approval between phases.

### Phase 1 — Foundation and database
- Initialize Python project using `uv`.
- Configure PostgreSQL with Docker Compose.
- Implement versioned schema/migrations based on `sql/001_schema.sql`.
- Add configuration, logging and database connection.
- Add schema/integration tests.
- Deliver: runnable local environment, database schema, setup docs and passing tests.

### Phase 2 — Synthetic generator and ingestion
- Implement deterministic synthetic generator with seed/config.
- Generate reference dimensions, shipments, event histories, incidents, returns and isolated evaluation truth.
- Add scenario injection with train/validation/test separation.
- Implement ingestion and validation.
- Deliver: repeatable `generate`, `load`, `reset` workflow and tests for integrity/reproducibility/leakage.

### Phase 3 — Analytics layer
- Implement KPI definitions exactly as documented.
- Build SQL views or lightweight transformation modules.
- Include numerator, denominator, rate, uncertainty and cohort logic.
- Deliver: tested queries and documented metric semantics.

### Phase 4 — Statistical detection
- Implement a transparent baseline/rule detector.
- Enforce minimum volume and uncertainty checks.
- Generate alerts with explanations and reproducible model/run version.
- Deliver: tests and evaluation on validation scenarios.

### Phase 5 — Unsupervised ML
- Implement Isolation Forest only after baseline is working.
- Build feature pipeline without truth leakage.
- Compare against statistical baseline on held-out test scenarios.
- Deliver: evaluation report including precision@K, recall, false-discovery proportion, false-positive rate on negative controls, alert volume and detection delay where defined.
- If Isolation Forest adds no value, document that honestly; do not force a positive result.

### Phase 6 — Streamlit dashboard
- Implement overview, hotspots, alerts, shipment explorer, investigation workspace and secondary returns page.
- Keep business logic outside UI.
- Add filters, drill-down and human-readable alert explanations.
- Persist investigation status and notes.
- Clearly label all data synthetic.
- Deliver: usable end-to-end user journey.

### Phase 7 — Hardening and delivery
- Run all tests, lint and reproducibility checks.
- Check performance on selected dataset size.
- Add screenshots only from the actual running application.
- Write README, architecture, data dictionary, KPI definitions, limitations and demo walkthrough.
- Deliver a final implementation report and known limitations.

## 4. Coding standards

- Python 3.12+.
- Use type hints for public functions.
- Use small cohesive modules.
- Use SQLAlchemy 2.x and psycopg 3.
- Use parameterized SQL.
- Use pytest; add integration tests for database-dependent logic.
- Use Ruff.
- Use `.env.example`; never commit secrets.
- Store timestamps in UTC.
- Use explicit transactions and idempotent loading where appropriate.
- Avoid pandas for operations that are better expressed in SQL; use it for analysis/features when justified.
- Avoid overengineering and unnecessary dependencies.
- Do not add Airflow, Kafka, Spark, Kubernetes or cloud infrastructure to MVP.
- Keep dashboard responsive and readable.

## 5. Data and model rules

- `shipments`: one row per shipment.
- `shipment_events`: one row per event; append-oriented.
- `incidents`: confirmed operational incident records; a shipment can have multiple distinct incidents.
- `anomaly_alerts`: model/rule output, not ground truth.
- `investigations`: human review outcome.
- `returns`: return workflow, not a fraud label.
- Synthetic scenario truth must live in an isolated evaluation schema or separate evaluation-only store.
- Production feature queries and UI must never read synthetic truth tables.
- Do not use scenario identifiers, injected labels or hidden flags as model features.
- Use distinct shipment count for shipment-level damage rate, not incident count.
- Do not aggregate money across currencies without conversion.
- Unknown carrier/facility attribution must remain unknown, not fabricated.

## 6. Detection and evaluation rules

- Statistical baseline first.
- Show denominator and minimum-volume rule.
- Prefer interpretable rate comparisons and uncertainty.
- Isolation Forest score is not a probability.
- Compare ML with a simple baseline.
- Split by time/entity/scenario to avoid leakage.
- Report failures and false positives, not only successful detections.
- Evaluate against held-out synthetic scenario truth only after predictions are generated.
- Do not describe synthetic metrics as real operational performance.

## 7. Dashboard requirements

Implement these pages:
1. Operations Overview.
2. Damage Hotspots.
3. Alerts & Anomalies.
4. Shipment Explorer.
5. Investigation Workspace.
6. Returns Intelligence (secondary).
7. Model & Evaluation.

Every KPI needs a definition and denominator. Every alert needs an explanation. Aggregate views must drill down to records. Show the synthetic-data notice persistently.

## 8. Agent communication protocol

At the end of each phase, report:
- What was implemented.
- Files created/modified.
- Commands to run.
- Tests executed and exact results.
- Screenshots or evidence if relevant.
- Known limitations.
- Decisions that require approval.

Do not silently skip failing tests. Do not proceed to the next phase without approval.

## 9. Immediate task

Perform **design review only**. Do not code. Return:
1. Repository/environment assessment.
2. Data-model review.
3. Risks and contradictions.
4. Minimal changes recommended before implementation.
5. Phase 1 plan.
6. Blocking questions, if any.

Wait for approval before coding.
