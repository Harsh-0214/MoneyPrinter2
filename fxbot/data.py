"""Loading, cleaning and resampling EUR/USD price data.

All prices are BID prices (what MT5 and Dukascopy export). The simulator
adds the spread on top to get ASK prices.
All timestamps are converted to UTC internally.
"""
import numpy as np
import pandas as pd

PIP = 0.0001            # EUR/USD pip size
POINTS_PER_PIP = 10     # MT5 quotes EUR/USD with 5 digits: 1 pip = 10 points


def _apply_ny7(naive_ts: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Convert FOREX.com server timestamps to UTC.

    Server time = New York local time + 7 hours (winter: UTC+2, summer: UTC+3).
    We subtract 7 h to recover naive NY local time, localize it as
    America/New_York (which knows the exact US DST switch dates), then
    convert to UTC.  Europe/Helsinki would be wrong in the ~2-week windows
    where US and European DST switch dates differ.
    """
    shifted = naive_ts - pd.Timedelta(hours=7)
    return shifted.tz_localize(
        "America/New_York", ambiguous="NaT", nonexistent="NaT"
    ).tz_convert("UTC")


def server_ts_to_utc(epoch_seconds) -> pd.DatetimeIndex:
    """Convert MT5 server-time epoch seconds to real UTC.

    MT5's copy_rates_* encodes bar timestamps as if the server clock were UTC,
    so a bar at server 10:00 (UTC+2 in winter) comes back as epoch 10:00 UTC.
    This function undoes that by treating the values as server time and
    applying the NY+7 offset.
    """
    naive = pd.DatetimeIndex(pd.to_datetime(epoch_seconds, unit="s"))
    return _apply_ny7(naive)


def utc_to_server_epoch(ts_utc) -> int:
    """Inverse of server_ts_to_utc: real UTC -> MT5 server-time epoch seconds
    (what MT5 chart objects use as their time coordinate)."""
    ts = pd.Timestamp(ts_utc)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    naive_server = ts.tz_convert("America/New_York").tz_localize(None) + pd.Timedelta(hours=7)
    return int((naive_server - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1))


def load_csv(path, source_tz="UTC"):
    """Load bars from an MT5 export, Dukascopy CSV, or a generic OHLC CSV."""
    with open(path, "r", encoding="utf-8-sig") as f:
        first = f.readline()
    sep = "\t" if "\t" in first else ("," if "," in first else ";")
    df = pd.read_csv(path, sep=sep, encoding="utf-8-sig")
    df.columns = [str(c).strip().strip("<>").strip().lower() for c in df.columns]
    df = df.rename(columns={"tickvol": "volume", "tick_volume": "volume", "vol": "real_volume"})

    # --- timestamps -------------------------------------------------------
    if "date" in df.columns and "time" in df.columns:          # MT5 "Export Bars"
        raw = df["date"].astype(str).str.replace(".", "-", regex=False) + " " + df["time"].astype(str)
        ts = pd.to_datetime(raw)
    elif "gmt time" in df.columns:                            # Dukascopy old format
        ts = pd.to_datetime(df["gmt time"], format="%d.%m.%Y %H:%M:%S.%f")
    elif "etc/utc" in df.columns:                             # Dukascopy new format (ISO 8601 UTC)
        ts = pd.to_datetime(df["etc/utc"], utc=True)
    else:                                                     # generic / fetch_mt5_data.py
        col = next((c for c in ("time", "datetime", "timestamp", "date") if c in df.columns), None)
        if col is None:
            raise ValueError(f"Can't find a time column in {path}. Columns: {list(df.columns)}")
        if pd.api.types.is_numeric_dtype(df[col]):
            ts = pd.to_datetime(df[col], unit="s")
        else:
            ts = pd.to_datetime(df[col])

    ts = pd.DatetimeIndex(ts)
    if ts.tz is None:
        if source_tz == "NY+7":
            ts = _apply_ny7(ts)
        else:
            ts = ts.tz_localize(source_tz, ambiguous="NaT", nonexistent="NaT")
    ts = ts.tz_convert("UTC")

    missing = [c for c in ("open", "high", "low", "close") if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns {missing} in {path}")

    out = pd.DataFrame(
        {c: pd.to_numeric(df[c], errors="coerce").to_numpy() for c in ("open", "high", "low", "close")},
        index=ts,
    )
    if "spread" in df.columns:
        out["data_spread_pips"] = pd.to_numeric(df["spread"], errors="coerce").to_numpy() / POINTS_PER_PIP
    return clean(out)


def clean(df):
    """Drop bad rows, duplicates and unsorted data."""
    df = df[df.index.notna()]
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[(df["high"] >= df["low"]) & (df["open"] > 0)]
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df.index.name = "time"
    return df


def resample(df, timeframe):
    """Turn 1-minute bars into bigger bars (e.g. '5min', '15min', '1h')."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "data_spread_pips" in df.columns:
        agg["data_spread_pips"] = "mean"
    out = df.resample(timeframe, label="left", closed="left").agg(agg)
    return out.dropna(subset=["open", "high", "low", "close"])


def filter_dates(df, start=None, end=None):
    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df.index < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
    return df


def generate_synthetic(start="2023-01-02", days=365, seed=42, start_price=1.08):
    """Random-walk 1-minute bars with realistic session volatility.

    There is NO edge in this data by construction. Use it to test the
    pipeline: a strategy should LOSE roughly its costs here. If it makes
    money on random data, something is broken (usually lookahead).
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=days * 1440, freq="1min", tz="UTC")
    idx = idx[idx.dayofweek < 5]
    h = idx.hour
    vol = np.select([h < 7, h < 12, h < 16, h < 21], [0.4, 1.2, 1.5, 1.0], default=0.5) * 0.8 * PIP
    close = start_price + np.cumsum(rng.standard_normal(len(idx)) * vol)
    open_ = np.concatenate([[start_price], close[:-1]])
    high = np.maximum(open_, close) + np.abs(rng.standard_normal(len(idx))) * vol * 0.5
    low = np.minimum(open_, close) - np.abs(rng.standard_normal(len(idx))) * vol * 0.5
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)
    df.index.name = "time"
    return df
