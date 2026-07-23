"""Live decision loop: one tick = mark-to-market -> kill-switch check -> diff
target weights against broker positions -> submit orders.

`run_replay` drives this over a cached historical panel with the paper
broker, as an end-to-end offline smoke test of the whole decision pipeline --
useful right now, before any real-time feed or venue adapter exists. Swap
`broker` for a real `Broker` implementation and feed live bars in to go from
replay to an actual (paper or live) trading loop -- on a host you control,
never here (see EXECUTION.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from casino.execution import orders as orders_mod
from casino.execution.book import target_weights
from casino.execution.broker import Broker
from casino.execution.killswitch import KillSwitch


@dataclass
class TickResult:
    ts: pd.Timestamp
    orders: list[orders_mod.OrderIntent]
    halted: bool
    halt_reason: str | None
    equity: float


def run_tick(
    ts: pd.Timestamp,
    weights_row: pd.Series,
    prices_row: pd.Series,
    broker: Broker,
    killswitch: KillSwitch,
    min_trade_notional: float,
) -> TickResult:
    marks = prices_row.dropna().to_dict()
    equity = broker.get_equity(marks)
    halted, reason = killswitch.should_halt(equity, bar_ts=ts)
    if halted:
        return TickResult(ts, [], True, reason, equity)

    intents = orders_mod.weights_to_orders(
        weights_row, broker.get_positions(), equity, prices_row, min_trade_notional
    )
    for intent in intents:
        broker.place_order(intent.symbol, intent.side, intent.qty, prices_row[intent.symbol], ts)

    return TickResult(ts, intents, False, None, broker.get_equity(marks))


def run_replay(
    prices: pd.DataFrame,
    funding: pd.DataFrame | None,
    cfg: dict,
    broker: Broker,
    killswitch: KillSwitch,
) -> list[TickResult]:
    """Replay every bar of a cached panel through the decision loop.

    `target_weights` holds its value flat between rebalance-grid points (see
    `risk.sizing.throttle_rebalance`), and the cost model only charges a trade
    when that VALUE changes (`turnover = weights.diff()`). So orders are only
    generated on bars where the weight actually changed -- re-deriving a
    target quantity from the same flat weight fraction every bar (as price and
    equity drift) would manufacture "corrective" trades the validated backtest
    never priced in.
    """
    weights = target_weights(prices, funding, cfg)
    min_notional = float(cfg.get("execution", {}).get("min_trade_notional", 10.0))
    results: list[TickResult] = []
    prev_row: pd.Series | None = None
    for ts in weights.index:
        w_row = weights.loc[ts].dropna()
        if w_row.empty:
            continue
        rebalance_due = prev_row is None or not w_row.equals(prev_row)
        if rebalance_due:
            result = run_tick(ts, w_row, prices.loc[ts], broker, killswitch, min_notional)
            prev_row = w_row
        else:
            marks = prices.loc[ts].dropna().to_dict()
            equity = broker.get_equity(marks)
            halted, reason = killswitch.should_halt(equity, bar_ts=ts)
            result = TickResult(ts, [], halted, reason, equity)
        results.append(result)
        if result.halted:
            break
    return results
