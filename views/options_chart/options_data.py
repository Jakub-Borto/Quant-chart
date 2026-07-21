"""Disk -> memory loading for the options exposure chart.

Reads one day of sparse 5-minute option rows and densifies them into
forward-filled per-contract state grids so any slider time is a column slice.
Contract definitions (strike / call-put / expiry) come from the parquet
schema metadata (key ``contracts``), the point multiplier from ``multiplier``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from views.footprint_chart.footprint_data import select_day_files

_COLUMNS = ["instrument_id", "bid", "ask", "open_interest",
            "daily_estimated_oi", "dealer_oi_flow"]


class OptionsDay:
    """One session of forward-filled option state. Immutable after load."""

    def __init__(self, times, strike, cp, expiry_ns, mult,
                 bid, ask, oi, est_oi, flow, quote_backfilled, F, date):
        self.times = times                    # list[pd.Timestamp], sorted
        self.times_ns = np.array([t.value for t in times], dtype=np.int64)
        self.n_t = len(times)
        self.n_inst = len(strike)
        self.strike = strike                  # float64 [n_inst]
        self.cp = cp                          # int8 [n_inst], +1 call / -1 put
        self.expiry_ns = expiry_ns            # int64 [n_inst]
        self.strikes_sorted = np.unique(strike)
        self.strike_slot = np.searchsorted(self.strikes_sorted, strike).astype(np.int32)
        self.n_strikes = len(self.strikes_sorted)
        self.mult = mult
        self.bid = bid                        # float32 [n_inst, n_t], ffilled
        self.ask = ask
        self.oi = oi
        self.est_oi = est_oi
        self.flow = flow
        self.quote_backfilled = quote_backfilled  # bool [n_inst]
        self.F = F                            # float64 [n_t], underlying close <= t
        self.date = date                      # actual loaded date "YYYY-MM-DD"

    def __len__(self) -> int:
        return self.n_t


def _read_meta(path: Path) -> tuple[dict, float]:
    meta = pq.read_schema(path).metadata or {}
    contracts = json.loads(meta.get(b"contracts", b"{}"))
    mult = float(meta.get(b"multiplier", b"1"))
    return contracts, mult


def _ffill_rows(grid: np.ndarray) -> np.ndarray:
    """Row-wise forward fill; cells before a row's first observation stay NaN."""
    n_inst, n_t = grid.shape
    idx = np.where(np.isfinite(grid), np.arange(n_t)[None, :], 0)
    np.maximum.accumulate(idx, axis=1, out=idx)
    return grid[np.arange(n_inst)[:, None], idx]


def _backfill_quotes(folder: Path, day_file: Path, missing_ids: np.ndarray,
                     max_files: int) -> pd.DataFrame:
    """Last non-null bid/ask per missing instrument from files older than day_file."""
    found = pd.DataFrame(columns=["bid", "ask"])
    if max_files <= 0 or len(missing_ids) == 0:
        return found
    older = []
    for f in sorted(folder.glob("*.parquet"), reverse=True):
        try:
            if pd.Timestamp(f.stem).date() < pd.Timestamp(day_file.stem).date():
                older.append(f)
        except ValueError:
            continue
        if len(older) >= max_files:
            break
    remaining = set(int(i) for i in missing_ids)
    for f in older:
        if not remaining:
            break
        try:
            df = pd.read_parquet(f, columns=["instrument_id", "bid", "ask"])
        except (OSError, ValueError, KeyError):
            continue
        df = df[df["instrument_id"].isin(remaining)]
        if df.empty:
            continue
        last = df.groupby("instrument_id")[["bid", "ask"]].last()
        last = last.dropna(how="all")
        found = pd.concat([found, last[~last.index.isin(found.index)]])
        remaining -= set(found.index.tolist())
    return found


def _load_futures_closes(config) -> Optional[tuple[np.ndarray, np.ndarray]]:
    if not config.has_futures():
        return None
    files = select_day_files(Path(config.futures_path()), config.date, 1)
    if not files:
        return None
    try:
        df = pd.read_parquet(files[-1], columns=["close"])
    except (OSError, ValueError, KeyError):
        return None
    if df.empty:
        return None
    return df.index.as_unit("ns").asi8, df["close"].to_numpy(dtype=np.float64)


