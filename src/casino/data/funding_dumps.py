"""Multi-year funding-rate history from Binance's public data dumps.

Exchange *live* funding-rate endpoints are capped at recent history (OKX ~3
months, most venues ~1 month), which makes a real 2021->present carry backtest
impossible from ccxt alone. Binance publishes full monthly funding history as
public, no-API-key CSV zips at data.binance.vision — and crucially that CDN is a
SEPARATE domain from the geo-blocked Binance API, so it is reachable where the
trading API returns 451.

File layout (USDT-margined perps):
    https://data.binance.vision/data/futures/um/monthly/fundingRate/
        {SYMBOL}/{SYMBOL}-fundingRate-{YYYY-MM}.zip
each containing one CSV with columns: calc_time (ms), funding_interval_hours,
last_funding_rate.

We normalize to the same shape as ingest.fetch_funding (index=ts UTC named 'ts',
one column 'funding_rate') and cache under a sentinel venue 'binancevision' so
universe.load_funding_panel picks it up alongside real OHLCV.
"""

from __future__ import annotations

import io
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone

import pandas as pd

from casino.data import storage

BASE_URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
_UA = {"User-Agent": "Mozilla/5.0"}
DUMP_VENUE = "binancevision"


def binance_symbol(ccxt_symbol: str) -> str:
    """'BTC/USDT:USDT' -> 'BTCUSDT' (USDT-margined perp dump naming)."""
    base = ccxt_symbol.split("/")[0]
    return f"{base}USDT"


def _months(start: str, end: str | None) -> list[str]:
    """Inclusive list of 'YYYY-MM' strings from start to end (or now)."""
    s = datetime.fromisoformat(start.replace("Z", "+00:00"))
    e = (
        datetime.fromisoformat(end.replace("Z", "+00:00"))
        if end
        else datetime.now(timezone.utc)
    )
    out, y, m = [], s.year, s.month
    while (y, m) <= (e.year, e.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _download(url: str, max_retries: int = 3) -> bytes | None:
    """GET bytes; None on 404 (month before listing), retry transient errors."""
    delay = 1.5
    for _ in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None  # symbol not listed that month — expected, skip
            time.sleep(delay)
            delay *= 2
        except Exception:
            time.sleep(delay)
            delay *= 2
    return None


def _parse_zip(raw: bytes) -> pd.DataFrame:
    """Parse a monthly funding zip into (ts, funding_rate). Empty on any issue."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    df = pd.read_csv(z.open(z.namelist()[0]))
    if "calc_time" not in df or "last_funding_rate" not in df:
        return _empty()
    out = pd.DataFrame(
        {"funding_rate": pd.to_numeric(df["last_funding_rate"], errors="coerce")}
    )
    out["ts"] = pd.to_datetime(
        pd.to_numeric(df["calc_time"], errors="coerce"), unit="ms", utc=True
    )
    out = out.dropna(subset=["ts"]).set_index("ts")
    return out[["funding_rate"]]


def _empty() -> pd.DataFrame:
    idx = pd.DatetimeIndex([], tz="UTC", name="ts")
    return pd.DataFrame({"funding_rate": pd.Series(dtype="float64")}, index=idx)


def fetch_funding_history(ccxt_symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
    """Download and concatenate all monthly funding dumps for one symbol."""
    sym = binance_symbol(ccxt_symbol)
    frames: list[pd.DataFrame] = []
    for ym in _months(start, end):
        raw = _download(f"{BASE_URL}/{sym}/{sym}-fundingRate-{ym}.zip")
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
    return df


def ingest_funding_dumps(cfg: dict) -> dict[str, int]:
    """Fetch full funding history for the configured universe into the cache.

    Returns {symbol: n_rows}. Cached under venue 'binancevision'.
    """
    d = cfg["data"]
    symbols = list(d["universe"]) + list(d.get("delisted_symbols") or [])
    counts: dict[str, int] = {}
    for symbol in symbols:
        df = fetch_funding_history(symbol, d["start"], d["end"])
        if len(df):
            storage.write_df(df, storage.funding_path(d["cache_dir"], DUMP_VENUE, symbol))
        counts[symbol] = len(df)
    return counts
