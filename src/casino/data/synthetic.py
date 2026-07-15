"""Synthetic OHLCV generator for offline development and controlled tests.

Two uses:
  1. Exercise the full pipeline without exchange network access (this session's
     egress policy blocks Binance/Bybit/OKX; live fetch requires an environment
     where those domains are allowlisted).
  2. Controlled validation: generate price paths with a KNOWN trend component so we
     can confirm the TSMOM signal captures real momentum and that shuffling the
     signal destroys the edge (a leakage/robustness sanity check).

Model: per-asset log-price is a regime-switching drift (persistent trends) plus
GBM noise plus a shared market factor, so assets are cross-correlated like crypto.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from casino.data import storage


def generate_prices(
    symbols: list[str],
    n_bars: int,
    start: str = "2021-01-01",
    freq: str = "1h",
    seed: int = 7,
    trend_strength: float = 0.12,
    regime_switch_prob: float = 0.02,
    bar_vol: float = 0.012,
    market_beta: float = 0.5,
) -> dict[str, pd.DataFrame]:
    """Return {symbol: OHLCV DataFrame} with persistent trends + shared factor."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start=start, periods=n_bars, freq=freq, tz="UTC", name="ts")

    # Shared market factor with its own slow regime.
    mkt_regime = _regime_path(rng, n_bars, regime_switch_prob)
    mkt_ret = market_beta * (trend_strength * bar_vol * mkt_regime
                             + bar_vol * rng.standard_normal(n_bars))

    out: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols):
        a_rng = np.random.default_rng(seed + i + 1)
        regime = _regime_path(a_rng, n_bars, regime_switch_prob)
        idio = trend_strength * bar_vol * regime + bar_vol * a_rng.standard_normal(n_bars)
        ret = mkt_ret + idio
        close = 100.0 * np.exp(np.cumsum(ret))
        # Build plausible OHLC around close.
        open_ = np.empty_like(close)
        open_[0] = 100.0
        open_[1:] = close[:-1]
        hi_lo = np.abs(a_rng.standard_normal(n_bars)) * bar_vol * close
        high = np.maximum(open_, close) + hi_lo
        low = np.minimum(open_, close) - hi_lo
        volume = np.abs(a_rng.standard_normal(n_bars)) * 1000 + 100
        out[sym] = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=idx,
        )
    return out


def _regime_path(rng: np.random.Generator, n: int, switch_prob: float) -> np.ndarray:
    """+1/-1 regime that flips with probability `switch_prob` each bar (persistent)."""
    state = 1.0
    path = np.empty(n)
    for t in range(n):
        if rng.random() < switch_prob:
            state = -state
        path[t] = state
    return path


def write_synthetic_cache(cfg: dict, n_bars: int = 8000, seed: int = 7) -> list[str]:
    """Generate synthetic OHLCV for the configured universe and write it to cache.

    Uses a sentinel venue name 'synthetic' so it never collides with real data.
    """
    d = cfg["data"]
    symbols = list(d["universe"]) + list(d.get("delisted_symbols") or [])
    frames = generate_prices(symbols, n_bars=n_bars, start=d["start"][:10],
                             freq=d["timeframe"], seed=seed)
    for sym, df in frames.items():
        path = storage.ohlcv_path(d["cache_dir"], "synthetic", sym, d["timeframe"])
        storage.write_df(df, path)
    return symbols
