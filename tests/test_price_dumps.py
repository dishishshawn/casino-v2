from __future__ import annotations

import io
import shutil
import zipfile

import pandas as pd

from casino.data import ingest, price_dumps, storage, universe


def _headerless_csv() -> str:
    # open_time,open,high,low,close,volume,close_time,quote_volume,count,
    # taker_buy_volume,taker_buy_quote_volume,ignore
    return (
        "1672531200000,1.0,1.2,0.9,1.1,100,1672534799999,110,10,50,55,0\n"
        "1672534800000,1.1,1.3,1.0,1.2,120,1672538399999,140,12,60,66,0\n"
    )


def _headered_csv() -> str:
    header = (
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
        "taker_buy_volume,taker_buy_quote_volume,ignore\n"
    )
    return header + _headerless_csv()


def _zip_bytes(csv_text: str, name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, csv_text)
    return buf.getvalue()


def test_parse_zip_headerless():
    df = price_dumps._parse_zip(_zip_bytes(_headerless_csv(), "FTTUSDT-1h-2023-01.csv"))
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["close"].iloc[0] == 1.1
    assert df.index[0] == pd.Timestamp("2023-01-01 00:00:00", tz="UTC")


def test_parse_zip_with_header_row():
    df = price_dumps._parse_zip(_zip_bytes(_headered_csv(), "FTTUSDT-1h-2023-01.csv"))
    assert len(df) == 2
    assert df["close"].iloc[0] == 1.1


def test_fetch_ohlcv_history_concatenates_and_caps_end(monkeypatch):
    # CSV bars are at 2023-01-01 00:00 and 01:00 (see _headerless_csv epochs).
    zips = {
        "2023-01": _zip_bytes(_headerless_csv(), "x.csv"),
    }

    def fake_download(url: str, max_retries: int = 3):
        for ym, blob in zips.items():
            if ym in url:
                return blob
        return None

    monkeypatch.setattr(price_dumps, "_download", fake_download)
    df = price_dumps.fetch_ohlcv_history(
        "FTT/USDT:USDT", "1h", "2023-01-01T00:00:00Z", "2023-01-01T00:30:00Z"
    )
    # Only the first bar (00:00) is strictly before the 00:30 cap.
    assert len(df) == 1
    assert df.index[0] == pd.Timestamp("2023-01-01 00:00:00", tz="UTC")


def test_ingest_universe_falls_back_to_price_dumps_for_delisted(monkeypatch, cfg):
    cfg["data"]["cache_dir"] = "data_cache_unit_delisted"
    cfg["data"]["universe"] = ["BTC/USDT:USDT"]
    cfg["data"]["delisted_symbols"] = ["FTT/USDT:USDT"]
    cfg["data"]["venues"] = ["okx"]

    def fake_ingest_symbol(venue, symbol, timeframe, start, end, cache_dir):
        raise RuntimeError("not in exchange.markets")

    idx = pd.date_range("2021-01-01", periods=3, freq="1h", tz="UTC", name="ts")
    canned = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx
    )

    def fake_fetch_ohlcv_history(symbol, timeframe, start, end):
        return canned

    monkeypatch.setattr(ingest, "ingest_symbol", fake_ingest_symbol)
    monkeypatch.setattr(price_dumps, "fetch_ohlcv_history", fake_fetch_ohlcv_history)
    try:
        served = universe.ingest_universe(cfg)
        assert served == {"FTT/USDT:USDT": price_dumps.DUMP_VENUE}
        path = storage.ohlcv_path(
            cfg["data"]["cache_dir"], price_dumps.DUMP_VENUE, "FTT/USDT:USDT", "1h"
        )
        assert storage.read_df(path) is not None
    finally:
        shutil.rmtree("data_cache_unit_delisted", ignore_errors=True)
