"""Risk kill-switch: halts new orders when a hard risk limit is breached.

Deliberately narrow: it decides whether to stop TRADING, it does not itself
flatten positions -- doing that safely is a venue-specific, logged operator
or adapter action that belongs with the real broker integration, not here.
This is the one item from ROADMAP.md's "deferred (later phases)" list that is
pure risk logic with no venue dependency, so it can be built and tested now.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KillSwitchConfig:
    max_drawdown: float = 0.25  # halt if equity falls this far from its peak
    max_stale_bars: int = 3     # halt if the data feed stops advancing


class KillSwitch:
    def __init__(self, cfg: KillSwitchConfig):
        self.cfg = cfg
        self.peak_equity: float | None = None
        self.stale_count = 0
        self._last_bar_ts = None

    def observe_bar(self, bar_ts) -> None:
        if bar_ts == self._last_bar_ts:
            self.stale_count += 1
        else:
            self.stale_count = 0
            self._last_bar_ts = bar_ts

    def should_halt(self, equity: float, bar_ts=None) -> tuple[bool, str | None]:
        if bar_ts is not None:
            self.observe_bar(bar_ts)
        self.peak_equity = equity if self.peak_equity is None else max(self.peak_equity, equity)
        if self.peak_equity > 0:
            dd = 1.0 - equity / self.peak_equity
            if dd >= self.cfg.max_drawdown:
                return True, f"drawdown {dd:.1%} >= limit {self.cfg.max_drawdown:.1%}"
        if self.stale_count >= self.cfg.max_stale_bars:
            return True, f"data feed stale for {self.stale_count} bars"
        return False, None
