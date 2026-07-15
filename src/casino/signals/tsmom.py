"""Time-series momentum (TSMOM) — the anchor edge.

Per Moskowitz, Ooi & Pedersen (2012): an instrument's own past return positively
predicts its next-period return. We follow the brief's crypto adaptation: SHORTER
lookbacks than the equity 12-month (days-to-weeks), long/short symmetric, and the
raw trend risk-normalized by recent volatility before being squashed to [-1, 1].

The score is causal (uses only past/current prices) and lookback-blended so no
single horizon dominates — model whole-config robustness, not one magic parameter.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from casino.signals.base import Signal


class TSMomentum(Signal):
    name = "tsmom"

    def __init__(
        self,
        lookbacks_bars: list[int],
        vol_lookback_bars: int,
        score_cap: float = 1.0,
    ):
        if not lookbacks_bars:
            raise ValueError("lookbacks_bars must be non-empty")
        self.lookbacks_bars = list(lookbacks_bars)
        self.vol_lookback_bars = int(vol_lookback_bars)
        self.score_cap = float(score_cap)

    def scores(self, prices: pd.DataFrame) -> pd.DataFrame:
        log_px = np.log(prices.astype(float))
        rets = log_px.diff()
        # Per-bar vol used to risk-normalize the trend, so a fixed trend on a calm
        # asset scores higher than the same trend on a wild one.
        bar_vol = rets.ewm(span=self.vol_lookback_bars, min_periods=self.vol_lookback_bars).std()

        blended = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
        n = 0
        for lb in self.lookbacks_bars:
            # Trend = cumulative log return over the lookback (causal).
            trend = log_px - log_px.shift(lb)
            # Normalize by expected move over the same horizon: vol * sqrt(lookback).
            denom = bar_vol * np.sqrt(lb)
            z = trend / denom.replace(0.0, np.nan)
            blended = blended.add(np.tanh(z), fill_value=0.0)
            n += 1

        scores = (blended / n).clip(-self.score_cap, self.score_cap)
        # No position until every lookback + vol window has warmed up.
        warmup = max(max(self.lookbacks_bars), self.vol_lookback_bars)
        scores.iloc[:warmup] = np.nan
        return scores


def from_config(cfg: dict) -> TSMomentum:
    """Build a TSMomentum from a config dict (hours -> bars via timeframe)."""
    s = cfg["signal"]
    bars_per_hour = _bars_per_hour(cfg["data"]["timeframe"])
    lookbacks = [max(1, round(h * bars_per_hour)) for h in s["lookbacks_hours"]]
    vol_lb = max(2, round(s["vol_lookback_hours"] * bars_per_hour))
    return TSMomentum(lookbacks, vol_lb, s.get("score_cap", 1.0))


def _bars_per_hour(timeframe: str) -> float:
    table = {"1m": 60, "5m": 12, "15m": 4, "1h": 1, "4h": 0.25, "1d": 1 / 24}
    if timeframe not in table:
        raise ValueError(f"unsupported timeframe {timeframe}")
    return table[timeframe]
