"""Volatility estimation and inverse-vol (risk-parity-ish) base weights.

Volatility targeting is the industry-standard way to size high-vol strategies
(the brief: CTAs target ~10-20% annualized; we start lower given crypto's vol).
Each asset is scaled inversely to its own forecast vol so dollar-risk is roughly
constant across instruments before the portfolio-level target is applied.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def forecast_annual_vol(
    prices: pd.DataFrame,
    halflife_bars: int,
    bars_per_year: int,
) -> pd.DataFrame:
    """EWMA annualized volatility forecast per asset, causal (uses past returns)."""
    rets = np.log(prices.astype(float)).diff()
    bar_vol = rets.ewm(halflife=halflife_bars, min_periods=max(2, halflife_bars // 2)).std()
    # Shift by one bar so the vol used at t is known strictly before t (no lookahead).
    bar_vol = bar_vol.shift(1)
    return bar_vol * np.sqrt(bars_per_year)


def inverse_vol_weights(
    scores: pd.DataFrame,
    ann_vol: pd.DataFrame,
    target_annual_vol: float,
    floor_vol: float = 1e-4,
) -> pd.DataFrame:
    """Per-asset target weights = score * (target_vol / forecast_vol).

    A score of +1 on an asset whose forecast vol equals the target maps to weight 1
    (fully invested at target risk); noisier assets get proportionally smaller size.
    """
    safe_vol = ann_vol.clip(lower=floor_vol)
    return scores * (target_annual_vol / safe_vol)
