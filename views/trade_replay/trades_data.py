"""Trades parquet loader + in-memory model for the trade replay window.

A trades file is one parquet with one row per backtest trade. The canonical
schema (ivb_model files) is:
    date, direction, trade_type, entry_time, exit_time, entry_price,
    exit_price, sl, tp, exit_reason, pnl_points, ticks, cumulative_ticks,
    notes (JSON string)
Older files may lack trade_type / notes — everything optional is fail-soft.
Unknown extra columns are kept and surfaced generically (detail cards +
table columns).
"""
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from core.asset_info import tick_size_for

# columns we know how to display specially; anything else is an "extra"
KNOWN_COLS = {
    "date", "direction", "trade_type", "entry_time", "exit_time",
    "entry_price", "exit_price", "sl", "tp", "exit_reason",
    "pnl_points", "ticks", "cumulative_ticks", "notes",
}
REQUIRED_COLS = {"date", "direction", "entry_time", "exit_time", "entry_price"}

# display order for the table (existing columns only, extras appended)
TABLE_COL_ORDER = [
    "date", "direction", "trade_type", "entry_time", "exit_time",
    "entry_price", "exit_price", "sl", "tp", "sl_ticks", "tp_ticks", "rr",
    "ticks", "cumulative_ticks", "duration_min", "exit_reason",
]


def default_trades_dir(parquet_root: str) -> str:
    """Sibling `trades` folder of the parquet data root."""
    if not parquet_root:
        return ""
    return str(Path(parquet_root).parent / "trades")


def list_trade_files(folder: str) -> list:
    """*.parquet in the folder, newest first. Fail-soft empty list."""
    try:
        p = Path(folder)
        if not p.is_dir():
            return []
        return sorted(p.glob("*.parquet"), key=lambda f: f.stat().st_mtime,
                      reverse=True)
    except OSError:
        return []


def _safe_json(raw) -> dict:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return obj if isinstance(obj, dict) else {}


class TradeSet:
    """Normalized trades + parsed notes + per-column filter arrays."""

    def __init__(self, df: pd.DataFrame, notes: list, tick_size: float,
                 extra_cols: list, path: Path) -> None:
        self.df = df
        self.notes = notes
        self.tick_size = tick_size
        self.extra_cols = extra_cols
        self.path = path
        self.table_cols = ([c for c in TABLE_COL_ORDER if c in df.columns]
                           + extra_cols)

    def __len__(self) -> int:
        return len(self.df)

    def column_kind(self, col: str) -> str:
        """'numeric' | 'time' | 'date' | 'categorical' — drives filter UI."""
        if col in ("entry_time", "exit_time"):
            return "time"
        if col == "date":
            return "date"
        dtype = self.df[col].dtype
        if pd.api.types.is_datetime64_any_dtype(dtype):
            return "time"
        if pd.api.types.is_numeric_dtype(dtype) or pd.api.types.is_bool_dtype(dtype):
            return "numeric"
        return "categorical"

    def filter_values(self, col: str) -> np.ndarray:
        """Numeric array used for filtering (times → minute-of-day,
        dates → yyyymmdd ints); categorical columns return the raw values."""
        kind = self.column_kind(col)
        s = self.df[col]
        if kind == "time":
            t = pd.DatetimeIndex(s)
            return (t.hour * 60 + t.minute).to_numpy(dtype=float)
        if kind == "date":
            return np.array([float(str(v).replace("-", "")[:8] or "nan")
                             for v in s])
        if kind == "numeric":
            return s.to_numpy(dtype=float)
        return s.to_numpy()


def load_trades(path) -> Optional[TradeSet]:
    path = Path(path)
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    if df.empty or not REQUIRED_COLS.issubset(df.columns):
        return None
    df = df.reset_index(drop=True)

    tick = tick_size_for(path.name.split("_")[0])

    # normalize date -> 'YYYY-MM-DD' strings (handles date objects, str, ts)
    df["date"] = df["date"].map(lambda v: str(v)[:10])

    notes = ([_safe_json(v) for v in df["notes"]] if "notes" in df.columns
             else [{} for _ in range(len(df))])

    # derived columns (NaN-safe)
    entry = df["entry_price"].to_numpy(dtype=float)
    if "sl" in df.columns:
        df["sl_ticks"] = np.abs(entry - df["sl"].to_numpy(dtype=float)) / tick
    if "tp" in df.columns:
        df["tp_ticks"] = np.abs(df["tp"].to_numpy(dtype=float) - entry) / tick
    if "sl_ticks" in df.columns and "tp_ticks" in df.columns:
        slt = df["sl_ticks"].to_numpy()
        df["rr"] = np.where(slt > 0, df["tp_ticks"].to_numpy() / np.where(slt > 0, slt, 1.0), np.nan)
    if "ticks" not in df.columns and "pnl_points" in df.columns:
        df["ticks"] = df["pnl_points"].to_numpy(dtype=float) / tick
    df["duration_min"] = (
        (pd.DatetimeIndex(df["exit_time"]) - pd.DatetimeIndex(df["entry_time"]))
        .total_seconds().to_numpy() / 60.0)

    derived = {"sl_ticks", "tp_ticks", "rr", "duration_min"}
    extra_cols = [c for c in df.columns
                  if c not in KNOWN_COLS and c not in derived]
    return TradeSet(df, notes, tick, extra_cols, path)
