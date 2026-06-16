"""Candle/indicator/big-trade loading and in-memory model for the footprint chart.

Reads enriched 1-minute candle Parquet files for a FootprintConfig:
  - selects `days_back` day-files ending at the anchor date
  - concatenates them in chronological order
  - applies the time-of-day filter
  - parses tick_volume / passive_orders JSON once, up front

JSON is parsed at load time (never in the paint loop). OHLC are kept as
float64 per the schema.
"""
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


class ChartData:
    def __init__(self, df: pd.DataFrame) -> None:
        self.times = list(df.index)                 # tz-aware America/New_York
        self.n = len(df)

        self.o = df["open"].to_numpy(dtype=float)
        self.h = df["high"].to_numpy(dtype=float)
        self.l = df["low"].to_numpy(dtype=float)
        self.c = df["close"].to_numpy(dtype=float)
        self.volume = df["volume"].to_numpy()
        self.buy_volume = df["buy_volume"].to_numpy()
        self.sell_volume = df["sell_volume"].to_numpy()
        self.delta = df["volume_delta"].to_numpy()
        self.delta_pct = (df["volume_delta_pct"].to_numpy(dtype=float)
                          if "volume_delta_pct" in df.columns
                          else np.zeros(self.n))

        self.tick_volume = ([_parse_levels(s) for s in df["tick_volume"]]
                            if "tick_volume" in df.columns
                            else [{} for _ in range(self.n)])
        self.passive_orders = ([_parse_levels(s) for s in df["passive_orders"]]
                               if "passive_orders" in df.columns
                               else [{} for _ in range(self.n)])

        # indices where a new Globex session begins (for default viewport)
        self.session_starts = _session_starts(self.times)
        # epoch-ns of each bar start, for mapping trades -> candle index
        if self.n:
            self.times_ns = np.asarray(pd.DatetimeIndex(self.times).as_unit("ns").asi8)
        else:
            self.times_ns = np.array([], dtype="int64")

    def __len__(self) -> int:
        return self.n


def _parse_levels(raw) -> dict:
    """JSON string -> {price(float): (qty_a(int), qty_b(int))}."""
    if not raw or isinstance(raw, float):   # None / NaN
        return {}
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    out = {}
    for k, v in obj.items():
        if isinstance(v, list) and len(v) >= 2:
            out[float(k)] = (int(v[0]), int(v[1]))
    return out


def select_day_files(folder: Path, date: str, days_back: int) -> list:
    """The `days_back` day-files (YYYY-MM-DD.parquet) ending at the anchor date."""
    if not folder.is_dir():
        return []
    files = sorted(folder.glob("*.parquet"))
    if not files:
        return []
    try:
        anchor = pd.Timestamp(date).date()
    except (ValueError, TypeError):
        anchor = None
    selected = []
    for f in reversed(files):
        try:
            file_date = pd.Timestamp(f.stem).date()
        except ValueError:
            continue
        if anchor is None or file_date <= anchor:
            selected.append(f)
        if len(selected) >= max(1, days_back):
            break
    return list(reversed(selected))


def load_candles(config) -> Optional[ChartData]:
    """Load candle data for a FootprintConfig. Returns None if nothing to show."""
    if not config.has_dataset():
        return None
    selected = select_day_files(Path(config.dataset_path()), config.date, config.days_back)
    if not selected:
        return None

    df = pd.concat([pd.read_parquet(f) for f in selected])
    df = _apply_time_filter(df, config.time_start, config.time_end)
    if df.empty:
        return None
    df = resample_dataframe(df, config.tf_value, config.tf_unit)
    if df.empty:
        return None
    return ChartData(df)


