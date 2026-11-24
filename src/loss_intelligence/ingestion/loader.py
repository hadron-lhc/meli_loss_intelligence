from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from sqlalchemy import Engine, text

from loss_intelligence.config import get_settings
from loss_intelligence.db.engine import create_engine_for, database_url_for
from loss_intelligence.db.maintenance import TRUNCATE_SQL, validate_reset_request
from loss_intelligence.ingestion.validation import ValidationResult, validate_dataset
from loss_intelligence.synthetic.common import DATASET_FILES
from loss_intelligence.synthetic.writer import read_manifest, resolve_dataset_dir


@dataclass(frozen=True)
class TableSpec:
    dataset_key: str
    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class LoadResult:
    run_id: UUID
    row_counts: dict[str, int]
    scenario_counts: dict[str, int]


class DatasetValidationError(RuntimeError):
    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        super().__init__(
            f"dataset validation failed with {len(result.errors)} error(s): {result.errors[:3]}"
        )


class DatasetLoadError(RuntimeError):
    pass


TABLE_SPECS = (
    TableSpec(
        "zones",
        "zones",
        ("zone_id", "zone_code", "zone_name", "region", "country_code"),
    ),
    TableSpec(
        "facilities",
        "facilities",
        (
            "facility_id",
            "facility_code",
            "facility_name",
            "facility_type",
            "zone_id",
            "active_from",
            "active_to",
            "is_active",
        ),
    ),
    TableSpec(
        "carriers",
        "carriers",
        (
            "carrier_id",
            "carrier_code",
            "carrier_name",
            "carrier_type",
            "active_from",
            "active_to",
        ),
    ),
    TableSpec(
        "product_categories",
        "product_categories",
        (
            "product_category_id",
            "category_code",
            "category_name",
            "fragility_class",
        ),
    ),
    TableSpec(
        "packaging_types",
        "packaging_types",
        ("packaging_type_id", "packaging_code", "packaging_name", "protection_level"),
    ),
    TableSpec(
        "shipments",
        "shipments",
        (
            "shipment_id",
            "shipment_code",
            "created_at",
            "dispatched_at",
            "delivered_at",
            "origin_facility_id",
            "destination_zone_id",
            "carrier_id",
            "product_category_id",
            "packaging_type_id",
            "weight_g",
            "length_mm",
            "width_mm",
            "height_mm",
            "declared_value",
            "currency_code",
            "shipment_status",
            "is_test_record",
            "created_record_at",
        ),
    ),
    TableSpec(
        "shipment_events",
        "shipment_events",
        (
            "event_id",
            "shipment_id",
            "event_code",
            "event_name",
            "stage",
            "event_status",
            "occurred_at",
            "recorded_at",
            "facility_id",
            "zone_id",
            "carrier_id",
            "sequence_number",
            "source_system",
            "event_metadata",
        ),
    ),
    TableSpec(
        "incidents",
        "incidents",
        (
            "incident_id",
            "shipment_id",
            "related_event_id",
            "incident_type",
            "damage_type",
            "severity",
            "reported_at",
            "confirmed_at",
            "incident_status",
            "estimated_loss_amount",
            "currency_code",
            "evidence_type",
            "created_at",
        ),
    ),
    TableSpec(
        "returns",
        "returns",
        (
            "return_id",
            "shipment_id",
            "initiated_at",
            "received_at",
            "declared_reason",
            "inspection_outcome",
            "return_status",
            "condition_on_return",
            "created_at",
        ),
    ),
    TableSpec(
        "synthetic_scenarios",
        "evaluation.synthetic_scenarios",
        (
            "scenario_id",
            "scenario_code",
            "scenario_type",
            "description",
            "split",
            "start_at",
            "end_at",
            "affected_entity_type",
            "affected_entity_id",
            "expected_detection",
            "expected_signals",
            "difficulty",
        ),
    ),
    TableSpec(
        "synthetic_truth_links",
        "evaluation.synthetic_truth_links",
        (
            "truth_link_id",
            "scenario_id",
            "entity_type",
            "entity_id",
            "truth_role",
        ),
    ),
)

UUID_COLUMNS = frozenset(
    {
        "zone_id",
        "facility_id",
        "carrier_id",
        "product_category_id",
        "packaging_type_id",
        "shipment_id",
        "event_id",
        "incident_id",
        "return_id",
        "related_event_id",
        "scenario_id",
        "truth_link_id",
        "entity_id",
        "generation_run_id",
    }
)
DATETIME_COLUMNS = frozenset(
    {
        "created_at",
        "dispatched_at",
        "delivered_at",
        "occurred_at",
        "recorded_at",
        "reported_at",
        "confirmed_at",
        "initiated_at",
        "received_at",
        "start_at",
        "end_at",
        "created_record_at",
        "started_at",
        "completed_at",
    }
)
DATE_COLUMNS = frozenset({"active_from", "active_to"})
DECIMAL_COLUMNS = frozenset({"declared_value", "estimated_loss_amount"})
JSONB_COLUMNS = frozenset({"event_metadata", "expected_signals"})


