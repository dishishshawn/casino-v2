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

from casino.data import ingest, price_dumps, storage


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

    Genuinely delisted symbols are usually gone from every venue's live market
    list, so ccxt can't resolve them at all -- for those (and only those), fall
    back to Binance's static klines archive (price_dumps) once the live venues
    are exhausted. `delisted_symbol_end` optionally caps how far a ticker's
    history is pulled, for tickers later reassigned to an unrelated asset.

    Returns a mapping symbol -> venue that actually served it.
    """
    d = cfg["data"]
    delisted = list(d.get("delisted_symbols") or [])
    symbols = list(d["universe"]) + delisted
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
        if symbol in served or symbol not in delisted:
            continue
        end = (d.get("delisted_symbol_end") or {}).get(symbol) or d["end"]
        df = price_dumps.fetch_ohlcv_history(symbol, d["timeframe"], d["start"], end)
        if len(df):
            path = storage.ohlcv_path(d["cache_dir"], price_dumps.DUMP_VENUE, symbol, d["timeframe"])
            storage.write_df(df, path)
            served[symbol] = price_dumps.DUMP_VENUE
    return served


def load_price_panel(cfg: dict, field: str = "close") -> pd.DataFrame:
    """Load a wide DataFrame (index=time, columns=symbols) of one OHLCV field.

    Only reads the cache — call ingest_universe first (or scripts/fetch_data.py).
    """
    d = cfg["data"]
    symbols = list(d["universe"]) + list(d.get("delisted_symbols") or [])
    # "synthetic" is searched last so real cached data always wins when present;
    # the dump archive is the only source for genuinely-delisted tickers.
    read_venues = list(d["venues"]) + [price_dumps.DUMP_VENUE, "synthetic"]
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
    # Prefer the multi-year Binance data-dump funding (venue 'binancevision') over
    # the shallow live-API funding, since carry needs deep history.
    read_venues = ["binancevision"] + list(d["venues"])
    cols: dict[str, pd.Series] = {}
    for symbol in symbols:
        for venue in read_venues:
            path = storage.funding_path(d["cache_dir"], venue, symbol)
            df = storage.read_df(path)
            if df is not None and len(df):
                cols[symbol] = df["funding_rate"].rename(symbol)
                break
    if not cols:
        return pd.DataFrame()
    return pd.concat(cols.values(), axis=1).sort_index()
