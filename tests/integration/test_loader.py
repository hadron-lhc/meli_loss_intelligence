import json
import shutil

import pytest
from sqlalchemy import text

from loss_intelligence.ingestion.loader import DatasetValidationError, load_dataset

pytestmark = pytest.mark.integration


def _count(engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_loader_loads_dataset_and_truth(db, fixture_dataset_dir) -> None:
    manifest = json.loads((fixture_dataset_dir / "manifest.json").read_text())
    result = load_dataset(db, fixture_dataset_dir)

    assert result.row_counts == manifest["row_counts"]
    assert result.scenario_counts == manifest["scenario_counts"]

    expected_counts = manifest["row_counts"]
    for table, expected in (
        ("shipments", expected_counts["shipments"]),
        ("shipment_events", expected_counts["shipment_events"]),
        ("incidents", expected_counts["incidents"]),
        ("returns", expected_counts["returns"]),
        ("evaluation.synthetic_scenarios", expected_counts["synthetic_scenarios"]),
        ("evaluation.synthetic_truth_links", expected_counts["synthetic_truth_links"]),
        ("meta.generation_runs", 1),
    ):
        assert _count(db, table) == expected, table

    with db.connect() as connection:
        run = connection.execute(
            text("SELECT generator_version, seed, status, config_hash FROM meta.generation_runs")
        ).one()
        assert run.generator_version == manifest["generator_version"]
        assert run.seed == 7
        assert run.status == "completed"
        assert len(run.config_hash) == 64

        orphan_events = connection.execute(
            text(
                "SELECT count(*) FROM shipment_events e "
                "LEFT JOIN shipments s ON s.shipment_id = e.shipment_id "
                "WHERE s.shipment_id IS NULL"
            )
        ).scalar_one()
        assert orphan_events == 0

        bad_related = connection.execute(
            text(
                "SELECT count(*) FROM incidents i "
                "JOIN shipment_events e ON e.event_id = i.related_event_id "
                "WHERE e.shipment_id <> i.shipment_id"
            )
        ).scalar_one()
        assert bad_related == 0


def test_loader_is_idempotent_with_reset(db, fixture_dataset_dir) -> None:
    load_dataset(db, fixture_dataset_dir)
    load_dataset(db, fixture_dataset_dir)

    assert _count(db, "shipments") == 1500
    assert _count(db, "evaluation.synthetic_scenarios") == 12
    assert _count(db, "meta.generation_runs") == 1


def test_loader_refuses_invalid_dataset(db, fixture_dataset_dir, tmp_path) -> None:
    dataset_dir = tmp_path / "dataset"
    shutil.copytree(fixture_dataset_dir, dataset_dir)
    manifest_path = dataset_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["row_counts"]["shipments"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DatasetValidationError):
        load_dataset(db, dataset_dir)

    assert _count(db, "shipments") == 0
    assert _count(db, "evaluation.synthetic_scenarios") == 0
