"""Funding-carry signal — an orthogonal sleeve to time-series momentum.

Perp funding is paid by the crowded side: when funding is positive, longs pay
shorts, so a SHORT position *earns* the funding (and vice-versa). This sleeve
therefore tilts OPPOSITE the sign of funding, sized by how rich funding is.

Why it complements TSMOM: funding is richest in euphoric, over-crowded markets —
often the choppy, mean-reverting regimes where momentum bleeds. Carry and trend
are largely uncorrelated, so blending them can raise portfolio Sharpe through
genuine diversification rather than by over-fitting either signal.

Caveat (honest): this engine holds a single directional perp leg per instrument,
so this is NAKED carry (funding harvest WITH price risk), not delta-neutral
cash-and-carry (which would need a spot leg the engine doesn't model). Price risk
is handled downstream by the same vol-targeting/portfolio construction as TSMOM.

Causal: the score at bar t uses only funding realized up to and including t.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from casino.signals.base import Signal


class CarrySignal(Signal):
    name = "carry"

    def __init__(
        self,
        funding: pd.DataFrame,
        lookback_bars: int,
        funding_interval_bars: int,
        carry_ref_annual: float = 0.30,
        score_cap: float = 1.0,
        market_neutral: bool = True,
    ):
        if funding is None or not len(funding):
            raise ValueError("CarrySignal requires a non-empty funding panel")
        self.funding = funding
        self.lookback_bars = max(1, int(lookback_bars))
        self.funding_interval_bars = max(1, int(funding_interval_bars))
        self.carry_ref_annual = float(carry_ref_annual)
        self.score_cap = float(score_cap)
        # Cross-sectional dollar-neutral carry: demean scores across instruments
        # each bar so the book is ~market-neutral. This strips the market beta
        # (price risk) that makes NAKED directional carry a loser, keeping the
        # relative funding harvest that is the actual edge.
        self.market_neutral = bool(market_neutral)

    def scores(self, prices: pd.DataFrame) -> pd.DataFrame:
        # Align funding to the price grid; ffill holds the last realized rate
        # (known at its calc time) forward -> causal.
        fr = (
            self.funding.reindex(columns=prices.columns)
            .reindex(prices.index)
            .ffill()
        )
        # Smooth recent funding to capture the persistent funding regime.
        smoothed = fr.ewm(span=self.lookback_bars, min_periods=self.lookback_bars).mean()
        # Annualize the per-interval rate so the reference scale is interpretable.
        intervals_per_year = 8760.0 / (self.funding_interval_bars)  # bars are hourly here
        smoothed_annual = smoothed * intervals_per_year
        # SHORT positive funding to earn it: score = -tanh(annual_funding / ref).
        z = smoothed_annual / max(self.carry_ref_annual, 1e-9)
        scores = -np.tanh(z)
        if self.market_neutral:
            # Demean across instruments each bar -> ~dollar-neutral (long low /
            # short high funding). Uses only same-bar cross-section -> causal.
            scores = scores.sub(scores.mean(axis=1), axis=0)
        scores = scores.clip(-self.score_cap, self.score_cap)
        scores.iloc[: self.lookback_bars] = np.nan
        return scores


def from_config(cfg: dict, funding: pd.DataFrame) -> CarrySignal:
    """Build a CarrySignal from config (hours -> bars via timeframe)."""
    c = cfg.get("carry", {})
    bph = _bars_per_hour(cfg["data"]["timeframe"])
    lookback = max(1, round(c.get("lookback_hours", 72) * bph))
    interval_bars = max(1, round(cfg["costs"]["funding_interval_hours"] * bph))
    return CarrySignal(
        funding=funding,
        lookback_bars=lookback,
        funding_interval_bars=interval_bars,
        carry_ref_annual=c.get("carry_ref_annual", 0.30),
        score_cap=c.get("score_cap", 1.0),
        market_neutral=c.get("market_neutral", True),
    )


def _bars_per_hour(timeframe: str) -> float:
    table = {"1m": 60, "5m": 12, "15m": 4, "1h": 1, "4h": 0.25, "1d": 1 / 24}
    if timeframe not in table:
        raise ValueError(f"unsupported timeframe {timeframe}")
    return table[timeframe]
