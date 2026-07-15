from __future__ import annotations

import numpy as np

from casino.backtest import engine
from casino.costs.model import CostModel
from casino.risk import sizing
from casino.signals import tsmom


def _net_sharpe(prices, cfg, shuffle_scores=False, seed=0):
    scores = tsmom.from_config(cfg).scores(prices)
    if shuffle_scores:
        rng = np.random.default_rng(seed)
        vals = scores.to_numpy()
        for j in range(vals.shape[1]):
            col = vals[:, j]
            mask = ~np.isnan(col)
            perm = rng.permutation(mask.sum())
            col[mask] = col[mask][perm]
            vals[:, j] = col
        scores.iloc[:, :] = vals
    w = sizing.size(scores, prices, cfg)
    zero_cm = CostModel(0, 0, 0, 0, 8, 0.0)
    res = engine.run_backtest(prices, w, zero_cm, cfg)
    r = res.net_returns.dropna()
    return float(r.mean() / r.std(ddof=1) * np.sqrt(cfg["risk"]["bars_per_year"]))


def test_scores_are_bounded_and_causal(prices, cfg):
    scores = tsmom.from_config(cfg).scores(prices)
    assert scores.max().max() <= 1.0 + 1e-9
    assert scores.min().min() >= -1.0 - 1e-9
    # Warmup region is NaN (no signal before lookback+vol windows fill).
    assert scores.iloc[:10].isna().all().all()


def test_signal_captures_known_momentum(prices, cfg):
    # Trending synthetic data -> TSMOM should earn a clearly positive Sharpe.
    assert _net_sharpe(prices, cfg) > 0.5


def test_shuffled_signal_destroys_edge(prices, cfg):
    real = _net_sharpe(prices, cfg)
    shuffled = _net_sharpe(prices, cfg, shuffle_scores=True, seed=1)
    # Destroying the signal's time alignment should collapse the edge.
    assert shuffled < real - 0.5


def test_no_edge_on_random_walk(noise_prices, cfg):
    # On trendless data the (cost-free) Sharpe should be modest, not a fantasy.
    assert abs(_net_sharpe(noise_prices, cfg)) < 2.0
