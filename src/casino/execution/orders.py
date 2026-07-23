"""Target weights (fraction of equity) -> discrete order intents, diffed
against currently-held quantities. Pure arithmetic -- no broker, no network.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str   # "buy" | "sell"
    qty: float  # base-asset quantity, always positive


def weights_to_orders(
    target_weights: pd.Series,
    current_positions: dict[str, float],
    equity: float,
    prices: pd.Series,
    min_trade_notional: float = 10.0,
) -> list[OrderIntent]:
    """Diff target weights against held qty -> order intents.

    Skips any leg whose notional delta is below `min_trade_notional` -- avoids
    dust-sized taker fills that are pure cost bleed, the same discipline
    `risk.sizing.throttle_rebalance` applies in the backtest.
    """
    orders: list[OrderIntent] = []
    for symbol, w in target_weights.items():
        if pd.isna(w):
            continue
        px = prices.get(symbol)
        if px is None or pd.isna(px) or px <= 0:
            continue
        target_qty = (float(w) * equity) / px
        held_qty = current_positions.get(symbol, 0.0)
        delta_qty = target_qty - held_qty
        notional = abs(delta_qty) * px
        if notional < min_trade_notional:
            continue
        side = "buy" if delta_qty > 0 else "sell"
        orders.append(OrderIntent(symbol=symbol, side=side, qty=abs(delta_qty)))
    return orders
