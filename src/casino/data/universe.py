"""Universe assembly and the panel of aligned prices used by the backtest.

SURVIVORSHIP BIAS WARNING: ccxt lists only currently-live perps. A universe built
purely from live symbols excludes coins that delisted/collapsed, which biases
crypto-momentum backtests UPWARD (the design brief flags this as the single most
common way crypto momentum misleads). `config.data.delisted_symbols` lets you feed
an external delisted list; until that is populated, results carry this bias and the
reports say so loudly.
"""

from __future__ import annotations

import warnings

import pandas as pd

from casino.data import ingest, storage


def survivorship_warning(cfg: dict) -> str | None:
    """Return a warning string if the universe has no delisted symbols wired in."""
    delisted = cfg["data"].get("delisted_symbols") or []
    if not delisted:
        return (
            "SURVIVORSHIP BIAS: universe contains only currently-live perps and no "
            "delisted symbols. Crypto-momentum results are biased UPWARD. Populate "
            "config.data.delisted_symbols to mitigate."
        )
    return None


def ingest_universe(cfg: dict) -> dict[str, str]:
    """Ingest every symbol, trying venues in order until one has the data.

    Returns a mapping symbol -> venue that actually served it.
    """
    d = cfg["data"]
    symbols = list(d["universe"]) + list(d.get("delisted_symbols") or [])
    served: dict[str, str] = {}
    for symbol in symbols:
        for venue in d["venues"]:
            try:
                df = ingest.ingest_symbol(
                    venue, symbol, d["timeframe"], d["start"], d["end"], d["cache_dir"]
                )
                if df is not None and len(df):
                    served[symbol] = venue
                    break
            except Exception as exc:  # noqa: BLE001 - venue fallback is intentional
                warnings.warn(f"{venue} failed for {symbol}: {exc}", stacklevel=2)
                continue
    return served


def load_price_panel(cfg: dict, field: str = "close") -> pd.DataFrame:
    """Load a wide DataFrame (index=time, columns=symbols) of one OHLCV field.

    Only reads the cache — call ingest_universe first (or scripts/fetch_data.py).
    """
    d = cfg["data"]
    symbols = list(d["universe"]) + list(d.get("delisted_symbols") or [])
    # "synthetic" is searched last so real cached data always wins when present.
    read_venues = list(d["venues"]) + ["synthetic"]
    cols: dict[str, pd.Series] = {}
    for symbol in symbols:
        for venue in read_venues:
            path = storage.ohlcv_path(d["cache_dir"], venue, symbol, d["timeframe"])
            df = storage.read_df(path)
            if df is not None and len(df):
                cols[symbol] = df[field].rename(symbol)
                break
    if not cols:
        raise FileNotFoundError(
            "No cached OHLCV found. Run scripts/fetch_data.py first."
        )
    panel = pd.concat(cols.values(), axis=1).sort_index()
    return panel


def load_funding_panel(cfg: dict) -> pd.DataFrame:
    """Wide funding-rate panel aligned to symbols (may be empty for some venues)."""
    d = cfg["data"]
    symbols = list(d["universe"]) + list(d.get("delisted_symbols") or [])
    cols: dict[str, pd.Series] = {}
    for symbol in symbols:
        for venue in d["venues"]:
            path = storage.funding_path(d["cache_dir"], venue, symbol)
            df = storage.read_df(path)
            if df is not None and len(df):
                cols[symbol] = df["funding_rate"].rename(symbol)
                break
    if not cols:
        return pd.DataFrame()
    return pd.concat(cols.values(), axis=1).sort_index()
