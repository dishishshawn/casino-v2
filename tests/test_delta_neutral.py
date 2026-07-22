from __future__ import annotations

import numpy as np
import pandas as pd

from casino.backtest import delta_neutral
from casino.costs.model import CostModel


def _funding(cfg, rate_by_sym):
    idx = pd.date_range("2021-01-01", periods=2000, freq="1h", tz="UTC", name="ts")
    return pd.DataFrame({s: rate_by_sym[s] for s in cfg["data"]["universe"]}, index=idx)


def test_deploys_only_on_positive_funding(cfg):
    syms = cfg["data"]["universe"]
    rates = {s: (0.0003 if i == 0 else -0.0003) for i, s in enumerate(syms)}
    d = delta_neutral.deploy_weights(_funding(cfg, rates), cfg).iloc[-1]
    assert d[syms[0]] > 0            # positive funding -> basis trade on
    assert (d[syms[1:]] == 0).all()  # negative funding -> no deployment


def test_positive_funding_earns_before_costs(cfg):
    syms = cfg["data"]["universe"]
    fund = _funding(cfg, {s: 0.0002 for s in syms})
    zero_cm = CostModel(0, 0, 0, 0, cfg["costs"]["funding_interval_hours"], 0.0)
    net = delta_neutral.dn_carry_returns(fund, zero_cm, cfg).dropna()
    # Cost-free, all-positive funding -> the sleeve accrues a positive mean return.
    assert net.mean() > 0


def test_costs_only_reduce_carry(cfg):
    syms = cfg["data"]["universe"]
    fund = _funding(cfg, {s: 0.0002 for s in syms})
    zero_cm = CostModel(0, 0, 0, 0, cfg["costs"]["funding_interval_hours"], 0.0)
    real_cm = CostModel(4, 1, 1, 5, cfg["costs"]["funding_interval_hours"], 0.0)
    gross = delta_neutral.dn_carry_returns(fund, zero_cm, cfg).sum()
    net = delta_neutral.dn_carry_returns(fund, real_cm, cfg).sum()
    assert net < gross


def test_throttle_cuts_turnover(cfg):
    syms = cfg["data"]["universe"]
    # Noisy funding so unthrottled deployment churns every bar.
    idx = pd.date_range("2021-01-01", periods=2000, freq="1h", tz="UTC", name="ts")
    rng = np.random.default_rng(0)
    fund = pd.DataFrame(
        {s: 0.0002 + 0.0002 * rng.standard_normal(2000) for s in syms}, index=idx
    )
    fast = {**cfg, "risk": {**cfg["risk"], "rebalance_hours": 0}}
    slow = {**cfg, "risk": {**cfg["risk"], "rebalance_hours": 24}}
    turn_fast = delta_neutral.deploy_weights(fund, fast).diff().abs().sum().sum()
    turn_slow = delta_neutral.deploy_weights(fund, slow).diff().abs().sum().sum()
    assert turn_slow < turn_fast
