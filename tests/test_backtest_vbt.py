"""Cross-check the returns-based engine against vectorbt's gross accounting."""

from __future__ import annotations

import numpy as np

from casino.backtest import engine
from casino.costs.model import CostModel
from casino.risk import sizing
from casino.signals import tsmom


def test_gross_return_matches_vectorbt(prices, cfg):
    scores = tsmom.from_config(cfg).scores(prices)
    weights = sizing.size(scores, prices, cfg)
    zero_cm = CostModel(0, 0, 0, 0, 8, 0.0)
    res = engine.run_backtest(prices, weights, zero_cm, cfg)
    ours = float(res.equity.iloc[-1] / res.init_cash - 1.0)
    theirs = engine.vbt_check(prices, weights, cfg)
    # Small discrepancy is expected (vectorbt rebalances via discrete orders vs our
    # continuous weight application), but they must agree in sign and rough magnitude.
    assert np.sign(ours) == np.sign(theirs)
    assert abs(ours - theirs) <= 0.25 * (abs(theirs) + 0.05)


def test_costs_reduce_returns(prices, cfg):
    from casino.costs.model import from_config as cost_from_config

    scores = tsmom.from_config(cfg).scores(prices)
    weights = sizing.size(scores, prices, cfg)
    gross = engine.run_backtest(prices, weights, CostModel(0, 0, 0, 0, 8, 0.0), cfg)
    net = engine.run_backtest(prices, weights, cost_from_config(cfg), cfg)
    assert net.equity.iloc[-1] < gross.equity.iloc[-1]
