"""CPCV-based OOS Sharpe distribution and the Probability of Backtest Overfitting.

Two outputs the gauntlet gates on:
  * oos_sharpe_distribution: Sharpe on each combinatorial-purged test block, giving a
    DISTRIBUTION of out-of-sample Sharpes instead of a single fragile number.
  * probability_of_backtest_overfitting (PBO): Bailey et al.'s CSCV. Given a matrix of
    candidate-config return series, how often does the config that looks best
    in-sample land below the median out-of-sample? High PBO => the selection is noise.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from casino.validation.purged_cv import cpcv_splits


def _sharpe(x: np.ndarray) -> float:
    x = x[~np.isnan(x)]
    if len(x) < 2:
        return 0.0
    sd = x.std(ddof=1)
    return float(x.mean() / sd) if sd > 0 else 0.0


def oos_sharpe_distribution(
    returns: pd.Series,
    n_groups: int,
    k_test: int,
    label_horizon: int = 0,
    embargo: int = 0,
) -> np.ndarray:
    """Per-observation Sharpe on each combinatorial purged test block."""
    r = returns.to_numpy()
    n = len(r)
    out = []
    for _train, test_idx, _combo in cpcv_splits(n, n_groups, k_test, label_horizon, embargo):
        out.append(_sharpe(r[test_idx]))
    return np.array(out)


def probability_of_backtest_overfitting(
    returns_matrix: pd.DataFrame,
    n_partitions: int = 8,
) -> float:
    """CSCV PBO over a T x M matrix of candidate-config per-bar return series.

    Splits time into `n_partitions` blocks, tries every half-split as in-sample,
    selects the best in-sample config, and measures how often it underperforms the
    median out-of-sample. Returns a probability in [0, 1]; lower is better.
    """
    R = returns_matrix.dropna(how="any")
    T, M = R.shape
    if M < 2 or n_partitions < 2 or T < n_partitions * 2:
        return float("nan")
    if n_partitions % 2 == 1:
        n_partitions -= 1
    blocks = np.array_split(np.arange(T), n_partitions)
    arr = R.to_numpy()
    half = n_partitions // 2
    logits = []
    for is_combo in combinations(range(n_partitions), half):
        is_rows = np.concatenate([blocks[b] for b in is_combo])
        oos_rows = np.concatenate([blocks[b] for b in range(n_partitions) if b not in is_combo])
        is_sr = np.array([_sharpe(arr[is_rows, m]) for m in range(M)])
        oos_sr = np.array([_sharpe(arr[oos_rows, m]) for m in range(M)])
        best = int(np.argmax(is_sr))
        # Relative rank of the IS-best config in the OOS ranking.
        rank = float((oos_sr <= oos_sr[best]).sum())  # 1..M
        w = rank / (M + 1.0)
        w = min(max(w, 1e-6), 1 - 1e-6)
        logits.append(np.log(w / (1.0 - w)))
    logits = np.array(logits)
    # PBO = fraction of splits where the IS-best config is below OOS median (logit<=0).
    return float((logits <= 0).mean())
