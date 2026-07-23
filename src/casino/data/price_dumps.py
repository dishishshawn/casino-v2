"""Multi-year OHLCV history for genuinely delisted perps, from Binance's public
data dumps.

A delisted ticker (e.g. FTT after the Nov-2022 FTX collapse) is no longer in
any venue's live market list, so ccxt can't resolve it via the trading API at
all -- `exchange.load_markets()` simply won't contain it. Binance's public
klines dumps at data.binance.vision are a static per-month archive keyed by
symbol string, not by "is this market currently open", so history for a
delisted ticker is usually still there. Same domain/mechanism as
funding_dumps.py, just the klines endpoint instead of fundingRate.

File layout (USDT-margined perp futures):
    https://data.binance.vision/data/futures/um/monthly/klines/
        {SYMBOL}/{interval}/{SYMBOL}-{interval}-{YYYY-MM}.zip
each containing one CSV (older dumps: no header; newer dumps: header row) with
columns open_time,open,high,low,close,volume,close_time,quote_volume,count,
taker_buy_volume,taker_buy_quote_volume,ignore.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd

from casino.data.funding_dumps import DUMP_VENUE, _download, _months, binance_symbol

__all__ = ["DUMP_VENUE", "binance_symbol", "fetch_ohlcv_history"]

BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"

_RAW_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


def _parse_zip(raw: bytes) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(raw))
    df = pd.read_csv(z.open(z.namelist()[0]), header=None, names=_RAW_COLUMNS)
    # Newer dumps ship a text header row in the data itself; drop it (and any
    # other unparseable row) by requiring a numeric open_time.
    open_time = pd.to_numeric(df["open_time"], errors="coerce")
    df = df.loc[open_time.notna()]
    out = df[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    out["ts"] = pd.to_datetime(pd.to_numeric(df["open_time"]), unit="ms", utc=True)
    out = out.dropna(subset=["ts"]).set_index("ts").sort_index()
    return out[["open", "high", "low", "close", "volume"]]


def _empty() -> pd.DataFrame:
    idx = pd.DatetimeIndex([], tz="UTC", name="ts")
    return pd.DataFrame(
        {c: pd.Series(dtype="float64") for c in ["open", "high", "low", "close", "volume"]},
        index=idx,
    )


def fetch_ohlcv_history(
    ccxt_symbol: str, timeframe: str, start: str, end: str | None = None
) -> pd.DataFrame:
    """Download and concatenate all monthly klines dumps for one symbol.

    `end` both bounds which monthly archives are requested and trims the final
    frame, so callers can cap a ticker whose meaning changed after a given date
    (e.g. LUNA reassigned to the unrelated Terra 2.0 token post-collapse).
    """
    sym = binance_symbol(ccxt_symbol)
    frames: list[pd.DataFrame] = []
    for ym in _months(start, end):
        raw = _download(f"{BASE_URL}/{sym}/{timeframe}/{sym}-{timeframe}-{ym}.zip")
        if raw is None:
            continue
        try:
            frames.append(_parse_zip(raw))
        except Exception:
            continue
    if not frames:
        return _empty()
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if end:
        df = df[df.index < pd.Timestamp(end)]
    return df
