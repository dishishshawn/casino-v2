"""Probabilistic & Deflated Sharpe Ratio and Minimum Track Record Length.

Bailey & Lopez de Prado (2014). Two corrections a raw Sharpe badly needs:
  1. Non-normality: skew and kurtosis change the sampling variance of the Sharpe.
  2. Selection bias: if you tried N strategy configs, the best one's Sharpe is
     inflated by multiple testing. The Deflated Sharpe benchmarks the observed SR
     against the EXPECTED MAXIMUM Sharpe of N noise trials.

All SR inputs here are PER-OBSERVATION (non-annualized). Convert annualized SR by
dividing by sqrt(bars_per_year) before calling.
"""

from __future__ import annotations

import math

from scipy.stats import norm

EULER_MASCHERONI = 0.5772156649015329


def probabilistic_sharpe_ratio(
    sr: float,
    n: int,
    skew: float,
    kurtosis: float,
    sr_benchmark: float = 0.0,
) -> float:
    """P(true SR > sr_benchmark) given observed SR, sample size, skew, kurtosis.

    `kurtosis` is the NON-excess kurtosis (normal = 3).
    """
    if n < 2:
        return 0.5
    denom = math.sqrt(max(1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr, 1e-12))
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / denom
    return float(norm.cdf(z))


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Expected maximum of N independent SR estimates with variance `sr_variance`.

    E[max] ~ sqrt(V) * [(1-gamma) Z(1 - 1/N) + gamma Z(1 - 1/(N e))].
    This is the benchmark the Deflated Sharpe must beat.
    """
    n = max(int(n_trials), 2)
    v = max(sr_variance, 1e-12)
    z1 = norm.ppf(1.0 - 1.0 / n)
    z2 = norm.ppf(1.0 - 1.0 / (n * math.e))
    return float(math.sqrt(v) * ((1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2))


def deflated_sharpe_ratio(
    sr: float,
    n: int,
    skew: float,
    kurtosis: float,
    n_trials: int,
    sr_variance: float,
) -> float:
    """DSR = PSR evaluated against the expected-max-Sharpe benchmark.

    Returns a probability in [0, 1]; treat DSR > 0.95 as 'clearly significant'.
    """
    sr0 = expected_max_sharpe(n_trials, sr_variance)
    return probabilistic_sharpe_ratio(sr, n, skew, kurtosis, sr_benchmark=sr0)


def min_track_record_length(
    sr: float,
    skew: float,
    kurtosis: float,
    sr_benchmark: float = 0.0,
    target_prob: float = 0.95,
) -> float:
    """Minimum #observations for PSR(sr) >= target_prob. inf if SR <= benchmark."""
    if sr <= sr_benchmark:
        return math.inf
    z = norm.ppf(target_prob)
    return float(1.0 + (1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr) * (z / (sr - sr_benchmark)) ** 2)
