from __future__ import annotations

import numpy as np
import pandas as pd

from casino.validation import cpcv
from casino.validation.deflated_sharpe import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
)
from casino.validation.purged_cv import cpcv_splits, purged_kfold


def test_purge_removes_overlapping_train_labels():
    n = 100
    horizon = 5
    embargo = 3
    for train, test in purged_kfold(n, n_splits=5, label_horizon=horizon, embargo=embargo):
        if len(test) == 0 or len(train) == 0:
            continue
        lo, hi = test.min() - horizon, test.max() + embargo
        # No training index may fall inside the purge+embargo window around test.
        assert not ((train >= lo) & (train <= hi)).any()
        # Train and test never intersect.
        assert len(np.intersect1d(train, test)) == 0


def test_cpcv_produces_multiple_paths():
    n = 400
    splits = list(cpcv_splits(n, n_groups=6, k_test=2))
    # C(6,2) = 15 combinations -> 15 OOS paths.
    assert len(splits) == 15
    for train, test, combo in splits:
        assert len(np.intersect1d(train, test)) == 0
        assert len(combo) == 2


def test_psr_increases_with_sample_size():
    lo = probabilistic_sharpe_ratio(0.1, n=50, skew=0, kurtosis=3)
    hi = probabilistic_sharpe_ratio(0.1, n=5000, skew=0, kurtosis=3)
    assert hi > lo


def test_dsr_shrinks_as_trials_grow():
    kwargs = dict(sr=0.12, n=2000, skew=0.0, kurtosis=3.0, sr_variance=0.01)
    few = deflated_sharpe_ratio(n_trials=1, **kwargs)
    many = deflated_sharpe_ratio(n_trials=200, **kwargs)
    # More trials -> higher benchmark -> lower deflated probability.
    assert many < few


def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(100, 0.01) > expected_max_sharpe(5, 0.01)


def test_pbo_high_for_pure_noise():
    # Many pure-noise 'strategies': best-in-sample should not persist OOS -> PBO ~ 0.5.
    rng = np.random.default_rng(0)
    T, M = 2000, 20
    mat = pd.DataFrame(rng.standard_normal((T, M)) * 0.01,
                       columns=[f"cfg{i}" for i in range(M)])
    pbo = cpcv.probability_of_backtest_overfitting(mat, n_partitions=8)
    assert 0.25 <= pbo <= 0.75


def test_pbo_low_for_one_genuinely_good_strategy():
    # One config has a real positive drift; the rest are noise -> low PBO.
    rng = np.random.default_rng(1)
    T, M = 2000, 20
    mat = rng.standard_normal((T, M)) * 0.01
    mat[:, 0] += 0.004  # genuine edge in cfg0
    df = pd.DataFrame(mat, columns=[f"cfg{i}" for i in range(M)])
    pbo = cpcv.probability_of_backtest_overfitting(df, n_partitions=8)
    assert pbo < 0.25
