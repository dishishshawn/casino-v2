"""Populate the Parquet cache with OHLCV + funding for the configured universe.

Usage:
    python scripts/fetch_data.py [--config config/default.yaml]
                                 [--symbols BTC/USDT:USDT,ETH/USDT:USDT]
                                 [--start 2023-01-01T00:00:00Z]

Public market data only — no API keys required.
"""

from __future__ import annotations

import argparse
import warnings

from casino.config import load_config
from casino.data import universe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--symbols", default=None, help="comma-separated override of universe")
    ap.add_argument("--start", default=None, help="override start ISO timestamp")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.symbols:
        cfg["data"]["universe"] = [s.strip() for s in args.symbols.split(",")]
    if args.start:
        cfg["data"]["start"] = args.start

    warn = universe.survivorship_warning(cfg)
    if warn:
        warnings.warn(warn, stacklevel=1)

    print(f"Ingesting {len(cfg['data']['universe'])} symbols "
          f"(timeframe={cfg['data']['timeframe']}, start={cfg['data']['start']}) ...")
    served = universe.ingest_universe(cfg)
    for sym, venue in served.items():
        print(f"  OK  {sym:24s} <- {venue}")
    missing = set(cfg["data"]["universe"]) - set(served)
    for sym in missing:
        print(f"  MISS {sym}")
    print(f"Done: {len(served)}/{len(cfg['data']['universe'])} served.")


if __name__ == "__main__":
    main()
