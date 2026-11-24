from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime
from typing import Any
from uuid import UUID

from loss_intelligence.config import get_settings
from loss_intelligence.db.engine import create_engine_for
from loss_intelligence.detection.config import DetectionConfig
from loss_intelligence.detection.detector import detect
from loss_intelligence.detection.evaluation import (
    detect_and_evaluate_validation,
    evaluate_validation,
)
from loss_intelligence.logging import configure_logging

COMMANDS = ("detect", "evaluate-validation", "run-validation")


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, default=_json_default))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run statistical detection and evaluate validation scenarios."
    )
    parser.add_argument("command", nargs="?", choices=COMMANDS, default="detect")
    parser.add_argument("--database", choices=("main", "test"), default="main")
    parser.add_argument("--start", type=datetime.fromisoformat)
    parser.add_argument("--end", type=datetime.fromisoformat)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--min-relative-lift", type=float, default=1.5)
    parser.add_argument("--min-zero-baseline-rate", type=float, default=0.25)
    parser.add_argument("--max-evidence", type=int, default=5)
    parser.add_argument("--detection-run-id", type=UUID)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine_for(settings, args.database)

    try:
        if args.command == "evaluate-validation":
            result = evaluate_validation(
                engine,
                detection_run_id=args.detection_run_id,
                k=args.k,
            )
        else:
            config = DetectionConfig(
                lookback_days=args.lookback_days,
                alpha=args.alpha,
                min_relative_lift=args.min_relative_lift,
                min_zero_baseline_rate=args.min_zero_baseline_rate,
                max_evidence=args.max_evidence,
            )
            if args.command == "run-validation":
                detection, evaluation = detect_and_evaluate_validation(
                    engine,
                    config,
                    k=args.k,
                )
                result = {
                    "detection": asdict(detection),
                    "evaluation": asdict(evaluation),
                }
            else:
                result = detect(
                    engine,
                    config,
                    observed_start=args.start,
                    observed_end=args.end,
                )
    except ValueError as exc:
        parser.error(str(exc))
    finally:
        engine.dispose()

    if hasattr(result, "__dataclass_fields__"):
        result = asdict(result)
    _print_json(result)


if __name__ == "__main__":
    main()
