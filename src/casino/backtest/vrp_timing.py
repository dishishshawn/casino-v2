"""Variance-risk-premium market-timing sleeve.

We cannot harvest the crypto VRP cleanly (that needs options, which this engine
does not model). Instead we use the VRP as a forward-looking market-TIMING signal
on a broad perp basket: when implied vol (Deribit DVOL) is richly above realized
vol, the market is pricing more fear than has materialized — historically
associated with subsequent weak/negative index returns — so we tilt risk-off;
when the premium is low/negative we tilt risk-on.

Distinct from our existing sizing (which scales by TRAILING realized vol): this
signal is driven by FORWARD-looking implied vol and takes a directional view on
the market basket, giving a return stream ~uncorrelated to the momentum sleeve.

Honest caveat: this is a directional market-timing bet. In bull regimes it will
be net long (beta-like); its genuine value-add is turning defensive in the 2022
bear / 2025 chop, which the regime walk-forward is there to verify. Modeled as a
return stream because the position is on a basket, not a single instrument.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from casino.costs.model import CostModel


def _bars_per_hour(timeframe: str) -> float:
    table = {"1m": 60, "5m": 12, "15m": 4, "1h": 1, "4h": 0.25, "1d": 1 / 24}
    return table[timeframe]


def vrp_position(
    prices: pd.DataFrame,
    dvol: pd.Series,
    cfg: dict,
) -> pd.Series:
    """Causal market-timing position in [-1, 1] from the variance risk premium."""
    v = cfg.get("vrp", {})
    bph = _bars_per_hour(cfg["data"]["timeframe"])
    bpy = int(cfg["risk"]["bars_per_year"])
    rv_win = max(2, round(v.get("realized_vol_hours", 168) * bph))
    z_win = max(2, round(v.get("zscore_hours", 720) * bph))

    idx = prices.index
    mkt = prices.pct_change().mean(axis=1)                      # equal-weight index return
    realized = mkt.rolling(rv_win).std() * np.sqrt(bpy)         # trailing realized ann vol
    implied = dvol.reindex(idx.union(dvol.index)).ffill().reindex(idx)  # forward implied vol
    vrp = implied - realized                                    # variance risk premium
    z = (vrp - vrp.rolling(z_win).mean()) / vrp.rolling(z_win).std()
    # Risk-off when the premium is richly high: short the basket; risk-on when low.
    pos = (-np.tanh(z)).clip(-1.0, 1.0)

    # Daily rebalance throttle: the VRP regime moves slowly; don't re-trade hourly.
    rb_hours = float(cfg["risk"].get("rebalance_hours", 0) or 0)
    if rb_hours > 0:
        step = max(1, round(rb_hours * bph))
        if step > 1:
            off = (np.arange(len(pos)) % step) != 0
            pos = pos.copy()
            pos.iloc[off] = np.nan
            pos = pos.ffill()
    return pos.rename("vrp_pos")


def vrp_timing_returns(
    prices: pd.DataFrame,
    dvol: pd.Series,
    cost_model: CostModel,
    cfg: dict,
) -> pd.Series:
    """Net per-bar return of the VRP market-timing sleeve (basket position)."""
    if dvol is None or not len(dvol):
        raise ValueError("vrp_timing_returns requires a non-empty DVOL series")
    pos = vrp_position(prices, dvol, cfg)
    mkt = prices.pct_change().mean(axis=1)

    # Constant-exposure basket bet (|pos| <= 1). NOTE: we deliberately do NOT
    # vol-target this sleeve by market vol -- the signal's edge is concentrated in
    # HIGH-vol fear regimes, so scaling exposure down when vol is high would fight
    # the signal. Equal-risk weighting for a blend is done at the blend level.
    gross = (pos.shift(1).fillna(0.0) * mkt).rename("gross")  # hold into next bar (causal)

    # Cost on basket-notional turnover as |pos| changes.
    turnover = pos.fillna(0.0).diff().abs()
    turnover.iloc[0] = abs(pos.iloc[0]) if pd.notna(pos.iloc[0]) else 0.0
    rate = cost_model.per_trade_rate(turnover.to_frame("m"))["m"]
    cost = rate * turnover
    return (gross - cost).rename("net")
