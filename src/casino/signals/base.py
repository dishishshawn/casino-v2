"""Signal interface.

A Signal turns a price panel into a target-score panel in [-1, 1] per instrument
(sign = direction, magnitude = conviction). It knows NOTHING about position sizing,
leverage, costs, or order routing — those live downstream in risk/ and backtest/.
This separation is the brief's modularity requirement: the alpha module must not
know how orders are executed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Signal(ABC):
    name: str = "signal"

    @abstractmethod
    def scores(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Return a score panel (index=time, columns=symbols), values in [-1, 1].

        Must be causal: score at time t uses only prices up to and including t.
        """
        raise NotImplementedError
