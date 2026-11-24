# Setup and Operations

> Independent proof of concept. Synthetic data only. Not affiliated with or endorsed by Mercado Libre.

## Prerequisites

- Python 3.12+
- uv
- Docker with Docker Compose v2
- Free host port 5433 (default)

## First run

```bash
cp .env.example .env
make up
make migrate
make generate-fixture
make validate-data
make load
make analytics
make test
```

`make up` starts PostgreSQL 16 and waits for the container health check.
`make migrate` applies `sql/001_schema.sql`, `sql/002_schema_amendments.sql`,
`sql/003_analytics_views.sql` and `sql/004_detection_scope_types.sql`.
`make generate-fixture` creates a small deterministic dataset under `data/generated/`.
`make validate-data` checks the latest dataset before ingestion.
`make load` validates, truncates and loads it into the main database.
`make analytics` prints the analytics snapshot as JSON.
`make test` recreates the dedicated test database, applies migrations and runs all tests.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_USER` | `loss_app` | Compose PostgreSQL user. |
| `POSTGRES_PASSWORD` | local development value | Compose PostgreSQL password. Never commit a real secret. |
| `POSTGRES_DB` | `loss_intelligence` | Main database name. |
| `POSTGRES_PORT` | `5433` | Host port mapped to container PostgreSQL. |
| `DATABASE_URL` | local URL on port 5433 | Main SQLAlchemy URL. |
| `TEST_DATABASE_URL` | local URL on port 5433 | Dedicated test database URL. |
| `TEST_ADMIN_DATABASE_URL` | local `postgres` database URL | Used to create/drop the test database. |
| `APP_ENV` | `local` | `local`, `test` or `ci`. |
| `LOG_LEVEL` | `INFO` | Python logging level. |
| `DB_ECHO` | `false` | SQLAlchemy SQL echo. |

All database URLs must use the `postgresql+psycopg` driver.

## Port 5433

The local machine used for development already has a PostgreSQL server on port 5432.
This project uses Docker Compose on port 5433 to avoid touching that server or its
databases. If 5433 is occupied, change `POSTGRES_PORT` in `.env` and update the URLs.

## Migrations

- Migration files are applied in filename order.
- Each applied migration records its version, description and SHA-256 checksum in
  `schema_migrations`.
- Re-running migrations is safe when files are unchanged.
- Changing an already-applied migration file causes a checksum error; create a new
  migration instead.
- DDL runs inside a transaction. A failed migration rolls back and is not recorded.

## Synthetic data workflow

```bash
make generate            # default: 30,000 shipments
make generate-fixture    # small fixture: 1,500 shipments
make validate-data       # validates the latest run
make load                # validates + truncates main + loads
make load-test           # validates + truncates test + loads
make reset-data          # explicit main-database truncate
```

`make load` and `make load-test` are destructive: they truncate the target database
inside the load transaction. The CLI requires `--yes`; the Make targets pass it
explicitly. Use `DATA_DIR=...` to point at another dataset root and `RUN_ID=...` to
select a specific run instead of `latest.json`.

Generation profiles:

| Profile | Shipments | Dates | Purpose |
|---|---:|---|---|
| `default` | 30,000 | 2026-01-01 to 2026-06-30 | realistic PoC volume |
| `fixture` | 1,500 | 2026-01-01 to 2026-03-31 | fast tests and demos |
| `fixture-no-scenarios` | 1,500 | 2026-01-01 to 2026-03-31 | baseline tests without truth |

The generator uses a seed, deterministic UUIDs and stable row ordering. Re-running the
same configuration produces byte-identical JSONL data files. `manifest.json` stores
the seed, full config, config hash, generator version, row counts, scenario counts,
observed rates and intentional data-quality findings.

The default scenario rotation is:

- `train`: facility rate shift, carrier-zone shift, packaging risk shift.
- `validation`: event-sequence shift, return-pattern shift, data-quality shift.
- `test`: facility rate shift, carrier-zone shift, packaging risk shift.
- Each split also includes one negative-control scenario with `expected_detection = FALSE`
  and no injected effect.

The generator reserves a 30-day clean baseline at the start of the date range before
scenario windows begin. The configured `end_date` is inclusive; the default range covers
181 calendar days.

Scenario and truth rows are written to `evaluation.*` only. Operational JSONL files
must not contain scenario or truth fields; the validator rejects such leakage.

Intentional anomalies (late recordings, timestamp conflicts, duplicate event codes,
missing attribution, missing dimensions) are allowed and counted. Validation blocks
missing files, count mismatches, broken references, invalid enums, taxonomy
inconsistencies, invalid truth links, duplicate links and leakage.

Loading uses `COPY` in a single transaction. It validates first, truncates the
allowlisted target database, loads dimensions and operational data, loads evaluation
truth, records `meta.generation_runs`, and verifies row counts before commit. A failed
load rolls back completely.

The original reference run produced 371,173 events, 560 incidents, 1,987 returns,
9 scenarios and 423,767 total rows. That total includes 37 reference-dimension rows
(8 zones + 8 facilities + 6 carriers + 10 categories + 5 packaging types); the core and
truth files account for 423,730 rows. After the date-range, clean-baseline and
negative-control corrections, new default runs have different counts and should be
recorded from their own `manifest.json`. Generation and validation take under a minute
each locally; loading takes roughly two minutes because constraints and indexes remain
active.

### Corrected reference run

After the audit corrections, the preserved reference dataset is
`data/generated/1d77d698-0637-5e3d-b22e-a09451e45369` (generator `0.2.1`, config hash
`0f837103a953b907169156b58c29a16f0137d96f1f3e90b485c2a589f8a79e0d`). It covers
2026-01-01 through 2026-06-30, contains 30,000 shipments, 370,706 events, 596 incidents,
1,943 returns, 12 scenarios (3 negative controls), and 422,790 total rows. Of those rows,
37 are reference dimensions; core and truth files account for 422,753.

On the test database, `overview --maturity-days 14` reports 29,034 eligible shipments,
493 damaged shipments, a 1.698% damage rate (CI95% 1.556%-1.853%), and 541 confirmed
damage incidents. Mature cohort: 430/26,822 (1.603%); immature cohort: 63/2,212 (2.848%).
Attribution now resolves every confirmed incident: 509 `delivery`, 32
`reverse_logistics`, 0 null.

`run-validation` reports 3 alerts, recall 3/3, false-positive rate 0/1, FDP 0/3,
precision@10 1.0, 72 tested hypotheses, 12 q-significant hypotheses and 9 suppressed by
the lift/zero-baseline guard. The detection run is
`09ad52b4-cd65-401f-ad2b-addaffcdf1ef`; the original detection run remains preserved.

The corrected tables and superseded report sections are consolidated in
[`Addendum_Correcciones_Auditoria_v1.1.docx`](Addendum_Correcciones_Auditoria_v1.1.docx).

All report timestamps are UTC. The original report date (`2026-11-20`) and the detection
run timestamp (`2026-11-21 00:55:57 UTC`) fall on different UTC dates; do not compare
them as local-time values.

## Analytics workflow

```bash
make analytics
make analytics ANALYTICS_COMMAND=overview
make analytics ANALYTICS_COMMAND=daily START_DATE=2026-02-01 END_DATE=2026-02-28
make analytics ANALYTICS_COMMAND=hotspots SCOPE_TYPE=carrier MIN_VOLUME=50 LIMIT=10
make analytics ANALYTICS_COMMAND=loss
make analytics ANALYTICS_COMMAND=data-quality
```

The analytics command reads the main database and prints JSON. Rate calculations use
distinct confirmed-damage shipments over eligible delivered/returned non-test shipments.
Cohort dates come from shipment creation in UTC. Wilson intervals and minimum-volume
flags are applied in Python. Full definitions and attribution rules are in
[docs/ANALYTICS.md](ANALYTICS.md).

## Detection workflow

```bash
make detect
make detect-validation
make evaluate-validation
make evaluate-validation DETECTION_RUN_ID=<uuid> DETECTION_K=5
make detect DETECTION_DB=test
make detect DETECTION_START=2026-04-01T00:00:00+00:00 \
  DETECTION_END=2026-05-16T00:00:00+00:00
