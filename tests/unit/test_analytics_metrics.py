import pytest

from loss_intelligence.analytics.metrics import build_rate_stats, wilson_interval


def test_wilson_interval_handles_empty_sample() -> None:
    assert wilson_interval(0, 0) == (None, None)


def test_wilson_interval_contains_observed_rate() -> None:
    low, high = wilson_interval(5, 100)

    assert low is not None
    assert high is not None
    assert low < 0.05 < high
    assert 0 <= low <= high <= 1


def test_wilson_interval_matches_reference_values() -> None:
    low, high = wilson_interval(5, 100)

    assert low == pytest.approx(0.02154, abs=1e-5)
    assert high == pytest.approx(0.11175, abs=1e-5)


def test_wilson_interval_accepts_all_successes() -> None:
    low, high = wilson_interval(10, 10)

    assert low is not None
    assert high == 1.0
    assert 0 < low < 1


def test_wilson_interval_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError):
        wilson_interval(2, 1)
    with pytest.raises(ValueError):
        wilson_interval(-1, 1)


def test_rate_stats_flags_low_volume() -> None:
    stats = build_rate_stats(1, 10, minimum_volume=30)

    assert stats.rate == 0.1
    assert stats.per_1000 == 100.0
    assert stats.low_volume is True
    assert stats.ci_low is not None
    assert stats.ci_high is not None


def test_rate_stats_marks_sufficient_volume() -> None:
    stats = build_rate_stats(3, 30, minimum_volume=30)

    assert stats.rate == 0.1
    assert stats.low_volume is False


def test_rate_stats_handles_zero_denominator() -> None:
    stats = build_rate_stats(0, 0)

    assert stats.rate is None
    assert stats.per_1000 is None
    assert stats.ci_low is None
    assert stats.ci_high is None
    assert stats.low_volume is True


def test_rate_stats_rejects_numerator_above_denominator() -> None:
    with pytest.raises(ValueError):
        build_rate_stats(2, 1)


def test_rate_stats_rejects_invalid_minimum_volume() -> None:
    with pytest.raises(ValueError):
        build_rate_stats(0, 1, minimum_volume=0)
