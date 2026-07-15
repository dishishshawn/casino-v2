"""Fetch perp OHLCV + funding via ccxt into the Parquet cache.

Public market data only — no API keys. Fetches are incremental (resume from the
last cached bar) and paginate through ccxt's per-call limits. Network calls go
through the environment's HTTPS proxy automatically.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import ccxt
import pandas as pd

from casino.data import storage

_TF_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def make_exchange(venue: str) -> ccxt.Exchange:
    cls = getattr(ccxt, venue)
    ex = cls({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    return ex


def _to_ms(ts: str | int | None) -> int | None:
    if ts is None:
        return None
    if isinstance(ts, int):
        return ts
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def fetch_ohlcv(
    ex: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since_ms: int,
    end_ms: int | None = None,
    limit: int = 1000,
    max_retries: int = 4,
) -> pd.DataFrame:
    """Paginate OHLCV from `since_ms` up to `end_ms` (or now)."""
    tf_ms = _TF_MS[timeframe]
    end_ms = end_ms or int(time.time() * 1000)
    rows: list[list[float]] = []
    cursor = since_ms
    while cursor < end_ms:
        batch = _with_retries(
            lambda c=cursor: ex.fetch_ohlcv(symbol, timeframe, since=c, limit=limit),
            max_retries,
        )
        if not batch:
            break
        rows.extend(batch)
        last = batch[-1][0]
        if last <= cursor:  # no forward progress -> stop
            break
        cursor = last + tf_ms
        if len(batch) < limit:
            break
    if not rows:
        return _empty_ohlcv()
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df[df["ts"] < end_ms]
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    # Drop the last bar if it is still forming (within one timeframe of now).
    now_ms = int(time.time() * 1000)
    if len(df) and (df.index[-1].value // 1_000_000) > now_ms - tf_ms:
        df = df.iloc[:-1]
    return df


def fetch_funding(
    ex: ccxt.Exchange,
    symbol: str,
    since_ms: int,
    end_ms: int | None = None,
    max_retries: int = 4,
) -> pd.DataFrame:
    """Fetch historical funding rates if the venue supports it; else empty frame."""
    if not ex.has.get("fetchFundingRateHistory"):
        return _empty_funding()
    end_ms = end_ms or int(time.time() * 1000)
    rows: list[dict] = []
    cursor = since_ms
    while cursor < end_ms:
        batch = _with_retries(
            lambda c=cursor: ex.fetch_funding_rate_history(symbol, since=c, limit=1000),
            max_retries,
        )
        if not batch:
            break
        rows.extend(batch)
        last = batch[-1]["timestamp"]
        if last <= cursor:
            break
        cursor = last + 1
        if len(batch) < 1000:
            break
    if not rows:
        return _empty_funding()
    df = pd.DataFrame(
        [{"ts": r["timestamp"], "funding_rate": r["fundingRate"]} for r in rows]
    )
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _with_retries(fn, max_retries: int):
    delay = 2.0
    last_exc: Exception | None = None
    for _ in range(max_retries):
        try:
            return fn()
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
            last_exc = exc
            time.sleep(delay)
            delay *= 2
    if last_exc:
        raise last_exc
    return None


def _empty_ohlcv() -> pd.DataFrame:
    idx = pd.DatetimeIndex([], tz="UTC", name="ts")
    return pd.DataFrame(
        {c: pd.Series(dtype="float64") for c in ["open", "high", "low", "close", "volume"]},
        index=idx,
    )


def _empty_funding() -> pd.DataFrame:
    idx = pd.DatetimeIndex([], tz="UTC", name="ts")
    return pd.DataFrame({"funding_rate": pd.Series(dtype="float64")}, index=idx)


def ingest_symbol(
    venue: str,
    symbol: str,
    timeframe: str,
    start: str | None,
    end: str | None,
    cache_dir: str,
) -> pd.DataFrame:
    """Fetch (incrementally) and cache OHLCV + funding for one symbol on one venue."""
    ex = make_exchange(venue)
    ex.load_markets()

    ohlcv_p = storage.ohlcv_path(cache_dir, venue, symbol, timeframe)
    existing = storage.read_df(ohlcv_p)
    tf_ms = _TF_MS[timeframe]
    if existing is not None and len(existing):
        since_ms = int(existing.index[-1].value // 1_000_000) + tf_ms
    else:
        since_ms = _to_ms(start) or _to_ms("2021-01-01T00:00:00Z")
    end_ms = _to_ms(end)

    new = fetch_ohlcv(ex, symbol, timeframe, since_ms, end_ms)
    merged = storage.upsert_ohlcv(new, ohlcv_p) if len(new) else (existing if existing is not None else new)

    funding = fetch_funding(ex, symbol, _to_ms(start) or since_ms, end_ms)
    if len(funding):
        storage.write_df(funding, storage.funding_path(cache_dir, venue, symbol))

    return merged


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
