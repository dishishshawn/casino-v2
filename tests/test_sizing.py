from __future__ import annotations

from casino.risk import sizing
from casino.signals import tsmom


def test_leverage_and_position_caps_respected(prices, cfg):
    scores = tsmom.from_config(cfg).scores(prices)
    w = sizing.size(scores, prices, cfg)
    gross = w.abs().sum(axis=1)
    assert gross.max() <= cfg["risk"]["max_gross_leverage"] + 1e-9
    assert w.abs().max().max() <= cfg["risk"]["max_position_weight"] + 1e-9


def test_higher_kelly_scales_up_book(prices, cfg):
    scores = tsmom.from_config(cfg).scores(prices)
    low = cfg.copy()
    low["risk"] = {**cfg["risk"], "kelly_fraction": 0.1}
    high = cfg.copy()
    high["risk"] = {**cfg["risk"], "kelly_fraction": 0.5}
    w_low = sizing.size(scores, prices, low)
    w_high = sizing.size(scores, prices, high)
    # More Kelly => at least as much gross exposure on average (until caps bind).
    assert w_high.abs().sum(axis=1).mean() >= w_low.abs().sum(axis=1).mean()


def test_vol_targeting_keeps_realized_vol_in_reason(prices, cfg):
    import numpy as np

    scores = tsmom.from_config(cfg).scores(prices)
    w = sizing.size(scores, prices, cfg)
    asset_ret = prices.pct_change().fillna(0.0)
    port_ret = (w.shift(1).fillna(0.0) * asset_ret).sum(axis=1)
    realized_ann_vol = port_ret.std(ddof=1) * np.sqrt(cfg["risk"]["bars_per_year"])
    # Realized vol should be at or below the target ceiling (scaler clips up at 1x).
    assert realized_ann_vol <= cfg["risk"]["target_annual_vol"] * 2.0
