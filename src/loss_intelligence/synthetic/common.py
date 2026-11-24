import random
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

UUID_NAMESPACE = uuid.UUID("7f2f6d5c-6d25-4e1b-b4f7-5f1a7c3e9d10")

DATASET_FILES = {
    "zones": "zones.jsonl",
    "facilities": "facilities.jsonl",
    "carriers": "carriers.jsonl",
    "product_categories": "product_categories.jsonl",
    "packaging_types": "packaging_types.jsonl",
    "shipments": "shipments.jsonl",
    "shipment_events": "shipment_events.jsonl",
    "incidents": "incidents.jsonl",
    "returns": "returns.jsonl",
    "synthetic_scenarios": "synthetic_scenarios.jsonl",
    "synthetic_truth_links": "synthetic_truth_links.jsonl",
}


def deterministic_uuid(seed: int, kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(UUID_NAMESPACE, f"meli-loss-intelligence:{seed}:{kind}:{key}")


def utc_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def random_datetime(rng: random.Random, start: datetime, end: datetime) -> datetime:
    total_seconds = max(0, int((end - start).total_seconds()))
    return start + timedelta(seconds=rng.randint(0, total_seconds))


def random_hours(rng: random.Random, low: int, high: int) -> timedelta:
    return timedelta(hours=rng.randint(low, high), minutes=rng.randint(0, 59))


def weighted_choice[T](
    rng: random.Random,
    items: Sequence[T],
    weights: Sequence[float],
) -> T:
    return rng.choices(items, weights=weights, k=1)[0]
