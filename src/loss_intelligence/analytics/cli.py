from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

from loss_intelligence.analytics.metrics import (
    SCOPE_TYPES,
    get_daily_metrics,
    get_data_quality,
    get_loss_by_currency,
    get_overview,
    get_scope_hotspots,
    get_snapshot,
)
from loss_intelligence.config import get_settings
from loss_intelligence.db.engine import create_engine_for
from loss_intelligence.logging import configure_logging

COMMANDS = ("snapshot", "overview", "daily", "hotspots", "loss", "data-quality")


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, default=_json_default))


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the synthetic-data analytics layer.")
    parser.add_argument("command", nargs="?", choices=COMMANDS, default="snapshot")
    parser.add_argument("--database", choices=("main", "test"), default="main")
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--minimum-volume", type=int, default=30)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--maturity-days", type=int, default=14)
    parser.add_argument("--scope-type", choices=SCOPE_TYPES, default="facility")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine_for(settings, args.database)

    common = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "minimum_volume": args.minimum_volume,
        "confidence": args.confidence,
    }

    try:
        if args.command == "snapshot":
            value = get_snapshot(
                engine,
                hotspot_limit=args.limit,
                maturity_days=args.maturity_days,
                **common,
            )
        elif args.command == "overview":
            value = get_overview(engine, maturity_days=args.maturity_days, **common)
        elif args.command == "daily":
            value = get_daily_metrics(engine, **common)
        elif args.command == "hotspots":
            value = get_scope_hotspots(
                engine,
                args.scope_type,
                limit=args.limit,
                **common,
            )
        elif args.command == "loss":
            value = get_loss_by_currency(
                engine,
                start_date=args.start_date,
                end_date=args.end_date,
            )
        else:
            value = get_data_quality(
                engine,
                start_date=args.start_date,
                end_date=args.end_date,
            )
    except ValueError as exc:
        parser.error(str(exc))
    finally:
        engine.dispose()

    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    elif isinstance(value, tuple) and value and hasattr(value[0], "__dataclass_fields__"):
        value = [asdict(item) for item in value]
    _print_json(value)


if __name__ == "__main__":
    main()
