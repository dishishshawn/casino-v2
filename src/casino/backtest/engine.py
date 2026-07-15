"""Returns-based portfolio backtest with exact costs + perp funding.

Why returns-based rather than driving vectorbt end-to-end: perpetual-futures
FUNDING (a drag/credit on held notional across funding timestamps) and the brief's
turnover-scaled ADVERSE slippage are not things vectorbt models natively, and the
brief insists both be exact. So this engine is a transparent returns simulator we
fully control; vectorbt is used as an INDEPENDENT cross-check of the gross price
accounting (see backtest.vbt_check), honoring the chosen stack while keeping the
cost/funding model exact.

No lookahead: the target weight decided at bar t is held into bar t+1, so PnL at
t+1 uses weights known strictly before t+1.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from casino.costs.model import CostModel


@dataclass
class BacktestResult:
    net_returns: pd.Series
    gross_returns: pd.Series
    trade_costs: pd.Series
    funding_costs: pd.Series
    equity: pd.Series
    weights: pd.DataFrame
    init_cash: float

    @property
    def turnover(self) -> pd.Series:
        return self.weights.fillna(0.0).diff().abs().sum(axis=1)


def _bars_per_hour(timeframe: str) -> float:
    table = {"1m": 60, "5m": 12, "15m": 4, "1h": 1, "4h": 0.25, "1d": 1 / 24}
    return table[timeframe]


def run_backtest(
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    cost_model: CostModel,
    cfg: dict,
    funding: pd.DataFrame | None = None,
) -> BacktestResult:
    """Simulate the strategy net of trade costs and funding."""
    prices = prices.astype(float)
    weights = weights.reindex_like(prices).fillna(0.0)
    asset_ret = prices.pct_change().fillna(0.0)

    # Hold weight decided at t through the next bar's return (causal).
    w_held = weights.shift(1).fillna(0.0)
    gross = (w_held * asset_ret).sum(axis=1).rename("gross")

    trade_costs = cost_model.trade_cost_return(weights)
    bph = _bars_per_hour(cfg["data"]["timeframe"])
    funding_costs = cost_model.funding_cost_return(
        w_held, funding, prices.index, bph
    )

    net = (gross - trade_costs - funding_costs).rename("net")
    init_cash = float(cfg["backtest"]["init_cash"])
    equity = (init_cash * (1.0 + net).cumprod()).rename("equity")

    return BacktestResult(
        net_returns=net,
        gross_returns=gross,
        trade_costs=trade_costs.reindex(net.index).fillna(0.0),
        funding_costs=funding_costs.reindex(net.index).fillna(0.0),
        equity=equity,
        weights=weights,
        init_cash=init_cash,
    )


def vbt_check(prices: pd.DataFrame, weights: pd.DataFrame, cfg: dict) -> float:
    """Independent cross-check of gross (cost-free) total return via vectorbt.

    Returns vectorbt's total return for the same target-weight book so tests can
    assert our returns-based accounting agrees with a battle-tested engine.
    """
    import vectorbt as vbt

    prices = prices.astype(float)
    w = weights.reindex_like(prices).fillna(0.0)
    pf = vbt.Portfolio.from_orders(
        close=prices,
        size=w.shift(1).fillna(0.0),
        size_type="targetpercent",
        group_by=True,
        cash_sharing=True,
        fees=0.0,
        slippage=0.0,
        freq=cfg["data"]["timeframe"],
        init_cash=float(cfg["backtest"]["init_cash"]),
        call_seq="auto",
    )
    return float(pf.total_return())
