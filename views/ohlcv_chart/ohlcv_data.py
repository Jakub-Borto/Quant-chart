"""OHLCV data loader — thin wrapper around footprint_data helpers."""
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from views.footprint_chart.footprint_data import (
    select_day_files,
    _apply_time_filter,
    _bin_keys,
    _session_starts,
    load_indicators,
)


class OhlcvData:
    def __init__(self, df: pd.DataFrame) -> None:
        self.times = list(df.index)
        self.n = len(df)
        self.o = df["open"].to_numpy(dtype=float)
        self.h = df["high"].to_numpy(dtype=float)
        self.l = df["low"].to_numpy(dtype=float)
        self.c = df["close"].to_numpy(dtype=float)
        self.volume = df["volume"].to_numpy(dtype=float) if "volume" in df.columns else np.zeros(self.n)
        self.session_starts = _session_starts(self.times)
        # epoch-ns of each bar start, for mapping timestamps -> candle index
        if self.n:
            self.times_ns = np.asarray(pd.DatetimeIndex(self.times).as_unit("ns").asi8)
        else:
            self.times_ns = np.array([], dtype="int64")

    def __len__(self) -> int:
        return self.n


def _resample_ohlcv(df: pd.DataFrame, tf_value: int, tf_unit: str) -> pd.DataFrame:
    """Resample to the requested timeframe using only OHLCV columns."""
    if df.empty:
        return df
    if tf_unit == "Minutes" and tf_value <= 1:
        return df
    keys = _bin_keys(df.index, tf_value, tf_unit)
    if keys is None:
        return df
    tmp = df.copy()
    tmp["_bin"] = keys
    rows = []
    for bin_key, g in tmp.groupby("_bin", sort=True):
        row = {
            "open":   float(g["open"].iloc[0]),
            "high":   float(g["high"].max()),
            "low":    float(g["low"].min()),
            "close":  float(g["close"].iloc[-1]),
        }
        if "volume" in g.columns:
            row["volume"] = float(g["volume"].sum())
        rows.append((bin_key, row))
    if not rows:
        return pd.DataFrame()
    index = pd.DatetimeIndex([r[0] for r in rows])
    out = pd.DataFrame([r[1] for r in rows], index=index)
    out.index.name = df.index.name
    return out


def load_ohlcv(config) -> Optional[OhlcvData]:
    if not config.has_dataset():
        return None
    selected = select_day_files(Path(config.dataset_path()), config.date, config.days_back)
    if not selected:
        return None
    df = pd.concat([pd.read_parquet(f) for f in selected])
    df = _apply_time_filter(df, config.time_start, config.time_end)
    if df.empty:
        return None
    df = _resample_ohlcv(df, config.tf_value, config.tf_unit)
    if df.empty:
        return None
    return OhlcvData(df)


def load_ohlcv_indicators(config, candle_times):
    """Reuse footprint IndicatorData — it's generic (VWAP bands work for any OHLCV chart)."""
    if not config.has_indicators():
        return None
    return load_indicators(config, candle_times)
