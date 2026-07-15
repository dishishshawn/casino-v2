"""Parquet cache for OHLCV and funding data.

Point-in-time guarantee: we only ever store fully-closed bars and never mutate
history, so the same (config, cache) reproduces the same backtest.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from casino.config import REPO_ROOT


def _safe_symbol(symbol: str) -> str:
    """Turn a ccxt symbol like 'BTC/USDT:USDT' into a filesystem-safe stem."""
    return symbol.replace("/", "_").replace(":", "-")


def cache_root(cache_dir: str) -> Path:
    root = Path(cache_dir)
    if not root.is_absolute():
        root = REPO_ROOT / root
    return root


def ohlcv_path(cache_dir: str, venue: str, symbol: str, timeframe: str) -> Path:
    return cache_root(cache_dir) / "ohlcv" / venue / timeframe / f"{_safe_symbol(symbol)}.parquet"


def funding_path(cache_dir: str, venue: str, symbol: str) -> Path:
    return cache_root(cache_dir) / "funding" / venue / f"{_safe_symbol(symbol)}.parquet"


def write_df(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, engine="pyarrow")


def read_df(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_parquet(path, engine="pyarrow")


def upsert_ohlcv(new: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Merge new bars with any cached bars, keeping a unique, sorted DatetimeIndex."""
    existing = read_df(path)
    if existing is not None and len(existing):
        combined = pd.concat([existing, new])
    else:
        combined = new
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    write_df(combined, path)
    return combined
