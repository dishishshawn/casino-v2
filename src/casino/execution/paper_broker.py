"""Fully offline paper broker: no network, no keys, no venue connection.

Fills orders immediately at the supplied mark price, charging the SAME cost
model the backtest uses (taker fee + half-spread + slippage), so a paper run
and a backtest are directly comparable. This is a research / dry-run tool for
exercising the execution loop end-to-end. A later testnet or live adapter
implements the same `Broker` protocol (broker.py) against a real venue.
"""

from __future__ import annotations

import json
from pathlib import Path

from casino.costs.model import CostModel
from casino.execution.broker import Fill

BPS = 1e-4


class PaperBroker:
    def __init__(
        self,
        cost_model: CostModel,
        init_cash: float = 100_000.0,
        ledger_path: str | Path | None = None,
    ):
        self.cost_model = cost_model
        self.cash = float(init_cash)
        self.positions: dict[str, float] = {}
        self.fills: list[Fill] = []
        self.ledger_path = Path(ledger_path) if ledger_path else None

    def get_positions(self) -> dict[str, float]:
        return dict(self.positions)

    def get_equity(self, marks: dict[str, float]) -> float:
        pos_value = sum(qty * marks.get(sym, 0.0) for sym, qty in self.positions.items())
        return self.cash + pos_value

    def place_order(self, symbol: str, side: str, qty: float, mark_price: float, ts) -> Fill:
        if qty <= 0:
            raise ValueError("qty must be positive")
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
        notional = qty * mark_price
        fee_rate = (
            self.cost_model.taker_fee_bps
            + self.cost_model.half_spread_bps
            + self.cost_model.slippage_base_bps
        ) * BPS
        fee = notional * fee_rate
        signed = qty if side == "buy" else -qty
        self.positions[symbol] = self.positions.get(symbol, 0.0) + signed
        self.cash -= signed * mark_price + fee
        fill = Fill(symbol=symbol, side=side, qty=qty, price=mark_price, fee=fee, ts=str(ts))
        self.fills.append(fill)
        if self.ledger_path:
            self._append_ledger(fill)
        return fill

    def _append_ledger(self, fill: Fill) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_path, "a") as fh:
            fh.write(json.dumps(fill.__dict__) + "\n")
