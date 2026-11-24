# Last-Mile Loss Intelligence PoC

> **Independent proof of concept. Synthetic data only. Not affiliated with or endorsed by Mercado Libre.**

Operational analytics and loss-prevention proof of concept for last-mile logistics.
The repository contains the **Phase 1 foundation**, **Phase 2 synthetic data pipeline**,
**Phase 3 analytics layer**, **Phase 4 statistical detection** and **Phase 5 Streamlit
dashboard**: PostgreSQL schema, versioned migrations, deterministic data generation,
scenario injection, validation, dataset loading, KPI views, Wilson intervals, hotspot
analysis, alert persistence, held-out scenario evaluation and an investigation workflow.

No real operational data, no real Mercado Libre systems and no real loss claims are used.

## Current status

- Phase 1: foundation and database — implemented.
- Phase 2: deterministic synthetic data, validation and ingestion — implemented.
- Phase 3: analytics KPIs, uncertainty and hotspot queries — implemented.
- Phase 4: statistical baseline, alerts, evidence and validation evaluation — implemented.
- Phase 5: Streamlit dashboard, drill-down and investigation workflow — implemented.
- Isolation Forest — not implemented; documented as deferred pending a fair comparison.

## Stack

- Python 3.12+ (local environment uses 3.13)
- PostgreSQL 16 via Docker Compose
- SQLAlchemy 2.x + psycopg 3
- pytest and Ruff
- uv for environment and dependency management

## Quick start

```bash
cp .env.example .env
make up
make migrate
make generate
make validate-data
make load
make analytics
make detect-validation
make dashboard
make test
```

The dashboard is available at `http://localhost:8501` after `make dashboard`.

`make load` **truncates the main database** before loading the generated dataset.
PostgreSQL is exposed on host port **5433** by default. This avoids colliding with an
existing local PostgreSQL server on port 5432.

For a small, fast dataset instead of the default 30,000 shipments:

```bash
make generate-fixture
make validate-data
make load
```

## Commands

| Command | Purpose |
|---|---|
| `make up` | Start PostgreSQL and wait for its health check. |
| `make down` | Stop PostgreSQL. |
| `make logs` | Follow PostgreSQL logs. |
| `make migrate` | Apply versioned SQL migrations to the main database. |
| `make migrate-test` | Apply migrations to the dedicated test database. |
| `make test` | Run unit and integration tests. |
| `make test-unit` | Run unit tests only. |
| `make test-integration` | Run PostgreSQL integration tests only. |
| `make lint` | Run Ruff lint and format checks. |
| `make format` | Format code with Ruff. |
| `make check` | Run lint and all tests. |
| `make db-health` | Print database, timezone and server version. |
| `make reset-test` | Truncate only the dedicated test database. |
| `make generate` | Generate the default synthetic dataset under `data/generated/`. |
| `make generate-fixture` | Generate a 1,500-shipment fixture dataset. |
| `make validate-data` | Validate the latest generated dataset. |
| `make load` | Validate, truncate and load the latest dataset into the main database. |
| `make load-test` | Load the latest dataset into the dedicated test database. |
| `make reset-data` | Truncate the main database after explicit confirmation. |
| `make analytics` | Print the analytics snapshot as JSON. |
| `make detect` | Run statistical detection for the latest or explicit window. |
| `make detect-validation` | Detect over validation scenarios and evaluate the run. |
| `make evaluate-validation` | Evaluate a completed run against held-out scenarios. |
| `make dashboard` | Start the Streamlit dashboard on port 8501. |

Useful overrides: `DATA_DIR=...` changes the dataset root and `RUN_ID=...` selects a
specific generated run instead of `latest.json`. For analytics, `ANALYTICS_COMMAND`,
`ANALYTICS_DB`, `START_DATE`, `END_DATE`, `MIN_VOLUME`, `MATURITY_DAYS`, `SCOPE_TYPE`
and `LIMIT`
select the target database, partial report and filters. Detection uses `DETECTION_DB`,
`DETECTION_START`, `DETECTION_END`, `DETECTION_ALPHA`, `DETECTION_MIN_LIFT`,
`DETECTION_MIN_ZERO_RATE`, `DETECTION_MAX_EVIDENCE`, `DETECTION_K` and
`DETECTION_RUN_ID`. See [docs/ANALYTICS.md](docs/ANALYTICS.md) and
[docs/DETECTION.md](docs/DETECTION.md).

## Synthetic data

- Default profile: seed `20261119`, 30,000 shipments, 181 days, 8 zones, 8 facilities,
  6 carriers, 10 product categories and 5 packaging types.
