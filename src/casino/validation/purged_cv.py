"""Purged & embargoed K-fold cross-validation (Lopez de Prado).

Financial labels are NOT IID: a bar's label depends on a forward window of prices,
so naive K-fold leaks information from test into train. Two fixes:
  * PURGE: drop training observations whose label horizon overlaps the test window.
  * EMBARGO: drop a buffer of training observations right after each test window to
    kill serial-correlation leakage.

This splitter yields integer-position (train, test) index arrays over a time-ordered
sample and is the building block for CPCV.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np


def _purge_embargo(
    train_groups_idx: list[np.ndarray],
    test_idx: np.ndarray,
    n: int,
    label_horizon: int,
    embargo: int,
) -> np.ndarray:
    """Remove train indices overlapping [test_start - horizon, test_end + embargo]."""
    train = np.concatenate(train_groups_idx) if train_groups_idx else np.array([], dtype=int)
    if len(test_idx) == 0 or len(train) == 0:
        return np.sort(train)
    lo = test_idx.min() - label_horizon
    hi = test_idx.max() + embargo
    keep = train[(train < lo) | (train > hi)]
    return np.sort(keep)


def purged_kfold(
    n: int,
    n_splits: int,
    label_horizon: int = 0,
    embargo: int = 0,
):
    """Yield (train_idx, test_idx) for contiguous K folds with purge+embargo."""
    idx = np.arange(n)
    folds = np.array_split(idx, n_splits)
    for i, test_idx in enumerate(folds):
        train_groups = [f for j, f in enumerate(folds) if j != i]
        train_idx = _purge_embargo(train_groups, test_idx, n, label_horizon, embargo)
        yield train_idx, test_idx


def cpcv_splits(
    n: int,
    n_groups: int,
    k_test: int,
    label_horizon: int = 0,
    embargo: int = 0,
):
    """Yield (train_idx, test_idx, test_group_ids) for every combination of k groups.

    Combinatorial Purged CV: split the sample into `n_groups` contiguous groups and
    test on every choice of `k_test` of them, purging+embargoing the training set.
    Produces C(n_groups, k_test) splits -> a DISTRIBUTION of OOS paths, not one.
    """
    idx = np.arange(n)
    groups = np.array_split(idx, n_groups)
    for combo in combinations(range(n_groups), k_test):
        test_idx = np.concatenate([groups[g] for g in combo])
        train_groups = [groups[g] for g in range(n_groups) if g not in combo]
        # Purge around each contiguous test block separately for correctness.
        train_idx = np.concatenate(train_groups) if train_groups else np.array([], dtype=int)
        for g in combo:
            block = groups[g]
            lo, hi = block.min() - label_horizon, block.max() + embargo
            train_idx = train_idx[(train_idx < lo) | (train_idx > hi)]
        yield np.sort(train_idx), np.sort(test_idx), combo