def _apply_time_filter(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Keep rows whose NY time-of-day falls within [start, end] inclusive."""
    if df.empty:
        return df
    s, e = _to_minutes(start), _to_minutes(end)
    if s <= 0 and e >= 23 * 60 + 59:
        return df
    tod = df.index.hour * 60 + df.index.minute
    return df[(tod >= s) & (tod <= e)]


def _to_minutes(hhmm: str) -> int:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


# ---------------------------------------------------------------------------
# Timeframe resampling
# ---------------------------------------------------------------------------
def _kfmt(price: float) -> str:
    return f"{price:.10g}"


def _session_starts(times) -> list:
    """Indices where a new Globex session begins (hour >= 18 => next day)."""
    if not times:
        return []
    ti = pd.DatetimeIndex(times)
    naive = ti.tz_localize(None) if ti.tz is not None else ti
    add = np.where(naive.hour >= 18, 1, 0)
    trading = naive.normalize() + pd.to_timedelta(add, unit="D")
    starts = [0]
    for i in range(1, len(trading)):
        if trading[i] != trading[i - 1]:
            starts.append(i)
    return starts


def _bin_keys(index: pd.DatetimeIndex, tf_value: int, tf_unit: str):
    """Per-row bin label (tz-aware NY) for the requested timeframe."""
    idx = pd.DatetimeIndex(index)
    tz = idx.tz

    if tf_unit in ("Minutes", "Hours"):
        rule = f"{tf_value}min" if tf_unit == "Minutes" else f"{tf_value}h"
        # floor on wall-clock time, then re-localize (clock-aligned bins)
        naive = idx.tz_localize(None) if tz is not None else idx
        floored = naive.floor(rule)
        if tz is not None:
            floored = floored.tz_localize(tz, nonexistent="shift_forward", ambiguous=False)
        return floored

    # Days and above: group by Globex trading date
    naive = idx.tz_localize(None) if tz is not None else idx
    add = np.where(naive.hour >= 18, 1, 0)
    trading = pd.DatetimeIndex(naive.normalize() + pd.to_timedelta(add, unit="D"))

    if tf_unit == "Days":
        periods = trading
    elif tf_unit == "Weeks":
        periods = trading - pd.to_timedelta(trading.weekday, unit="D")  # Monday
    elif tf_unit == "Months":
        periods = trading.to_period("M").to_timestamp()
    elif tf_unit == "Years":
        periods = trading.to_period("Y").to_timestamp()
    else:
        return None

    if tf_value > 1:
        uniq = pd.Index(sorted(pd.unique(periods)))
        pos = {p: i for i, p in enumerate(uniq)}
        periods = pd.DatetimeIndex([uniq[(pos[p] // tf_value) * tf_value] for p in periods])

    if tz is not None:
        periods = pd.DatetimeIndex(periods).tz_localize(
            tz, nonexistent="shift_forward", ambiguous=False)
    return periods


def _aggregate_group(g: pd.DataFrame) -> dict:
    buy = int(g["buy_volume"].sum())
    sell = int(g["sell_volume"].sum())
    delta = buy - sell
    if min(buy, sell) == 0:
        pct = 100.0
    elif buy > sell:
        pct = delta / sell * 100.0
    elif sell > buy:
        pct = delta / buy * 100.0
    else:
        pct = 0.0

    tv: dict = {}
    if "tick_volume" in g.columns:
        for s in g["tick_volume"]:
            for k, (b, sl) in _parse_levels(s).items():
                pb, ps = tv.get(k, (0, 0))
                tv[k] = (pb + b, ps + sl)
    po: dict = {}
    if "passive_orders" in g.columns:
        for s in g["passive_orders"]:
            for k, (sz, ct) in _parse_levels(s).items():
                psz, pct2 = po.get(k, (0, 0))
                po[k] = (psz + sz, pct2 + ct)

    return {
        "open":   float(g["open"].iloc[0]),
        "high":   float(g["high"].max()),
        "low":    float(g["low"].min()),
        "close":  float(g["close"].iloc[-1]),
        "volume": int(g["volume"].sum()),
        "buy_volume":  buy,
        "sell_volume": sell,
        "volume_delta": delta,
        "volume_delta_pct": pct,
        "tick_volume":    json.dumps({_kfmt(k): [b, s] for k, (b, s) in tv.items()}),
        "passive_orders": json.dumps({_kfmt(k): [sz, ct] for k, (sz, ct) in po.items()}),
    }


def resample_dataframe(df: pd.DataFrame, tf_value: int, tf_unit: str) -> pd.DataFrame:
    """Resample 1-minute candles to the requested timeframe.

    OHLC = first/max/min/last, volumes summed, footprint tick_volume and
    passive_orders merged per price level. Minute/hour bins are clock-aligned;
    day+ bins group by Globex trading date.
    """
    if df.empty:
        return df
    if tf_unit == "Minutes" and tf_value <= 1:
        return df

    keys = _bin_keys(df.index, tf_value, tf_unit)
    if keys is None:
        return df

    tmp = df.copy()
    tmp["_bin"] = keys
    out_index, out_rows = [], []
    for bin_key, g in tmp.groupby("_bin", sort=True):
        out_index.append(bin_key)
        out_rows.append(_aggregate_group(g))
    if not out_rows:
        return df.iloc[0:0]
    return pd.DataFrame(out_rows, index=pd.DatetimeIndex(out_index))


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------
class IndicatorData:
    """Indicator columns aligned 1:1 with the candle bars (numpy float arrays)."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._cols = {c: df[c].to_numpy(dtype=float) for c in df.columns}

    def has(self, col: str) -> bool:
        return col in self._cols

    def col(self, col: str):
        return self._cols.get(col)


def _resample_last(df: pd.DataFrame, tf_value: int, tf_unit: str) -> pd.DataFrame:
    """Resample to the chart timeframe, taking each bin's last value (as-of close)."""
    if df.empty:
        return df
    if tf_unit == "Minutes" and tf_value <= 1:
        return df
    keys = _bin_keys(df.index, tf_value, tf_unit)
    if keys is None:
        return df
    tmp = df.copy()
    tmp["_bin"] = keys
    return tmp.groupby("_bin", sort=True).agg("last")


def load_indicators(config, candle_times) -> Optional[IndicatorData]:
    """Load indicator data aligned to the candle bars. None if unavailable."""
    path = config.indicators_path()
    if not path:
        return None
    selected = select_day_files(Path(path), config.date, config.days_back)
    if not selected:
        return None
    df = pd.concat([pd.read_parquet(f) for f in selected])
    df = _apply_time_filter(df, config.time_start, config.time_end)
    if df.empty:
        return None
    df = _resample_last(df, config.tf_value, config.tf_unit)
    # align to the candle bins (same 1-minute grid -> matching bin labels)
    df = df.reindex(pd.DatetimeIndex(candle_times))
    return IndicatorData(df)


# ---------------------------------------------------------------------------
# Big trades
# ---------------------------------------------------------------------------
class BigTradeData:
    """Individual large trades: price, size, side, plus epoch-ms and RTH flag."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.n = len(df)
        price = df["price"].to_numpy(dtype=float)
        size = df["size"].to_numpy()
        side = df["side"].astype(str).to_numpy()
        ts_ns = np.asarray(pd.DatetimeIndex(df.index).as_unit("ns").asi8)
        tod = pd.DatetimeIndex(df.index)
        mins = np.asarray(tod.hour * 60 + tod.minute)
        # keep everything time-ordered so trades can be range-sliced per candle
        order = np.argsort(ts_ns, kind="stable")
        self.ts_ns = ts_ns[order]
        self.price = price[order]
        self.size = size[order]
        self.side = side[order]
        # minutes-of-day (NY) per trade; RTH classification done at draw time
        # so the configurable RTH window applies live without reloading.
        self.tod_min = mins[order]

    def __len__(self) -> int:
        return self.n


def load_big_trades(config, days_back: int) -> Optional[BigTradeData]:
    """Load big-trade data using its own days_back. None if unavailable."""
    path = config.big_trades_path()
    if not path:
        return None
    selected = select_day_files(Path(path), config.date, days_back)
    if not selected:
        return None
    df = pd.concat([pd.read_parquet(f) for f in selected])
    df = _apply_time_filter(df, config.time_start, config.time_end)
    if df.empty:
        return None
    return BigTradeData(df)


# ---------------------------------------------------------------------------
# Composite volume profile (multi-day total volume)
# ---------------------------------------------------------------------------
def load_composite_volume(config, days_back: int, end_time: str):
    """Aggregate total volume per price across the most recent `days_back`
    day-files (including the current one). On the LAST (most recent) day only
    bars strictly before `end_time` (NY) are counted. Other days are full.

    Returns (levels, days_loaded) where levels is {price: total_volume};
    days_loaded is the actual number of files used (may be < days_back near the
    start of history). Returns ({}, 0) when nothing is available.
    """
    folder = Path(config.dataset_path())
    files = select_day_files(folder, config.date, days_back)
    if not files:
        return {}, 0

    last = files[-1]
    try:
        last_date = pd.Timestamp(last.stem).date()
        cutoff = pd.Timestamp(f"{last_date} {end_time}").tz_localize("America/New_York")
    except (ValueError, TypeError):
        cutoff = None

    levels: dict = {}
    for f in files:
        try:
            df = pd.read_parquet(f, columns=["tick_volume"])
        except Exception:
            continue
        if f is last and cutoff is not None:
            df = df[df.index < cutoff]   # last day: stop at end_time (exclusive)
        for tvs in df["tick_volume"]:
            if not tvs:
                continue
            try:
                d = json.loads(tvs) if isinstance(tvs, str) else tvs
            except (ValueError, TypeError):
                continue
            for price_s, qty in d.items():
                price = float(price_s)
                total = (qty[0] + qty[1]) if isinstance(qty, (list, tuple)) else qty
                levels[price] = levels.get(price, 0) + total
    return levels, len(files)
