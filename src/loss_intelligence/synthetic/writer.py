from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from loss_intelligence.synthetic.common import DATASET_FILES
from loss_intelligence.synthetic.models import GeneratedDataset, GenerationResult


def _json_default(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_dataset(
    dataset: GeneratedDataset,
    output_root: Path = Path("data/generated"),
) -> GenerationResult:
    run_id = UUID(dataset.manifest["run_id"])
    dataset_dir = output_root / str(run_id)
    dataset_dir.mkdir(parents=True, exist_ok=True)

    for name, filename in DATASET_FILES.items():
        rows = dataset.rows.get(name, [])
        path = dataset_dir / filename
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        row,
                        default=_json_default,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")

    manifest_path = dataset_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            dataset.manifest,
            default=_json_default,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    latest = {
        "run_id": str(run_id),
        "dataset_dir": str(dataset_dir.resolve()),
        "config_hash": dataset.manifest["config_hash"],
        "seed": dataset.manifest["seed"],
        "generator_version": dataset.manifest["generator_version"],
        "generated_at": dataset.manifest["generated_at"],
        "row_counts": dataset.manifest["row_counts"],
        "scenario_counts": dataset.manifest["scenario_counts"],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "latest.json").write_text(
        json.dumps(latest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    return GenerationResult(
        run_id=run_id,
        dataset_dir=dataset_dir,
        row_counts=dataset.manifest["row_counts"],
        scenario_counts=dataset.manifest["scenario_counts"],
        data_quality_findings=dataset.manifest["data_quality_findings"],
    )


def read_manifest(dataset_dir: Path) -> dict[str, Any]:
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Dataset manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def resolve_dataset_dir(output_root: Path, run_id: str | None = None) -> Path:
    if run_id:
        try:
            dataset_dir = output_root / str(UUID(run_id))
        except ValueError as exc:
            raise ValueError(f"invalid run id: {run_id!r}") from exc
    else:
        latest_path = output_root / "latest.json"
        if not latest_path.is_file():
            raise FileNotFoundError(
                f"No latest dataset pointer found at {latest_path}. Run generate first."
            )
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        dataset_dir = output_root / str(UUID(latest["run_id"]))
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")
    if not (dataset_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"Dataset manifest not found in {dataset_dir}")
    return dataset_dir
