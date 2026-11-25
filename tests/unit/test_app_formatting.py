from datetime import UTC, date, datetime
from decimal import Decimal

from loss_intelligence.app.components import normalize_date_range
from loss_intelligence.app.formatting import (
    alert_type_label,
    condition_label,
    format_ci,
    format_currency,
    format_date,
    format_datetime,
    format_days,
    format_int,
    format_pct,
    format_per_1000,
    format_rate,
    humanize,
    inspection_label,
    outcome_label,
    priority_label,
    reason_label,
    scope_label,
    status_label,
)
from loss_intelligence.app.views.hotspots import _previous_period


def test_formatting_numbers_rates_and_currency() -> None:
    assert format_int(12345) == "12,345"
    assert format_int(None) == "—"
    assert format_pct(0.01698) == "1.70%"
    assert format_pct(None) == "—"
    assert format_per_1000(16.98) == "16.98"
    assert format_rate(5, 200) == "2.50%"
    assert format_rate(1, 0) == "—"
    assert format_ci(0.01, 0.03) == "1.00% – 3.00%"
    assert format_ci(None, 0.03) == "—"
    assert format_currency(Decimal("1234.5"), "ARS") == "1,234.50 ARS"
    assert format_currency(None, "ARS") == "—"
    assert format_days(3.45) == "3.5 days"


def test_formatting_dates_and_labels() -> None:
    dt = datetime(2026, 2, 3, 14, 5, tzinfo=UTC)
    assert format_date(dt) == "2026-02-03"
    assert format_datetime(dt) == "2026-02-03 14:05 UTC"
    assert humanize("needs_more_evidence") == "Needs more evidence"
    assert humanize(None) == "—"
    assert scope_label("carrier_zone") == "Carrier / zone"
    assert alert_type_label("damage_rate_spike") == "Damage rate spike"
    assert status_label("in_review") == "In review"
    assert priority_label("critical") == "Critical"
    assert outcome_label("data_quality_issue") == "Data quality issue"
    assert reason_label("not_as_described") == "Not as described"
    assert inspection_label("does_not_match_declaration") == "Does not match declaration"
    assert condition_label("incomplete") == "Incomplete"


def test_normalize_date_range_handles_all_widget_shapes() -> None:
    day_one = date(2026, 1, 1)
    day_two = date(2026, 1, 10)
    assert normalize_date_range(None) == (None, None)
    assert normalize_date_range([]) == (None, None)
    assert normalize_date_range(day_one) == (day_one, day_one)
    assert normalize_date_range((day_one,)) == (day_one, day_one)
    assert normalize_date_range((day_one, day_two)) == (day_one, day_two)


def test_previous_period_computes_equal_length_preceding_window() -> None:
    assert _previous_period(None, date(2026, 1, 10)) == (None, None)
    assert _previous_period(date(2026, 1, 11), date(2026, 1, 20)) == (
        date(2026, 1, 1),
        date(2026, 1, 10),
    )