def _cast(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in UUID_COLUMNS:
        return UUID(str(value))
    if column in DATETIME_COLUMNS:
        return datetime.fromisoformat(str(value))
    if column in DATE_COLUMNS:
        return date.fromisoformat(str(value))
    if column in DECIMAL_COLUMNS:
        return Decimal(str(value))
    if column in JSONB_COLUMNS:
        return Jsonb(value)
    return value


def _iter_rows(dataset_dir: Path, dataset_key: str) -> Iterator[dict[str, Any]]:
    path = dataset_dir / DATASET_FILES[dataset_key]
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise DatasetLoadError(f"{path}:{line_number} is not a JSON object")
            yield value


def _copy_table(
    connection: Any,
    spec: TableSpec,
    dataset_dir: Path,
) -> None:
    columns = ", ".join(spec.columns)
    copy_sql = f"COPY {spec.table} ({columns}) FROM STDIN"
    raw_connection = connection.connection.driver_connection
    with raw_connection.cursor() as cursor:
        with cursor.copy(copy_sql) as copy:
            for row in _iter_rows(dataset_dir, spec.dataset_key):
                copy.write_row(tuple(_cast(column, row.get(column)) for column in spec.columns))


def _insert_generation_run(connection: Any, manifest: dict[str, Any]) -> None:
    generated_at = manifest.get("generated_at")
    started_at = (
        datetime.fromisoformat(generated_at) if isinstance(generated_at, str) else datetime.now(UTC)
    )
    connection.execute(
        text(
            """
            INSERT INTO meta.generation_runs
                (generation_run_id, generator_version, seed, config, config_hash,
                 status, started_at, completed_at, row_counts)
            VALUES
                (:generation_run_id, :generator_version, :seed, :config, :config_hash,
                 'completed', :started_at, NOW(), :row_counts)
            """
        ),
        {
            "generation_run_id": UUID(manifest["run_id"]),
            "generator_version": manifest["generator_version"],
            "seed": manifest["seed"],
            "config": Jsonb(manifest["config"]),
            "config_hash": manifest["config_hash"],
            "started_at": started_at,
            "row_counts": Jsonb(manifest["row_counts"]),
        },
    )


def _verify_counts(
    connection: Any,
    manifest: dict[str, Any],
) -> None:
    expected = manifest.get("row_counts", {})
    mismatches: list[str] = []
    for spec in TABLE_SPECS:
        actual = connection.execute(text(f"SELECT count(*) FROM {spec.table}")).scalar_one()
        if expected.get(spec.dataset_key) != actual:
            mismatches.append(
                f"{spec.table}: expected {expected.get(spec.dataset_key)}, found {actual}"
            )
    if mismatches:
        raise DatasetLoadError("row count verification failed: " + "; ".join(mismatches))


def load_dataset(
    engine: Engine,
    dataset_dir: Path,
    reset: bool = True,
    validate: bool = True,
) -> LoadResult:
    dataset_dir = dataset_dir.resolve()
    if validate:
        validation = validate_dataset(dataset_dir)
        if not validation.ok:
            raise DatasetValidationError(validation)

    manifest = read_manifest(dataset_dir)
    with engine.begin() as connection:
        if reset:
            connection.exec_driver_sql(TRUNCATE_SQL)
        _insert_generation_run(connection, manifest)
        for spec in TABLE_SPECS:
            _copy_table(connection, spec, dataset_dir)
        _verify_counts(connection, manifest)

    return LoadResult(
        run_id=UUID(manifest["run_id"]),
        row_counts=manifest["row_counts"],
        scenario_counts=manifest["scenario_counts"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and load a synthetic dataset.")
    parser.add_argument("--data-dir", default="data/generated", help="dataset root")
    parser.add_argument("--run-id", help="specific run id; defaults to latest")
    parser.add_argument(
        "--database",
        choices=("main", "test"),
        default="main",
        help="target database configuration",
    )
    parser.add_argument("--yes", action="store_true", help="confirm destructive reset")
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="append to existing data instead of truncating (not recommended)",
    )
    args = parser.parse_args()

    settings = get_settings()
    dataset_dir = resolve_dataset_dir(Path(args.data_dir), args.run_id)
    validation = validate_dataset(dataset_dir)
    print(validation.summary())
    for warning in validation.warnings:
        print(f"WARNING: {warning}")
    if not validation.ok:
        for error in validation.errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)

    reset = not args.no_reset
    if reset:
        database_url = database_url_for(settings, args.database)
        validate_reset_request(database_url, settings.app_env, args.yes)

    engine = create_engine_for(settings, args.database)
    try:
        result = load_dataset(engine, dataset_dir, reset=reset, validate=False)
        print(f"loaded run_id={result.run_id}")
        print(f"rows={sum(result.row_counts.values())}")
        print(
            "scenarios="
            + ",".join(f"{split}:{count}" for split, count in result.scenario_counts.items())
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