def load_options_day(config, settings, progress_cb=None, cancel_cb=None) -> Optional[OptionsDay]:
    """Load one day of option state for an OptionsConfig. None if nothing to show."""
    def _progress(step: int) -> bool:
        if progress_cb is not None:
            progress_cb(step, 6)
        return bool(cancel_cb and cancel_cb())

    if not config.has_dataset():
        return None
    selected = select_day_files(Path(config.dataset_path()), config.date, 1)
    if not selected:
        return None
    day_file = selected[-1]
    if _progress(0):
        return None

    contracts, mult = _read_meta(day_file)
    try:
        df = pd.read_parquet(day_file, columns=_COLUMNS)
    except (OSError, ValueError, KeyError):
        return None
    if df.empty:
        return None
    if _progress(1):
        return None

    # Axes: unique sorted timestamps x factorized instruments
    row_ts = df.index.as_unit("ns").asi8
    times_ns_u = np.unique(row_ts)
    t_idx = np.searchsorted(times_ns_u, row_ts)
    iid, uniq = pd.factorize(df["instrument_id"].to_numpy())
    n_t, n_inst = len(times_ns_u), len(uniq)

    # Static contract arrays from metadata (drop instruments without a definition)
    strike = np.full(n_inst, np.nan)
    cp = np.zeros(n_inst, dtype=np.int8)
    expiry_ns = np.zeros(n_inst, dtype=np.int64)
    for k, inst_id in enumerate(uniq):
        c = contracts.get(str(int(inst_id)))
        if c is None:
            continue
        strike[k] = float(c["strike"])
        cp[k] = 1 if c.get("cp_flag") == "call" else -1
        expiry_ns[k] = pd.Timestamp(c["expiry"]).value
    known = np.isfinite(strike) & (cp != 0)
    n_dropped = int(n_inst - known.sum())
    if n_dropped:
        print(f"[options] {n_dropped} instruments missing from contracts metadata, dropped",
              file=sys.stderr)
    if not known.any():
        return None
    if _progress(2):
        return None

    # Dense grids: one fancy assignment per column, then row-wise forward fill
    grids = {}
    for col in ("bid", "ask", "open_interest", "daily_estimated_oi", "dealer_oi_flow"):
        g = np.full((n_inst, n_t), np.nan, dtype=np.float32)
        g[iid, t_idx] = df[col].to_numpy(dtype=np.float32)
        grids[col] = _ffill_rows(g)
    if _progress(3):
        return None

    # Keep only contracts with metadata
    if n_dropped:
        uniq = uniq[known]
        strike, cp, expiry_ns = strike[known], cp[known], expiry_ns[known]
        grids = {c: g[known] for c, g in grids.items()}
        n_inst = len(uniq)

    # Previous-day backfill for instruments whose bid/ask never appeared today.
    # After ffill, NaN cells are exactly the prefix before the first observation,
    # so filling only-NaN cells with an older quote preserves most-recent semantics.
    bid, ask = grids["bid"], grids["ask"]
    no_mid = ~(np.isfinite(bid[:, -1]) & np.isfinite(ask[:, -1]))
    quote_backfilled = np.zeros(n_inst, dtype=bool)
    if no_mid.any() and settings.quote_lookback_files > 0:
        found = _backfill_quotes(Path(config.dataset_path()), day_file,
                                 uniq[no_mid], settings.quote_lookback_files)
        if not found.empty:
            slot_of = {int(v): k for k, v in enumerate(uniq)}
            for inst_id, row in found.iterrows():
                k = slot_of.get(int(inst_id))
                if k is None:
                    continue
                if np.isfinite(row["bid"]):
                    bid[k, ~np.isfinite(bid[k])] = row["bid"]
                if np.isfinite(row["ask"]):
                    ask[k, ~np.isfinite(ask[k])] = row["ask"]
                quote_backfilled[k] = True
    if _progress(4):
        return None

    # Underlying futures price per option timestamp
    fut = _load_futures_closes(config)
    if fut is None:
        return None
    f_ts, f_close = fut
    pos = np.searchsorted(f_ts, times_ns_u, side="right") - 1
    F = np.where(pos >= 0, f_close[np.clip(pos, 0, None)], np.nan)
    if _progress(5):
        return None

    tz = df.index.tz
    times = [pd.Timestamp(t, tz=tz) for t in times_ns_u]
    if _progress(6):
        return None

    return OptionsDay(
        times=times, strike=strike, cp=cp, expiry_ns=expiry_ns, mult=mult,
        bid=bid, ask=ask, oi=grids["open_interest"],
        est_oi=grids["daily_estimated_oi"], flow=grids["dealer_oi_flow"],
        quote_backfilled=quote_backfilled, F=F, date=day_file.stem,
    )
