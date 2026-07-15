from __future__ import annotations

import shutil

import pandas as pd

from casino.data import storage, synthetic, universe


def test_storage_roundtrip(tmp_path):
    df = pd.DataFrame(
        {"open": [1.0, 2.0], "close": [1.5, 2.5]},
        index=pd.date_range("2021-01-01", periods=2, freq="1h", tz="UTC", name="ts"),
    )
    path = tmp_path / "x.parquet"
    storage.write_df(df, path)
    back = storage.read_df(path)
    # Parquet does not persist the DatetimeIndex freq attribute; ignore it.
    pd.testing.assert_frame_equal(df, back, check_freq=False)


def test_upsert_dedupes_and_sorts(tmp_path):
    idx = pd.date_range("2021-01-01", periods=3, freq="1h", tz="UTC", name="ts")
    a = pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=idx)
    path = tmp_path / "o.parquet"
    storage.upsert_ohlcv(a, path)
    # Overlapping new batch: last value wins, index stays unique & sorted.
    b = pd.DataFrame({"close": [9.0, 4.0]}, index=idx[-1:].append(
        pd.date_range("2021-01-01 03:00", periods=1, freq="1h", tz="UTC", name="ts")))
    merged = storage.upsert_ohlcv(b, path)
    assert merged.index.is_monotonic_increasing
    assert merged.index.is_unique
    assert merged.loc[idx[-1], "close"] == 9.0


def test_synthetic_panel_load(cfg):
    cfg["data"]["cache_dir"] = "data_cache_unit"
    try:
        synthetic.write_synthetic_cache(cfg, n_bars=500, seed=1)
        panel = universe.load_price_panel(cfg)
        assert panel.shape == (500, len(cfg["data"]["universe"]))
        assert (panel > 0).all().all()
    finally:
        shutil.rmtree("data_cache_unit", ignore_errors=True)


def test_survivorship_warning_fires_without_delisted(cfg):
    cfg["data"]["delisted_symbols"] = []
    assert universe.survivorship_warning(cfg) is not None
    cfg["data"]["delisted_symbols"] = ["DEAD/USDT:USDT"]
    assert universe.survivorship_warning(cfg) is None
