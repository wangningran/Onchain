"""A/B testing: two-proportion z-test, sample-ratio-mismatch check, MDE / power."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from scipy import stats


@dataclass
class ABResult:
    n_a: int
    n_b: int
    rate_a: float
    rate_b: float
    abs_lift: float
    rel_lift: float
    ci_low: float  # 95% CI of absolute lift
    ci_high: float
    z: float
    p_value: float
    significant: bool

    def as_dict(self):
        return asdict(self)


def two_proportion_test(x_a: int, n_a: int, x_b: int, n_b: int, alpha: float = 0.05) -> ABResult:
    p_a, p_b = x_a / n_a, x_b / n_b
    pooled = (x_a + x_b) / (n_a + n_b)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    z = (p_b - p_a) / se_pooled
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    se = math.sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)  # unpooled for the CI
    zc = stats.norm.ppf(1 - alpha / 2)
    diff = p_b - p_a
    return ABResult(n_a, n_b, p_a, p_b, diff, diff / p_a, diff - zc * se, diff + zc * se, z, p, p < alpha)


def srm_check(n_a: int, n_b: int, expected_split: float = 0.5, threshold: float = 0.001) -> dict:
    """Chi-square test for sample ratio mismatch. p < threshold => assignment is broken, don't trust results."""
    total = n_a + n_b
    chi2, p = stats.chisquare([n_a, n_b], [total * expected_split, total * (1 - expected_split)])
    return dict(chi2=float(chi2), p_value=float(p), srm_detected=bool(p < threshold))


def minimum_detectable_effect(n_per_arm: int, base_rate: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Absolute MDE for a two-sided two-proportion test with equal arms."""
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return z * math.sqrt(2 * base_rate * (1 - base_rate) / n_per_arm)


def required_sample_size(base_rate: float, mde_abs: float, alpha: float = 0.05, power: float = 0.8) -> int:
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return math.ceil(2 * base_rate * (1 - base_rate) * (z / mde_abs) ** 2)
