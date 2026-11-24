"""Display formatting helpers shared by dashboard pages."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

EMPTY = "—"

SCOPE_LABELS = {
    "facility": "Facility",
    "carrier": "Carrier",
    "carrier_zone": "Carrier / zone",
    "zone": "Zone",
    "product_category": "Product category",
    "packaging_type": "Packaging type",
    "stage": "Stage",
    "shipment": "Shipment",
    "return": "Return",
    "global": "Global",
}

ALERT_TYPE_LABELS = {
    "damage_rate_spike": "Damage rate spike",
    "stage_concentration": "Stage concentration",
    "carrier_deviation": "Carrier deviation",
    "product_profile_deviation": "Product profile deviation",
    "event_sequence_outlier": "Event sequence outlier",
    "return_pattern_outlier": "Return pattern outlier",
    "data_quality": "Data quality",
}

STATUS_LABELS = {
    "new": "New",
    "acknowledged": "Acknowledged",
    "investigating": "Investigating",
    "resolved": "Resolved",
    "dismissed": "Dismissed",
    "open": "Open",
    "in_review": "In review",
    "closed": "Closed",
}

PRIORITY_LABELS = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}

OUTCOME_LABELS = {
    "confirmed_issue": "Confirmed issue",
    "no_issue_found": "No issue found",
    "data_quality_issue": "Data quality issue",
    "needs_more_evidence": "Needs more evidence",
    "other": "Other",
}

REASON_LABELS = {
    "damaged": "Damaged",
    "wrong_item": "Wrong item",
    "not_as_described": "Not as described",
    "changed_mind": "Changed mind",
    "size_fit": "Size / fit",
    "missing_parts": "Missing parts",
    "other": "Other",
    "unknown": "Unknown",
}

INSPECTION_LABELS = {
    "not_inspected": "Not inspected",
    "matches_declaration": "Matches declaration",
    "does_not_match_declaration": "Does not match declaration",
    "inconclusive": "Inconclusive",
    "unknown": "Unknown",
}

CONDITION_LABELS = {
    "new": "New",
    "used": "Used",
    "damaged": "Damaged",
    "incomplete": "Incomplete",
    "unknown": "Unknown",
}


def humanize(value: Any) -> str:
    if value is None or value == "":
        return EMPTY
    return str(value).replace("_", " ").strip().capitalize()


def label(mapping: dict[str, str], value: Any) -> str:
    if value is None or value == "":
        return EMPTY
    return mapping.get(str(value), humanize(value))


def format_int(value: Any) -> str:
    if value is None:
        return EMPTY
    return f"{int(value):,}"


def format_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return EMPTY
    return f"{value:.{digits}%}"


def format_per_1000(value: float | None, digits: int = 2) -> str:
    if value is None:
        return EMPTY
    return f"{value:,.{digits}f}"


def format_rate(numerator: Any, denominator: Any, digits: int = 2) -> str:
    if numerator is None or denominator in (None, 0):
        return EMPTY
    return format_pct(float(numerator) / float(denominator), digits)


def format_ci(low: float | None, high: float | None, digits: int = 2) -> str:
    if low is None or high is None:
        return EMPTY
    return f"{low:.{digits}%} – {high:.{digits}%}"


def format_currency(value: Any, currency_code: str | None) -> str:
    if value is None:
        return EMPTY
    amount = Decimal(str(value))
    formatted = f"{amount:,.2f}"
    return f"{formatted} {currency_code}" if currency_code else formatted


def format_date(value: date | datetime | None) -> str:
    if value is None:
        return EMPTY
    return value.strftime("%Y-%m-%d")


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return EMPTY
    return value.strftime("%Y-%m-%d %H:%M UTC")


def format_window(start: datetime | None, end: datetime | None) -> str:
    if start is None and end is None:
        return EMPTY
    return f"{format_datetime(start)} → {format_datetime(end)}"


def format_days(value: Any) -> str:
    if value is None:
        return EMPTY
    return f"{float(value):,.1f} days"


def scope_label(value: Any) -> str:
    return label(SCOPE_LABELS, value)


def alert_type_label(value: Any) -> str:
    return label(ALERT_TYPE_LABELS, value)


def status_label(value: Any) -> str:
    return label(STATUS_LABELS, value)


def priority_label(value: Any) -> str:
    return label(PRIORITY_LABELS, value)


def outcome_label(value: Any) -> str:
    return label(OUTCOME_LABELS, value)


def reason_label(value: Any) -> str:
    return label(REASON_LABELS, value)


def inspection_label(value: Any) -> str:
    return label(INSPECTION_LABELS, value)


def condition_label(value: Any) -> str:
    return label(CONDITION_LABELS, value)
