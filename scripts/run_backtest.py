"""Run a single cost-aware TSMOM backtest and emit metrics + an equity plot.

Usage:
    python scripts/run_backtest.py [--config config/default.yaml]
                                   [--synthetic] [--no-costs] [--out reports/]

--synthetic generates offline data (use when exchange egress is blocked).
--no-costs runs with a zero cost model (sanity check: costs must bite).
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from casino.backtest import engine, metrics  # noqa: E402
from casino.config import REPO_ROOT, config_hash, load_config  # noqa: E402
from casino.costs.model import CostModel  # noqa: E402
from casino.costs.model import from_config as cost_from_config  # noqa: E402
from casino.data import synthetic, universe  # noqa: E402
from casino.risk import sizing  # noqa: E402
from casino.signals import tsmom  # noqa: E402


def build_book(cfg: dict):
    prices = universe.load_price_panel(cfg)
    funding = universe.load_funding_panel(cfg)
    funding = funding if len(funding) else None
    scores = tsmom.from_config(cfg).scores(prices)
    weights = sizing.size(scores, prices, cfg)
    return prices, weights, funding


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--no-costs", action="store_true")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--synthetic-bars", type=int, default=8000)
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.synthetic:
        synthetic.write_synthetic_cache(cfg, n_bars=args.synthetic_bars)
    else:
        w = universe.survivorship_warning(cfg)
        if w:
            warnings.warn(w, stacklevel=1)

    prices, weights, funding = build_book(cfg)
    cost_model = CostModel(0, 0, 0, 0, cfg["costs"]["funding_interval_hours"], 0.0) \
        if args.no_costs else cost_from_config(cfg)

    result = engine.run_backtest(prices, weights, cost_model, cfg, funding)
    m = metrics.compute(result, cfg)

    print(f"\n=== TSMOM backtest (config {config_hash(cfg)}"
          f"{', NO COSTS' if args.no_costs else ''}) ===")
    print(metrics.format_report(m))

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
    result.equity.plot(ax=ax1, color="#1f77b4")
    ax1.set_title(f"TSMOM equity (Sharpe {m.sharpe:+.2f}, haircut {m.sharpe_haircut:+.2f}, "
                  f"maxDD {m.max_drawdown:.1%})")
    ax1.set_ylabel("equity")
    ax1.grid(alpha=0.3)
    result.weights.abs().sum(axis=1).plot(ax=ax2, color="#666")
    ax2.set_ylabel("gross lev")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    plot_path = out_dir / f"equity_{config_hash(cfg)}.png"
    fig.savefig(plot_path, dpi=110)
    print(f"\nplot -> {plot_path}")


if __name__ == "__main__":
    main()
