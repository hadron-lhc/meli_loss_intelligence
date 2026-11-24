from pathlib import Path

import pytest

from loss_intelligence.detection.config import DetectionConfig
from loss_intelligence.detection.statistics import (
    benjamini_hochberg,
    relative_lift,
    two_proportion_z,
)


def test_two_proportion_z_matches_reference_value() -> None:
    z_score, p_value = two_proportion_z(20, 100, 10, 100)

    assert z_score == pytest.approx(1.9803, abs=1e-4)
    assert p_value == pytest.approx(0.023835, abs=1e-6)


def test_two_proportion_z_handles_zero_variance() -> None:
    z_score, p_value = two_proportion_z(0, 100, 0, 100)

    assert z_score == 0.0
    assert p_value == 1.0


def test_two_proportion_z_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError):
        two_proportion_z(1, 0, 1, 10)
    with pytest.raises(ValueError):
        two_proportion_z(11, 10, 1, 10)


def test_relative_lift_handles_zero_baseline() -> None:
    assert relative_lift(0.2, 0.0) is None
    assert relative_lift(0.2, 0.1) == pytest.approx(2.0)


def test_benjamini_hochberg_controls_expected_values() -> None:
    assert benjamini_hochberg([0.01, 0.04, 0.03, 0.002]) == pytest.approx([0.02, 0.04, 0.04, 0.008])
    assert benjamini_hochberg([]) == []


def test_benjamini_hochberg_rejects_invalid_p_values() -> None:
    with pytest.raises(ValueError):
        benjamini_hochberg([-0.1])
    with pytest.raises(ValueError):
        benjamini_hochberg([1.1])


def test_detection_config_hash_is_stable_and_sensitive() -> None:
    first = DetectionConfig()
    second = DetectionConfig()
    changed = DetectionConfig(alpha=0.01)

    assert first.config_hash == second.config_hash
    assert first.config_hash != changed.config_hash
    assert len(first.config_hash) == 64


def test_detection_features_do_not_reference_evaluation_truth() -> None:
    detection_dir = Path(__file__).parents[2] / "src/loss_intelligence/detection"
    feature_files = (
        "config.py",
        "detector.py",
        "models.py",
        "queries.py",
        "statistics.py",
    )

    for filename in feature_files:
        source = (detection_dir / filename).read_text()
        assert "evaluation." not in source
        assert "synthetic_truth_links" not in source
