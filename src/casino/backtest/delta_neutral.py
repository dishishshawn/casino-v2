"""Delta-neutral cash-and-carry: harvest perp funding with price risk hedged.

The naked / cross-sectional carry sleeves in `signals/carry.py` still carry price
risk (a single directional perp leg). The REAL crypto carry edge is the basis
trade: hold LONG SPOT and SHORT PERP in equal notional. Price moves cancel across
the two legs, so the position is ~delta-neutral and its P&L is the funding the
short-perp leg RECEIVES while funding is positive — a near-riskless carry.

This engine is otherwise perp-only and price-driven, so a directional backtest
can't express a two-leg hedged position. We therefore model the sleeve's return
stream DIRECTLY: deploy capital into coin i's basis trade when its funding is
positive/rich, accrue the realized funding, and charge trade costs on BOTH legs.

Honest limitations this cannot capture (a high Sharpe here is NOT risk-free):
  * perp liquidation / margin calls when price spikes against the short leg,
  * funding abruptly flipping negative, basis blowouts, exchange/counterparty risk
    (e.g. an Oct-2025-style cascade), and capacity limits.
Treat the Sharpe as an UPPER bound on a real, operationally-risky trade.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from casino.costs.model import CostModel


def _bars_per_hour(timeframe: str) -> float:
    table = {"1m": 60, "5m": 12, "15m": 4, "1h": 1, "4h": 0.25, "1d": 1 / 24}
    return table[timeframe]


def deploy_weights(funding: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Per-bar capital fraction in each coin's LONG-SPOT/SHORT-PERP basis trade.

    Only positive funding is harvested (the standard, cleanest basis trade: long
    spot / short perp earns positive funding). Sizing scales with funding richness,
    is capped per coin, and the book is capped at `max_gross_leverage` total (kept
    unlevered by default so the Sharpe is not inflated by leverage).
    """
    r = cfg["risk"]
    c = cfg.get("carry", {})
    bph = _bars_per_hour(cfg["data"]["timeframe"])
    intervals_per_year = 8760.0 / cfg["costs"]["funding_interval_hours"]
    lookback = max(1, round(c.get("lookback_hours", 72) * bph))

    fr = funding.copy()
    # Smooth realized funding to capture the persistent funding regime (causal).
    smoothed = fr.ewm(span=lookback, min_periods=lookback).mean()
    ref_per_interval = max(c.get("carry_ref_annual", 0.30) / intervals_per_year, 1e-12)
    # Long-basis only: deploy on positive funding, scaled by richness.
    raw = (smoothed / ref_per_interval).clip(lower=0.0)
    raw = raw.clip(upper=r.get("max_position_weight", 1.0))
    # Total-deployment cap (delta-neutral, so this is a margin/capital cap).
    gross = raw.sum(axis=1)
    cap = float(r.get("dn_max_gross", 1.0))
    scale = (cap / gross).clip(upper=1.0).replace([np.inf, np.nan], 1.0)
    d = raw.mul(scale, axis=0)
    warmup = lookback
    d.iloc[:warmup] = 0.0
    d = d.fillna(0.0)

    # Rebalance throttle: basis trades are held for days/weeks, not re-traded every
    # bar. Refresh deployment on the same daily grid as the rest of the book so the
    # two-leg trade costs don't swamp the funding harvest.
    rb_hours = float(r.get("rebalance_hours", 0) or 0)
    if rb_hours > 0:
        step = max(1, round(rb_hours * bph))
        if step > 1:
            off_grid = (np.arange(len(d)) % step) != 0
            d.iloc[off_grid] = np.nan
            d = d.ffill().fillna(0.0)
    return d


def dn_carry_returns(
    funding: pd.DataFrame,
    cost_model: CostModel,
    cfg: dict,
) -> pd.Series:
    """Net per-bar return of the delta-neutral carry sleeve."""
    bph = _bars_per_hour(cfg["data"]["timeframe"])
    interval_bars = max(1, round(cfg["costs"]["funding_interval_hours"] * bph))

    d = deploy_weights(funding, cfg)
    # Decide deployment at t, hold into the next bar (causal, matches the engine).
    d_held = d.shift(1).fillna(0.0)

    # Realized funding accrued per bar (spread the interval rate across its bars).
    fr = funding.reindex(d.index).ffill().reindex(columns=d.columns).fillna(0.0)
    fr_bar = fr / interval_bars
    # Delta-neutral: NO price term. Short perp RECEIVES positive funding.
    gross = (d_held * fr_bar).sum(axis=1).rename("gross")

    # Trade costs on BOTH legs (spot + perp) each rebalance; spot ~ perp taker cost.
    turnover = d.fillna(0.0).diff().abs()
    turnover.iloc[0] = d.iloc[0].abs().fillna(0.0)
    leg_cost = (cost_model.per_trade_rate(turnover) * turnover).sum(axis=1)
    cost = 2.0 * leg_cost

    return (gross - cost).rename("net")
