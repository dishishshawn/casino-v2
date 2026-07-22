"""Deribit DVOL (implied-volatility index) history — free, no API key.

DVOL is Deribit's 30-day forward implied-vol index for BTC and ETH (annualized
%). It is the cleanest reachable forward-looking vol series: exchange funding and
OHLCV are backward-looking, so DVOL is the only way to measure the *variance risk
premium* (implied minus realized vol) without a paid options feed.

The public endpoint `get_volatility_index_data` returns [ts, open, high, low,
close] and caps at ~1000 points/call, so we paginate backward. BTC/ETH DVOL both
begin 2021-03-24 (index launch) — enough to cover the 2022 bear, 2023-24 recovery
and 2025 chop, plus most of the 2021 bull.

Reachable even where the Binance/Bybit trading APIs are geo-blocked.
"""

from __future__ import annotations

import json
import urllib.request

import pandas as pd

from casino.data import storage

API = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
_UA = {"User-Agent": "Mozilla/5.0"}
DVOL_VENUE = "deribit_dvol"
_RES_SECONDS = 43_200  # 12h bars


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fetch_dvol(currency: str, end_ms: int = 1_780_000_000_000, max_pages: int = 16) -> pd.Series:
    """Paginate DVOL close history backward from `end_ms`. Returns annualized vol (fraction)."""
    step = 1000 * _RES_SECONDS * 1000
    rows: list[list[float]] = []
    end = end_ms
    for _ in range(max_pages):
        start = end - step
        url = (
            f"{API}?currency={currency}&start_timestamp={start}"
            f"&end_timestamp={end}&resolution={_RES_SECONDS}"
        )
        data = _get(url).get("result", {}).get("data", [])
        if not data:
            break
        rows = data + rows
        end = data[0][0] - 1
        if len(data) < 1000:
            break
    if not rows:
        return pd.Series(dtype="float64")
    idx = pd.DatetimeIndex([pd.Timestamp(r[0], unit="ms", tz="UTC") for r in rows], name="ts")
    # column 4 = close DVOL in percent -> fraction
    s = pd.Series([r[4] / 100.0 for r in rows], index=idx, name="dvol")
    return s[~s.index.duplicated(keep="last")].sort_index()


def ingest_dvol(cfg: dict, currencies: tuple[str, ...] = ("BTC", "ETH")) -> dict[str, int]:
    """Fetch DVOL for the given currencies into the cache (venue 'deribit_dvol')."""
    counts: dict[str, int] = {}
    for cur in currencies:
        s = fetch_dvol(cur)
        if len(s):
            df = s.to_frame("dvol")
            storage.write_df(df, _dvol_path(cfg, cur))
        counts[cur] = len(s)
    return counts


def _dvol_path(cfg: dict, currency: str):
    # Reuse the funding path layout under a dedicated venue for a DVOL series.
    return storage.funding_path(cfg["data"]["cache_dir"], DVOL_VENUE, f"{currency}/USDT:USDT")


def load_dvol(cfg: dict, currency: str = "BTC") -> pd.Series:
    """Load a cached DVOL series (annualized vol fraction), or empty if absent."""
    df = storage.read_df(_dvol_path(cfg, currency))
    if df is None or not len(df):
        return pd.Series(dtype="float64")
    return df["dvol"]
