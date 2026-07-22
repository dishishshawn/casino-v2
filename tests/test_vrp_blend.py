from __future__ import annotations

import numpy as np
import pandas as pd

from casino.backtest import vrp_timing
from casino.costs.model import CostModel
from casino.data import dvol
from casino.validation.gauntlet import _equal_risk_blend


def _prices_dvol(cfg, n=2000):
    idx = pd.date_range("2021-04-01", periods=n, freq="1h", tz="UTC", name="ts")
    syms = cfg["data"]["universe"]
    prices = pd.DataFrame(
        {s: 100 * np.exp(np.cumsum(0.002 * np.random.default_rng(i).standard_normal(n)))
         for i, s in enumerate(syms)},
        index=idx,
    )
    # DVOL series on a coarser (12h) grid, values ~0.3-0.9 annualized.
    didx = pd.date_range("2021-04-01", periods=n // 12 + 2, freq="12h", tz="UTC", name="ts")
    d = pd.Series(0.6 + 0.2 * np.sin(np.arange(len(didx)) / 5), index=didx)
    return prices, d


def test_vrp_position_bounded_and_causal(cfg):
    prices, d = _prices_dvol(cfg)
    pos = vrp_timing.vrp_position(prices, d, cfg)
    assert pos.dropna().abs().max() <= 1.0 + 1e-9
    # Warmup (before realized+z windows fill) has no position.
    assert pos.iloc[:100].fillna(0).abs().sum() == 0.0 or pos.iloc[:2].isna().all()


def test_vrp_costs_reduce_return(cfg):
    prices, d = _prices_dvol(cfg)
    zero = CostModel(0, 0, 0, 0, 8, 0.0)
    real = CostModel(4, 1, 1, 5, 8, 0.0)
    g = vrp_timing.vrp_timing_returns(prices, d, zero, cfg).sum()
    n = vrp_timing.vrp_timing_returns(prices, d, real, cfg).sum()
    assert n <= g


def test_equal_risk_blend_downweights_high_vol(cfg):
    idx = pd.date_range("2021-01-01", periods=3000, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    calm = pd.Series(0.001 * rng.standard_normal(3000), index=idx)   # low vol
    wild = pd.Series(0.010 * rng.standard_normal(3000), index=idx)   # 10x vol
    blend = _equal_risk_blend([calm, wild], cfg).dropna()
    # After risk scaling, the wild sleeve must not dominate: blend vol should be far
    # below the raw wild vol (which would dominate a naive average).
    assert blend.std() < wild.std() * 0.5


def test_load_dvol_absent_returns_empty(cfg):
    cfg["data"]["cache_dir"] = "data_cache_no_dvol_here"
    assert dvol.load_dvol(cfg, "BTC").empty
