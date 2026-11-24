from __future__ import annotations

import math
from statistics import NormalDist


def two_proportion_z(
    observed_numerator: int,
    observed_denominator: int,
    baseline_numerator: int,
    baseline_denominator: int,
) -> tuple[float, float]:
    for numerator, denominator in (
        (observed_numerator, observed_denominator),
        (baseline_numerator, baseline_denominator),
    ):
        if denominator <= 0:
            raise ValueError("denominators must be positive")
        if numerator < 0 or numerator > denominator:
            raise ValueError("numerators must be between zero and their denominator")

    observed_rate = observed_numerator / observed_denominator
    baseline_rate = baseline_numerator / baseline_denominator
    pooled = (observed_numerator + baseline_numerator) / (
        observed_denominator + baseline_denominator
    )
    standard_error = math.sqrt(
        pooled * (1 - pooled) * ((1 / observed_denominator) + (1 / baseline_denominator))
    )
    if standard_error == 0:
        return 0.0, 1.0

    z_score = (observed_rate - baseline_rate) / standard_error
    p_value = 1 - NormalDist().cdf(z_score)
    return z_score, min(max(p_value, 0.0), 1.0)


def relative_lift(observed_rate: float, baseline_rate: float) -> float | None:
    if baseline_rate <= 0:
        return None
    return observed_rate / baseline_rate


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    if any(value < 0 or value > 1 for value in p_values):
        raise ValueError("p-values must be between zero and one")

    count = len(p_values)
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    q_values = [1.0] * count
    running_minimum = 1.0

    for rank in range(count, 0, -1):
        index, p_value = ordered[rank - 1]
        adjusted = p_value * count / rank
        running_minimum = min(running_minimum, adjusted)
        q_values[index] = min(running_minimum, 1.0)

    return q_values