```

`make detect` scores the latest 30-day window against the preceding 30 days. Run
configuration, config hash and status are stored in `meta.detection_runs`; alerts and
evidence are stored in operational tables. `make detect-validation` runs over the
validation-scenario span and immediately reports recall, false-discovery proportion,
false-positive rate on negative controls and
precision@K. Feature queries never read `evaluation.*`; only the evaluation module does.
Full rules and defaults are in [docs/DETECTION.md](DETECTION.md).

## Test database lifecycle

Integration tests recreate `loss_intelligence_test` at the start of the test session.
The recreation helper refuses any database name that does not end with `_test`.
Migrations are then applied from scratch. This verifies the from-zero schema path on
every test run.

The main database is not recreated by tests.

## Reset safety

The reset helper only accepts these exact database names:

- `loss_intelligence`
- `loss_intelligence_test`

It also requires explicit `--yes` confirmation and refuses production environments.
Use `make reset-test` for the safe test workflow. Resetting the main database removes
all operational and evaluation rows but preserves the static event taxonomy.
`make load` performs the same reset before loading, so treat it as destructive.

## From-zero verification

```bash
docker compose down -v
make up
make migrate
make check
make generate-fixture
make validate-data
make load-test
make analytics ANALYTICS_DB=test
make detect DETECTION_DB=test
```

`docker compose down -v` removes only this Compose project's PostgreSQL volume.
It does not touch the separate local PostgreSQL server on port 5432. `make load-test`
verifies the ingestion path against the dedicated test database without touching the
main database.

## Troubleshooting

- **Connection refused:** run `make up` and check `docker compose ps`.
- **Port already in use:** change `POSTGRES_PORT` and the URLs in `.env`.
- **Test database permission error:** the Compose PostgreSQL user must be able to
  create databases. The default `loss_app` user created by the official image can.
- **Checksum mismatch:** restore the migration file or add a new migration; do not
  edit an applied migration.
- **Reset denied:** verify the database name and pass `--yes`.
