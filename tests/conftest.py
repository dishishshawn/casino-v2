from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from casino.config import load_config
from casino.data import synthetic


@pytest.fixture
def cfg():
    c = load_config()
    c["data"]["cache_dir"] = "data_cache_test"
    return c


@pytest.fixture
def prices(cfg):
    """Small synthetic price panel with strong, known momentum for tests."""
    frames = synthetic.generate_prices(
        cfg["data"]["universe"], n_bars=3000, seed=11,
        trend_strength=0.5, regime_switch_prob=0.004,
    )
    return pd.concat({s: f["close"] for s, f in frames.items()}, axis=1)


@pytest.fixture
def noise_prices(cfg):
    """Trendless (pure random-walk) prices: momentum should NOT profit here."""
    n = 3000
    idx = pd.date_range("2021-01-01", periods=n, freq="1h", tz="UTC")
    cols = {}
    for i, s in enumerate(cfg["data"]["universe"]):
        r = 0.01 * np.random.default_rng(i + 1).standard_normal(n)
        cols[s] = pd.Series(100 * np.exp(np.cumsum(r)), index=idx)
    return pd.DataFrame(cols)
