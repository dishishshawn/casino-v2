"""Offline replay of the paper-trading decision loop against cached (or
synthetic) data. No network, no keys, no real venue connection -- see
EXECUTION.md. This exercises signal -> target weights -> order diffing ->
kill-switch -> simulated fills end to end; it does not change the gauntlet's
GO/NO-GO verdict or place any real order.

Usage:
    python scripts/run_paper.py [--config config/default.yaml]
                                [--synthetic] [--synthetic-bars 4000]
"""

from __future__ import annotations

import argparse
import warnings

from casino.config import config_hash, load_config
from casino.costs.model import from_config as cost_from_config
from casino.data import synthetic, universe
from casino.execution.killswitch import KillSwitch, KillSwitchConfig
from casino.execution.loop import run_replay
from casino.execution.paper_broker import PaperBroker


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--synthetic-bars", type=int, default=4000)
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.synthetic:
        synthetic.write_synthetic_cache(cfg, n_bars=args.synthetic_bars)
        print("[synthetic data mode -- offline pipeline exercise, not a real edge]")
    else:
        w = universe.survivorship_warning(cfg)
        if w:
            warnings.warn(w, stacklevel=1)

    prices = universe.load_price_panel(cfg)
    funding = universe.load_funding_panel(cfg)
    funding = funding if len(funding) else None

    ks_cfg = cfg.get("execution", {}).get("killswitch", {})
    killswitch = KillSwitch(
        KillSwitchConfig(
            max_drawdown=float(ks_cfg.get("max_drawdown", 0.25)),
            max_stale_bars=int(ks_cfg.get("max_stale_bars", 3)),
        )
    )
    broker = PaperBroker(cost_from_config(cfg), init_cash=float(cfg["backtest"]["init_cash"]))

    print(f"config {config_hash(cfg)}: paper replay, {prices.shape[1]} symbols, {prices.shape[0]} bars")
    results = run_replay(prices, funding, cfg, broker, killswitch)

    n_orders = sum(len(r.orders) for r in results)
    halts = [r for r in results if r.halted]
    print(f"ticks: {len(results)}  orders placed: {n_orders}  fills: {len(broker.fills)}")
    if halts:
        print(f"KILL-SWITCH halted at {halts[0].ts}: {halts[0].halt_reason}")
    final_equity = results[-1].equity if results else float(cfg["backtest"]["init_cash"])
    print(f"final positions: {broker.get_positions()}")
    print(f"final equity: {final_equity:,.2f}")


if __name__ == "__main__":
    main()
