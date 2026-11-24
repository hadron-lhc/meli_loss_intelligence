import json
import shutil
from uuid import uuid4

from loss_intelligence.ingestion.validation import validate_dataset


def _copy_dataset(source, tmp_path):
    target = tmp_path / "dataset"
    shutil.copytree(source, target)
    return target


def _rewrite_first_row(path, mutate) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    mutate(row)
    lines[0] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_valid_fixture_dataset_passes(fixture_dataset_dir) -> None:
    result = validate_dataset(fixture_dataset_dir)
    assert result.ok, result.errors
    assert result.warnings == []


def test_missing_file_is_reported(fixture_dataset_dir, tmp_path) -> None:
    dataset_dir = _copy_dataset(fixture_dataset_dir, tmp_path)
    (dataset_dir / "returns.jsonl").unlink()

    result = validate_dataset(dataset_dir)
    assert not result.ok
    assert any("missing dataset file: returns.jsonl" in error for error in result.errors)


def test_manifest_row_count_mismatch_is_reported(fixture_dataset_dir, tmp_path) -> None:
    dataset_dir = _copy_dataset(fixture_dataset_dir, tmp_path)
    manifest_path = dataset_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["row_counts"]["shipments"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_dataset(dataset_dir)
    assert not result.ok
    assert any("manifest row_counts[shipments]" in error for error in result.errors)


def test_scenario_leakage_in_operational_file_is_reported(fixture_dataset_dir, tmp_path) -> None:
    dataset_dir = _copy_dataset(fixture_dataset_dir, tmp_path)
    _rewrite_first_row(
        dataset_dir / "shipments.jsonl",
        lambda row: row.update({"scenario_id": str(uuid4())}),
    )

    result = validate_dataset(dataset_dir)
    assert not result.ok
    assert any("evaluation fields" in error for error in result.errors)


def test_truth_link_to_unknown_entity_is_reported(fixture_dataset_dir, tmp_path) -> None:
    dataset_dir = _copy_dataset(fixture_dataset_dir, tmp_path)
    _rewrite_first_row(
        dataset_dir / "synthetic_truth_links.jsonl",
        lambda row: row.update({"entity_id": str(uuid4())}),
    )

    result = validate_dataset(dataset_dir)
    assert not result.ok
    assert any("unknown shipment entity_id" in error for error in result.errors)
