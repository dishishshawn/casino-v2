"""Performance metrics, including the skew/kurtosis the Deflated Sharpe needs.

The brief's discipline: report a raw Sharpe AND a ~50%-haircut "believed" Sharpe,
because published/backtested edges decay (McLean & Pontiff) and in-sample Sharpes
are inflated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class Metrics:
    n_bars: int
    ann_return: float
    ann_vol: float
    sharpe: float
    sharpe_haircut: float
    max_drawdown: float
    calmar: float
    hit_rate: float
    avg_turnover: float
    trade_cost_drag_ann: float
    funding_drag_ann: float
    skew: float
    kurtosis: float  # excess kurtosis

    def as_dict(self) -> dict:
        return asdict(self)


def sharpe_ratio(returns: pd.Series, bars_per_year: int) -> float:
    r = returns.dropna()
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(bars_per_year))


def max_drawdown(equity: pd.Series) -> float:
    eq = equity.dropna()
    if eq.empty:
        return 0.0
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min())


def compute(result, cfg: dict) -> Metrics:
    bpy = int(cfg["risk"]["bars_per_year"])
    haircut = float(cfg["backtest"]["sharpe_haircut"])
    net = result.net_returns.dropna()

    ann_return = float((1.0 + net).prod() ** (bpy / max(len(net), 1)) - 1.0) if len(net) else 0.0
    ann_vol = float(net.std(ddof=1) * np.sqrt(bpy)) if len(net) > 1 else 0.0
    sr = sharpe_ratio(net, bpy)
    mdd = max_drawdown(result.equity)
    calmar = float(ann_return / abs(mdd)) if mdd < 0 else 0.0
    hit = float((net > 0).mean()) if len(net) else 0.0

    return Metrics(
        n_bars=int(len(net)),
        ann_return=ann_return,
        ann_vol=ann_vol,
        sharpe=sr,
        sharpe_haircut=sr * haircut,
        max_drawdown=mdd,
        calmar=calmar,
        hit_rate=hit,
        avg_turnover=float(result.turnover.mean()) if len(result.turnover) else 0.0,
        trade_cost_drag_ann=float(result.trade_costs.mean() * bpy),
        funding_drag_ann=float(result.funding_costs.mean() * bpy),
        skew=float(stats.skew(net)) if len(net) > 2 else 0.0,
        kurtosis=float(stats.kurtosis(net)) if len(net) > 3 else 0.0,
    )


def format_report(m: Metrics) -> str:
    lines = [
        f"  bars                 : {m.n_bars}",
        f"  annual return        : {m.ann_return:+.2%}",
        f"  annual vol           : {m.ann_vol:.2%}",
        f"  Sharpe (raw)         : {m.sharpe:+.3f}",
        f"  Sharpe (50% haircut) : {m.sharpe_haircut:+.3f}   <- believe this one",
        f"  max drawdown         : {m.max_drawdown:.2%}",
        f"  Calmar               : {m.calmar:.2f}",
        f"  hit rate (bars)      : {m.hit_rate:.2%}",
        f"  avg turnover/bar     : {m.avg_turnover:.3f}",
        f"  trade-cost drag/yr   : {m.trade_cost_drag_ann:.2%}",
        f"  funding drag/yr      : {m.funding_drag_ann:+.2%}",
        f"  skew / excess-kurt   : {m.skew:+.2f} / {m.kurtosis:+.2f}",
    ]
    return "\n".join(lines)