- Deterministic UUIDs and seeded random choices make repeated runs byte-identical for
  the same configuration. `manifest.json` records the seed, config, config hash,
  generator version, row counts and scenario counts.
- Scenarios are split into `train`, `validation` and `test`. The default rotation covers
  facility rate shifts, carrier-zone shifts, packaging risk, event-sequence changes,
  return-pattern changes and data-quality gaps. Each split also has one negative-control
  scenario with no injected effect, and a 30-day clean baseline precedes scenario windows.
- Truth and scenario metadata are written only to `evaluation.*`. Operational tables
  never receive `scenario_id`, `truth_role` or expected-signal fields.
- Intentional anomalies include late recordings, timestamp conflicts, duplicate event
  codes, missing attribution and missing dimensions. They are counted in
  `data_quality_findings` rather than treated as load-blocking corruption.
- The validator checks file presence, manifest counts, determinism metadata, foreign
  keys, enums, event taxonomy consistency, truth links and scenario leakage.
- Loading validates first, truncates and copies in one transaction, verifies row counts,
  and records the run in `meta.generation_runs`.

The original reference run produced 371,173 events, 560 incidents, 1,987 returns,
9 scenarios and 423,767 total rows. The total includes 37 reference-dimension rows
(8 zones + 8 facilities + 6 carriers + 10 categories + 5 packaging types); core and truth
files account for 423,730 rows. After the date-range, clean-baseline and negative-control
corrections, new default runs should be documented from their own `manifest.json`.
Generation, validation and loading each take under a few minutes on a local development
machine.

The preserved post-audit reference run is
`data/generated/1d77d698-0637-5e3d-b22e-a09451e45369` (generator `0.2.1`): 30,000
shipments, 370,706 events, 596 incidents, 1,943 returns, 12 scenarios including 3 negative
controls, and 422,790 total rows. Validation: recall 3/3, false-positive rate 0/1, FDP
0/3, precision@10 1.0, 72 tested hypotheses, 12 q-significant and 9 suppressed.
Analytics: 29,034 eligible shipments, 493 damaged, 1.698% damage rate and 541 confirmed
incidents.

The audit corrections, superseded sections and corrected tables are documented in
[`docs/Addendum_Correcciones_Auditoria_v1.1.docx`](docs/Addendum_Correcciones_Auditoria_v1.1.docx).

Dataset layout:

```text
data/generated/<run_id>/
├── zones.jsonl
├── facilities.jsonl
├── carriers.jsonl
├── product_categories.jsonl
├── packaging_types.jsonl
├── shipments.jsonl
├── shipment_events.jsonl
├── incidents.jsonl
├── returns.jsonl
├── synthetic_scenarios.jsonl
├── synthetic_truth_links.jsonl
└── manifest.json
```

`data/generated/` is ignored by Git.

## Analytics

- Eligible cohort: delivered/returned, non-test shipments with a delivery timestamp.
- Cohort date: UTC date of shipment creation.
- Damage rate: distinct confirmed package-damage shipments / eligible shipments.
- Every rate includes a 95% Wilson interval and a minimum-volume flag (default 30).
- Overview and snapshot output split mature and immature cohorts using a 14-day default
  horizon so recent, still-arriving damage reports do not look like a real decline.
- Hotspots are available for facility, carrier, zone, product category, packaging type
  and stage, with numerator, denominator and incident concentration shown separately.
- Estimated loss is grouped by currency and never summed across currencies.
- Data-quality views count late events, timestamp conflicts, duplicate records, missing
  attribution and missing dimensions without treating them as damage.
- Analytics SQL and Python never read `evaluation.*` truth tables.

Full metric definitions, attribution rules and command examples are in
[docs/ANALYTICS.md](docs/ANALYTICS.md).

## Detection

- Compares an observed window with a baseline of equal length. Ad hoc detection uses the
  immediately preceding window; validation uses a clean historical baseline that ends at
  the earliest scenario start.
- Scans confirmed damage rates by facility, carrier, carrier-zone, zone, category,
  packaging and stage, plus sequence, return and data-quality signals.
- Uses a one-sided two-proportion z-test, Benjamini-Hochberg FDR control, minimum
  denominators/numerator, relative-lift thresholds and a guard for zero-baseline rates.
- Stores every run in `meta.detection_runs` and alerts with observed/baseline counts,
  rates, q-values, priority, explanation and evidence links.
- `make detect-validation` runs over the validation-scenario span and reports recall,
  false-discovery proportion, false-positive rate on negative controls and precision@K
  against held-out truth.
