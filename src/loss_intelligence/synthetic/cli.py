from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

from loss_intelligence.synthetic.config import SyntheticDataConfig
from loss_intelligence.synthetic.generator import generate_dataset
from loss_intelligence.synthetic.writer import write_dataset

PROFILES = {
    "default": SyntheticDataConfig,
    "fixture": SyntheticDataConfig.fixture,
    "fixture-no-scenarios": SyntheticDataConfig.fixture_without_scenarios,
}


def build_config(args: argparse.Namespace) -> SyntheticDataConfig:
    config = PROFILES[args.profile]()
    updates: dict[str, Any] = {}
    if args.seed is not None:
        updates["seed"] = args.seed
    if args.shipments is not None:
        updates["shipment_count"] = args.shipments
    if args.start_date is not None:
        updates["start_date"] = args.start_date
    if args.end_date is not None:
        updates["end_date"] = args.end_date
    if args.scenarios_per_split is not None:
        updates["scenarios_per_split"] = args.scenarios_per_split
    if args.no_scenarios:
        updates["scenarios_per_split"] = 0
    return config.model_copy(update=updates) if updates else config


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic logistics data.")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="default")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--shipments", type=int)
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--scenarios-per-split", type=int)
    parser.add_argument("--no-scenarios", action="store_true")
    parser.add_argument("--output-dir", default="data/generated")
    args = parser.parse_args()

    config = build_config(args)
    dataset = generate_dataset(config)
    result = write_dataset(dataset, Path(args.output_dir))

    print(f"run_id={result.run_id}")
    print(f"dataset_dir={result.dataset_dir}")
    print(f"config_hash={config.config_hash}")
    print(f"seed={config.seed}")
    print(f"shipments={result.row_counts['shipments']}")
    print(f"events={result.row_counts['shipment_events']}")
    print(f"incidents={result.row_counts['incidents']}")
    print(f"returns={result.row_counts['returns']}")
    print(
        "scenarios="
        + ",".join(f"{split}:{count}" for split, count in result.scenario_counts.items())
    )
    print(
        "data_quality="
        + ",".join(f"{key}:{value}" for key, value in result.data_quality_findings.items())
    )


if __name__ == "__main__":
    main()
