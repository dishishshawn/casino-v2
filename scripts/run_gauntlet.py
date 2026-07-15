"""Run the full staged validation gauntlet and print a GO / NO-GO verdict.

Usage:
    python scripts/run_gauntlet.py [--config config/default.yaml]
                                   [--synthetic] [--synthetic-bars 8000]

The verdict is the ONLY deliverable of this build: it decides whether the edge is
worth advancing to paper trading. No capital is deployed.
"""

from __future__ import annotations

import argparse
import warnings

from casino.config import config_hash, load_config
from casino.data import synthetic, universe
from casino.validation import gauntlet


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--synthetic-bars", type=int, default=8000)
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.synthetic:
        synthetic.write_synthetic_cache(cfg, n_bars=args.synthetic_bars)
        print("[synthetic data mode — offline pipeline exercise, not a real edge]")
    else:
        w = universe.survivorship_warning(cfg)
        if w:
            warnings.warn(w, stacklevel=1)

    prices = universe.load_price_panel(cfg)
    funding = universe.load_funding_panel(cfg)
    funding = funding if len(funding) else None

    print(f"config {config_hash(cfg)}: {prices.shape[1]} symbols, {prices.shape[0]} bars")
    report = gauntlet.run_gauntlet(prices, funding, cfg)
    print(report.format())


if __name__ == "__main__":
    main()
