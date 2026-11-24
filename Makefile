.PHONY: help up down logs migrate migrate-test test test-unit test-integration lint format check db-health reset-test generate generate-fixture validate-data load load-test reset-data analytics detect detect-validation evaluate-validation dashboard

DATA_DIR ?= data/generated
RUN_ID ?=
ANALYTICS_COMMAND ?= snapshot
ANALYTICS_DB ?= main
START_DATE ?=
END_DATE ?=
MIN_VOLUME ?= 30
MATURITY_DAYS ?= 14
SCOPE_TYPE ?= facility
LIMIT ?=
DETECTION_DB ?= main
DETECTION_START ?=
DETECTION_END ?=
DETECTION_LOOKBACK_DAYS ?= 30
DETECTION_ALPHA ?= 0.05
DETECTION_MIN_LIFT ?= 1.5
DETECTION_MIN_ZERO_RATE ?= 0.25
DETECTION_MAX_EVIDENCE ?= 5
DETECTION_K ?= 10
DETECTION_RUN_ID ?=
DASHBOARD_PORT ?= 8501

help:
	@printf '%s\n' \
		'up               Start PostgreSQL and wait for readiness' \
		'down             Stop PostgreSQL' \
		'logs             Follow PostgreSQL logs' \
		'migrate          Apply migrations to the main database' \
		'migrate-test     Apply migrations to the test database' \
		'test             Run unit and integration tests' \
		'test-unit        Run unit tests only' \
		'test-integration Run integration tests only' \
		'lint             Run Ruff lint checks' \
		'format           Format code with Ruff' \
		'check            Run lint and tests' \
		'db-health        Print database health information' \
		'reset-test       Truncate the dedicated test database' \
		'generate         Generate the default synthetic dataset' \
		'generate-fixture Generate the small deterministic fixture dataset' \
		'validate-data    Validate the latest generated dataset' \
		'load             Validate and load the latest dataset into the main database' \
		'load-test        Validate and load the latest dataset into the test database' \
		'reset-data       Truncate the main database (explicit confirmation)' \
		'analytics        Query analytics snapshot as JSON (ANALYTICS_COMMAND=...)' \
		'detect           Run statistical detection for the latest or explicit window' \
		'detect-validation Run detection over validation scenarios and evaluate it' \
		'evaluate-validation Evaluate a completed detection run against held-out scenarios' \
		'dashboard        Start the Streamlit dashboard'

up:
	docker compose up -d --wait

down:
	docker compose down

logs:
	docker compose logs -f postgres

migrate:
	uv run python -m loss_intelligence.db.migrate --database main

migrate-test:
	uv run python -m loss_intelligence.db.migrate --database test

test:
	uv run pytest

test-unit:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

check: lint test

db-health:
	uv run python -m loss_intelligence.db.health --database main

reset-test:
	uv run python -m loss_intelligence.db.maintenance --database test --yes

generate:
	uv run python -m loss_intelligence.synthetic.cli --output-dir $(DATA_DIR)

generate-fixture:
	uv run python -m loss_intelligence.synthetic.cli --profile fixture --output-dir $(DATA_DIR)

validate-data:
	uv run python -m loss_intelligence.ingestion.validation --data-dir $(DATA_DIR) $(if $(RUN_ID),--run-id $(RUN_ID),)

load:
	uv run python -m loss_intelligence.ingestion.loader --data-dir $(DATA_DIR) --database main --yes $(if $(RUN_ID),--run-id $(RUN_ID),)

load-test:
	uv run python -m loss_intelligence.ingestion.loader --data-dir $(DATA_DIR) --database test --yes $(if $(RUN_ID),--run-id $(RUN_ID),)

reset-data:
	uv run python -m loss_intelligence.db.maintenance --database main --yes

analytics:
	uv run python -m loss_intelligence.analytics.cli $(ANALYTICS_COMMAND) --database $(ANALYTICS_DB) --minimum-volume $(MIN_VOLUME) --maturity-days $(MATURITY_DAYS) $(if $(START_DATE),--start-date $(START_DATE),) $(if $(END_DATE),--end-date $(END_DATE),) $(if $(SCOPE_TYPE),--scope-type $(SCOPE_TYPE),) $(if $(LIMIT),--limit $(LIMIT),)

detect:
	uv run python -m loss_intelligence.detection.cli detect --database $(DETECTION_DB) --lookback-days $(DETECTION_LOOKBACK_DAYS) --alpha $(DETECTION_ALPHA) --min-relative-lift $(DETECTION_MIN_LIFT) --min-zero-baseline-rate $(DETECTION_MIN_ZERO_RATE) --max-evidence $(DETECTION_MAX_EVIDENCE) $(if $(DETECTION_START),--start $(DETECTION_START),) $(if $(DETECTION_END),--end $(DETECTION_END),)

detect-validation:
	uv run python -m loss_intelligence.detection.cli run-validation --database $(DETECTION_DB) --lookback-days $(DETECTION_LOOKBACK_DAYS) --alpha $(DETECTION_ALPHA) --min-relative-lift $(DETECTION_MIN_LIFT) --min-zero-baseline-rate $(DETECTION_MIN_ZERO_RATE) --max-evidence $(DETECTION_MAX_EVIDENCE) --k $(DETECTION_K)

evaluate-validation:
	uv run python -m loss_intelligence.detection.cli evaluate-validation --database $(DETECTION_DB) --k $(DETECTION_K) $(if $(DETECTION_RUN_ID),--detection-run-id $(DETECTION_RUN_ID),)

dashboard:
	uv run streamlit run src/loss_intelligence/app/streamlit_app.py --server.port $(DASHBOARD_PORT)
