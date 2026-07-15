"""Realistic cost model — taker fees + spread + slippage + funding.

The brief is emphatic: "backtests ignoring costs routinely flip from profitable to
losing" and momentum structurally PAYS slippage because it demands liquidity in the
direction price is already moving. So slippage here is adverse (not mid-price), and
scales with how much you trade (turnover), plus a base term.

Two cost channels:
  * trade_cost_rate: charged on traded notional (|Δ weight|) each rebalance —
    taker fee + half-spread + base slippage + impact*turnover.
  * funding_cost: charged on HELD notional across funding timestamps.

Costs are returned as per-bar return drags so the backtest can subtract them from
gross strategy returns, and vectorbt can also consume trade_cost_rate as fees.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

BPS = 1e-4


@dataclass
class CostModel:
    taker_fee_bps: float = 4.0
    half_spread_bps: float = 1.0
    slippage_base_bps: float = 1.0
    slippage_impact_bps: float = 5.0
    funding_interval_hours: int = 8
    default_funding_rate: float = 0.0001

    def per_trade_rate(self, turnover: pd.DataFrame) -> pd.DataFrame:
        """Cost rate applied to traded notional, given |Δweight| turnover per asset.

        turnover is a fraction of equity traded (e.g. 0.5 = rebalanced half the book).
        Impact scales with turnover; the rest is fixed per cross.
        """
        fixed = (self.taker_fee_bps + self.half_spread_bps + self.slippage_base_bps) * BPS
        impact = self.slippage_impact_bps * BPS * turnover.abs()
        return fixed + impact

    def trade_cost_return(self, weights: pd.DataFrame) -> pd.Series:
        """Portfolio return drag from trading, per bar (>= 0).

        weights: target weight panel (post-sizing). Turnover = |w_t - w_{t-1}|.
        """
        turnover = weights.fillna(0.0).diff().abs()
        turnover.iloc[0] = weights.iloc[0].abs().fillna(0.0)
        cost = (self.per_trade_rate(turnover) * turnover).sum(axis=1)
        return cost.rename("trade_cost")

    def funding_cost_return(
        self,
        weights: pd.DataFrame,
        funding: pd.DataFrame | None,
        index: pd.DatetimeIndex,
        bars_per_hour: float,
    ) -> pd.Series:
        """Portfolio return drag from funding, per bar.

        Longs pay positive funding, shorts receive it: drag = w * funding_rate.
        If a real funding panel is missing, fall back to default_funding_rate applied
        at the funding cadence. Positive result = cost, negative = credit.
        """
        w = weights.fillna(0.0)
        # Per-bar funding rate panel aligned to weights.
        if funding is not None and len(funding):
            fr = funding.reindex(index).ffill()
            fr = fr.reindex(columns=w.columns).fillna(0.0)
            # funding_rate is per funding interval; it only "lands" on interval bars.
            fr = self._mask_to_intervals(fr, bars_per_hour)
        else:
            fr = self._default_funding_panel(w, bars_per_hour)
        drag = (w * fr).sum(axis=1)
        return drag.rename("funding_cost")

    def _interval_bars(self, bars_per_hour: float) -> int:
        return max(1, round(self.funding_interval_hours * bars_per_hour))

    def _mask_to_intervals(self, fr: pd.DataFrame, bars_per_hour: float) -> pd.DataFrame:
        step = self._interval_bars(bars_per_hour)
        mask = np.zeros(len(fr), dtype=bool)
        mask[::step] = True
        out = fr.copy()
        out.loc[~mask] = 0.0
        return out

    def _default_funding_panel(self, w: pd.DataFrame, bars_per_hour: float) -> pd.DataFrame:
        step = self._interval_bars(bars_per_hour)
        fr = pd.DataFrame(0.0, index=w.index, columns=w.columns)
        fr.iloc[::step] = self.default_funding_rate
        return fr


def from_config(cfg: dict) -> CostModel:
    c = cfg["costs"]
    return CostModel(
        taker_fee_bps=c["taker_fee_bps"],
        half_spread_bps=c["half_spread_bps"],
        slippage_base_bps=c["slippage_base_bps"],
        slippage_impact_bps=c["slippage_impact_bps"],
        funding_interval_hours=c["funding_interval_hours"],
        default_funding_rate=c["default_funding_rate"],
    )
