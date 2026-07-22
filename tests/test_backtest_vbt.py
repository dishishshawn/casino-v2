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
    # Isolate the TRADE-cost channel: funding is signed (shorts receive it), so a
    # low-turnover short-biased book can net a funding CREDIT that exceeds tiny
    # trade costs. Trade costs alone are an unambiguous drag, so zero funding here.
    trade_only = cost_from_config(cfg)
    trade_only.default_funding_rate = 0.0
    net = engine.run_backtest(prices, weights, trade_only, cfg)
    assert net.equity.iloc[-1] < gross.equity.iloc[-1]
