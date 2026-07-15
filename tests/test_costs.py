from __future__ import annotations

import numpy as np
import pandas as pd

from casino.costs.model import CostModel


def _weights():
    idx = pd.date_range("2021-01-01", periods=100, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    return pd.DataFrame(rng.uniform(-0.5, 0.5, (100, 3)),
                        index=idx, columns=["A", "B", "C"])


def test_trade_cost_nonnegative_and_monotonic_in_fee():
    w = _weights()
    cheap = CostModel(taker_fee_bps=1).trade_cost_return(w)
    pricey = CostModel(taker_fee_bps=10).trade_cost_return(w)
    assert (cheap >= 0).all()
    assert (pricey >= 0).all()
    # Higher fees can only raise (never lower) the cost drag.
    assert pricey.sum() > cheap.sum()


def test_zero_turnover_zero_trade_cost():
    idx = pd.date_range("2021-01-01", periods=50, freq="1h", tz="UTC")
    w = pd.DataFrame(0.3, index=idx, columns=["A"])  # constant weight -> no turnover
    cost = CostModel().trade_cost_return(w)
    # Only the very first bar pays (establishing the position); the rest are zero.
    assert cost.iloc[1:].abs().sum() == 0.0


def test_funding_cost_sign():
    idx = pd.date_range("2021-01-01", periods=48, freq="1h", tz="UTC")
    long = pd.DataFrame(1.0, index=idx, columns=["A"])
    short = pd.DataFrame(-1.0, index=idx, columns=["A"])
    cm = CostModel(default_funding_rate=0.001, funding_interval_hours=8)
    fund_long = cm.funding_cost_return(long, None, idx, bars_per_hour=1.0)
    fund_short = cm.funding_cost_return(short, None, idx, bars_per_hour=1.0)
    # Longs PAY positive funding (cost > 0); shorts RECEIVE it (cost < 0).
    assert fund_long.sum() > 0
    assert np.isclose(fund_long.sum(), -fund_short.sum())
    # Funding only lands on interval bars (every 8h) -> 6 hits over 48 bars.
    assert (fund_long != 0).sum() == 6
