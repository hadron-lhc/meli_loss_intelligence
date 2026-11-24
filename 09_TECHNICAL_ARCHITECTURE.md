# 09 — Technical Architecture & Engineering Conventions

## Recommended stack

- Python 3.12+
- PostgreSQL 16+
- SQLAlchemy 2.x + psycopg 3
- pandas / NumPy / SciPy
- scikit-learn
- Streamlit + Plotly
- pytest
- uv for dependency and environment management
- Docker Compose for local PostgreSQL
- Ruff for lint/format
- GitHub Actions for CI

Optional:
- dbt Core only if the agent can keep it lightweight and demonstrate meaningful transformations/tests. It is not a hard MVP dependency.
- Do not add Airflow, Kafka, Spark, Kubernetes or cloud infrastructure without a concrete requirement.

## Suggested architecture

1. Synthetic generator: deterministic generation and scenario injection.
2. Ingestion: validated loading into PostgreSQL.
3. Storage: normalized operational tables plus isolated evaluation truth.
4. Analytics: SQL views or Python/SQL transformation layer.
5. Detection: statistical baseline, then Isolation Forest.
6. Application: Streamlit dashboard with drill-down and investigation workflow.
7. Evaluation: isolated evaluation runner reading truth tables only after predictions are produced.

## Suggested repository layout

```text
meli-loss-intelligence/
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Makefile
├── docs/
│   ├── 01_PROJECT_CONTEXT.md
│   ├── 02_BENCHMARK.md
│   ├── 03_PRODUCT_SPEC.md
│   ├── 04_DATA_DICTIONARY.md
│   ├── 05_RELATIONAL_MODEL.md
│   ├── 06_EVENT_TAXONOMY.md
│   ├── 07_METRICS_AND_DETECTION.md
│   ├── 08_SYNTHETIC_DATA_SPEC.md
│   └── 11_ACCEPTANCE_CRITERIA.md
├── sql/
│   ├── 001_schema.sql
│   └── analytics/
├── src/
│   └── loss_intelligence/
│       ├── config.py
│       ├── db/
│       ├── synthetic/
│       ├── ingestion/
│       ├── analytics/
│       ├── detection/
│       ├── evaluation/
│       └── app/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── evaluation/
└── scripts/
```

## Engineering rules

- Keep business logic outside Streamlit page files.
- Use typed functions where practical.
- Validate configuration at startup.
- Never hardcode secrets.
- Use environment variables and `.env.example`.
- Use migrations or versioned SQL scripts; do not silently mutate schemas.
- Use parameterized SQL.
- Add indexes based on query patterns, especially shipment event lookups and time-window filtering.
- Use UTC in storage.
- Avoid giant monolithic modules.
- Include structured logging and actionable error messages.
- Tests must cover metric denominators, duplicate incidents, null attribution, event chronology, leakage prevention and reproducibility.
- CI must run lint, unit tests and relevant integration tests.
- Keep Streamlit reruns efficient; cache read-only aggregates carefully and invalidate after writes.
- Do not make the dashboard dependent on model training at startup.
