from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd

from casino.data import funding_dumps
from casino.signals.carry import CarrySignal


def _prices_and_funding(cfg):
    idx = pd.date_range("2021-01-01", periods=1000, freq="1h", tz="UTC", name="ts")
    syms = cfg["data"]["universe"]
    prices = pd.DataFrame(
        {s: 100.0 * np.exp(np.cumsum(0.001 * np.random.default_rng(i).standard_normal(1000)))
         for i, s in enumerate(syms)},
        index=idx,
    )
    # Constant, distinct funding per symbol: first rich-positive, last negative.
    rates = np.linspace(0.0005, -0.0005, len(syms))
    funding = pd.DataFrame({s: rates[i] for i, s in enumerate(syms)}, index=idx)
    return prices, funding


def test_carry_direction_shorts_positive_funding(cfg):
    prices, funding = _prices_and_funding(cfg)
    sig = CarrySignal(funding, lookback_bars=24, funding_interval_bars=8,
                      market_neutral=False)
    scores = sig.scores(prices).dropna()
    syms = cfg["data"]["universe"]
    # Highest-funding symbol -> most negative (short); lowest -> most positive.
    last = scores.iloc[-1]
    assert last[syms[0]] < 0     # positive funding -> short
    assert last[syms[-1]] > 0    # negative funding -> long
    assert (scores.abs() <= 1.0 + 1e-9).all().all()


def test_market_neutral_scores_sum_to_zero(cfg):
    prices, funding = _prices_and_funding(cfg)
    sig = CarrySignal(funding, lookback_bars=24, funding_interval_bars=8,
                      market_neutral=True)
    scores = sig.scores(prices).dropna()
    # Dollar-neutral: cross-sectional sum ~ 0 every bar.
    assert scores.sum(axis=1).abs().max() < 1e-9


def test_carry_warmup_is_nan(cfg):
    prices, funding = _prices_and_funding(cfg)
    sig = CarrySignal(funding, lookback_bars=50, funding_interval_bars=8)
    scores = sig.scores(prices)
    assert scores.iloc[:49].isna().all().all()


def test_binance_symbol_mapping():
    assert funding_dumps.binance_symbol("BTC/USDT:USDT") == "BTCUSDT"
    assert funding_dumps.binance_symbol("SOL/USDT:USDT") == "SOLUSDT"


def test_months_range_inclusive():
    months = funding_dumps._months("2021-11-01T00:00:00Z", "2022-02-15T00:00:00Z")
    assert months == ["2021-11", "2021-12", "2022-01", "2022-02"]


def test_parse_zip_roundtrips_funding():
    # Build an in-memory Binance-format funding zip (no network).
    csv = ("calc_time,funding_interval_hours,last_funding_rate\n"
           "1672531200000,8,0.0001\n1672560000000,8,-0.0002\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BTCUSDT-fundingRate-2023-01.csv", csv)
    df = funding_dumps._parse_zip(buf.getvalue())
    assert list(df.columns) == ["funding_rate"]
    assert len(df) == 2
    assert df["funding_rate"].iloc[0] == 0.0001
    assert df.index[0] == pd.Timestamp("2023-01-01 00:00:00", tz="UTC")
