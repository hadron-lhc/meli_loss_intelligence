import json

from loss_intelligence.synthetic.common import DATASET_FILES
from loss_intelligence.synthetic.config import SyntheticDataConfig
from loss_intelligence.synthetic.generator import generate_dataset
from loss_intelligence.synthetic.writer import (
    read_manifest,
    resolve_dataset_dir,
    write_dataset,
)


def test_writer_creates_dataset_and_latest_pointer(tmp_path, fixture_dataset) -> None:
    result = write_dataset(fixture_dataset, tmp_path)

    assert result.dataset_dir.is_dir()
    for filename in DATASET_FILES.values():
        assert (result.dataset_dir / filename).is_file()
    assert (result.dataset_dir / "manifest.json").is_file()
    assert (tmp_path / "latest.json").is_file()

    manifest = read_manifest(result.dataset_dir)
    assert manifest["run_id"] == str(result.run_id)
    assert manifest["generator_version"] == "0.2.1"
    assert manifest["row_counts"] == result.row_counts
    assert resolve_dataset_dir(tmp_path) == result.dataset_dir
    assert resolve_dataset_dir(tmp_path, str(result.run_id)) == result.dataset_dir


def test_writer_output_is_byte_deterministic(tmp_path) -> None:
    config = SyntheticDataConfig.fixture()
    first = write_dataset(generate_dataset(config), tmp_path / "first")
    second = write_dataset(generate_dataset(config), tmp_path / "second")

    for filename in DATASET_FILES.values():
        assert (first.dataset_dir / filename).read_bytes() == (
            second.dataset_dir / filename
        ).read_bytes()


def test_manifest_is_json_serializable(tmp_path, fixture_dataset) -> None:
    result = write_dataset(fixture_dataset, tmp_path)
    manifest = json.loads((result.dataset_dir / "manifest.json").read_text())
    assert manifest["seed"] == 7
    assert manifest["scenario_counts"] == {
        "train": 4,
        "validation": 4,
        "test": 4,
    }
