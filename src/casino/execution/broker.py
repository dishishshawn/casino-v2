"""Broker interface: the seam between strategy and venue.

Every later venue integration (an exchange testnet, an eventual regulated-
futures API) implements this Protocol. Nothing in this module makes a network
call. Implementations that do belong on a host you control, wired with venue
keys that must NEVER live in this repo or an ephemeral cloud sandbox -- see
EXECUTION.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    ts: str


class Broker(Protocol):
    def get_positions(self) -> dict[str, float]: ...

    def get_equity(self, marks: dict[str, float]) -> float: ...

    def place_order(
        self, symbol: str, side: str, qty: float, mark_price: float, ts
    ) -> Fill: ...