- Detection feature queries never read `evaluation.*`; only the evaluation module does.
- Isolation Forest is deferred pending a fair comparison with this baseline.

Defaults and matching rules are in [docs/DETECTION.md](docs/DETECTION.md).

## Dashboard

- Operations Overview, Damage Hotspots, Alerts & Anomalies, Shipment Explorer,
  Investigation Workspace, Returns Intelligence and Model & Evaluation pages.
- Persistent synthetic-data notice, metric definitions, denominators and Wilson
  uncertainty cues.
- Alert drill-down into evidence shipments, event timelines and incidents.
- Investigation creation and updates persist through the API layer; status and
  outcome changes are audited by database triggers.
- Read queries are cached for 60 seconds; writes clear the dashboard cache.
- The operational pages never read `evaluation.*` truth tables.

Run `make dashboard` and open `http://localhost:8501`. See
[docs/DASHBOARD.md](docs/DASHBOARD.md) for page details, architecture and
limitations.

## Database design

- `sql/001_schema.sql` is the immutable supplied baseline.
- `sql/002_schema_amendments.sql` adds Phase 1 amendments: generation/detection run
  metadata, event taxonomy enforcement, alert evidence links, investigation audit,
  scenario evaluation fields, integrity constraints and query indexes.
- `sql/003_analytics_views.sql` adds the Phase 3 analytics views in the `analytics`
  schema.
- `sql/004_detection_scope_types.sql` allows packaging and carrier-zone alert scopes.
- Applied migrations and checksums are tracked in `schema_migrations`.
- Evaluation truth lives in the isolated `evaluation` schema.
- Sessions are set to UTC.
- Test runs recreate the dedicated `loss_intelligence_test` database, apply migrations,
  and never touch the main database or unrelated local databases.

See [docs/SETUP.md](docs/SETUP.md) for setup details, reset safety and troubleshooting.

## Project layout

```text
src/loss_intelligence/
├── config.py          # validated environment settings
├── logging.py         # UTC logging configuration
├── db/
│   ├── engine.py      # SQLAlchemy engine and UTC session setup
│   ├── migrate.py     # versioned SQL migration runner
│   ├── health.py      # database health check
│   └── maintenance.py # guarded reset helpers
├── domain/
│   └── events.py      # canonical event taxonomy
├── analytics/
│   ├── metrics.py     # KPI queries, Wilson intervals and volume flags
│   ├── models.py      # typed analytics results
│   └── cli.py         # JSON analytics command
├── detection/
│   ├── config.py      # detection thresholds and config hash
│   ├── statistics.py  # two-proportion z-test and BH FDR
│   ├── queries.py     # signal numerators, denominators and evidence
│   ├── detector.py    # scoring, persistence and reproducibility
│   ├── evaluation.py  # held-out scenario matching and metrics
│   └── cli.py         # JSON detection command
├── synthetic/
│   ├── config.py      # generation profiles and seed/config hash
│   ├── generator.py   # deterministic shipment, event, incident and return generation
│   ├── reference.py   # synthetic reference dimensions
│   ├── scenarios.py   # split-aware scenario injection
│   ├── writer.py      # JSONL/manifest writer and dataset resolution
│   └── cli.py         # generation command
└── ingestion/
    ├── validation.py  # dataset integrity, truth and leakage checks
    └── loader.py      # transactional COPY loader and generation-run record
sql/
├── 001_schema.sql
├── 002_schema_amendments.sql
├── 003_analytics_views.sql
└── 004_detection_scope_types.sql
tests/
├── unit/
└── integration/
```

## Context pack

The original product, data and acceptance documents remain at the repository root:

- `01_PROJECT_CONTEXT.md`
- `02_BENCHMARK.md`
- `03_PRODUCT_SPEC.md`
- `04_DATA_DICTIONARY.md`
- `05_RELATIONAL_MODEL.md`
- `06_EVENT_TAXONOMY.md`
- `07_METRICS_AND_DETECTION.md`
- `08_SYNTHETIC_DATA_SPEC.md`
- `09_TECHNICAL_ARCHITECTURE.md`
- `10_AGENT_MASTER_PROMPT.md`
- `11_ACCEPTANCE_CRITERIA.md`

## Limitations

- All operational records are synthetic; no real damage, carrier or customer claims exist.
- Alerts are review signals, not incident confirmations or fraud findings.
- Isolation Forest has not been implemented; no incremental-value claim is made.
- The project does not assign carrier culpability or automate enforcement.
- Scenario truth describes how the test data was constructed; it is not evidence of
  real-world detection performance.
- Synthetic evaluation metrics do not establish real-world performance.
