"""Day-grid exposure computation for the interval map.

Samples the session at a fixed interval and runs the options chart's
``compute_exposure`` at each sampled timestamp, collecting per-strike totals
into [rows x cols] matrices. Qt-free.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from views.options_chart.options_compute import (
    ExposureParams, compute_exposure, units_label_for,
)

INTERVALS = [("5 min", 5), ("10 min", 10), ("15 min", 15),
             ("30 min", 30), ("60 min", 60)]
STRIKE_STEPS = [("All", 0), ("5", 5), ("10", 10), ("25", 25),
                ("50", 50), ("100", 100)]

# cells below this fraction of the grid max draw nothing
DOT_THRESHOLD = 0.005


@dataclass
class IntervalGrid:
    strikes: np.ndarray     # float64 [n_rows], ascending (row 0 = lowest strike)
    t_idx: np.ndarray       # int32 [n_cols], indices into day.times
    times: list             # [n_cols] pd.Timestamp
    total: np.ndarray       # float64 [n_rows, n_cols]
    call_part: np.ndarray
    put_part: np.ndarray
    F: np.ndarray           # float64 [n_cols], NaN where no underlying price
    f_row: np.ndarray       # float64 [n_cols], fractional row of F, NaN with F
    vmax: float             # max |total| over the kept grid
    units_label: str

    @property
    def n_rows(self) -> int:
        return len(self.strikes)

    @property
    def n_cols(self) -> int:
        return len(self.t_idx)


def build_interval_grid(day, params: ExposureParams, interval_min: int,
                        strike_step: int, iv_cache: dict,
                        progress_cb=None, cancel_cb=None) -> IntervalGrid | None:
    """Exposure grid over the whole session. None: cancelled or no nonzero rows.

    ``iv_cache`` is the window's shared per-timestamp IV cache — the first build
    is IV-bound (~11 ms/col), later rebuilds under new params reuse it (<1 ms/col).
    A data gap in the 5-min rows would shift wall-time alignment of the sampled
    columns; accepted (columns are "every k-th bar", not wall-clock anchored).
    """
    k = max(1, interval_min // 5)
    t_idx = np.arange(0, day.n_t, k, dtype=np.int32)
    n_cols = len(t_idx)

    total = np.zeros((day.n_strikes, n_cols))
    call_part = np.zeros((day.n_strikes, n_cols))
    put_part = np.zeros((day.n_strikes, n_cols))
    F = np.full(n_cols, np.nan)
    result_cache: dict = {}     # fresh per build; only iv_cache is worth keeping

    for j, t in enumerate(t_idx):
        if cancel_cb is not None and cancel_cb():
            return None
        res = compute_exposure(day, int(t), params, iv_cache, result_cache)
        if res is not None:
            total[:, j] = res.total
            call_part[:, j] = res.call_part
            put_part[:, j] = res.put_part
            F[j] = res.F
        if progress_cb is not None and (j % 4 == 3 or j == n_cols - 1):
            progress_cb(j + 1, n_cols)

    keep = np.ones(day.n_strikes, dtype=bool)
    if strike_step > 0:
        q = day.strikes_sorted / strike_step
        keep &= np.abs(q - np.round(q)) < 1e-9
    keep &= ((total != 0) | (call_part != 0) | (put_part != 0)).any(axis=1)
    if not keep.any():
        return None

    strikes = day.strikes_sorted[keep]
    total, call_part, put_part = total[keep], call_part[keep], put_part[keep]
    vmax = float(np.abs(total).max())
    if vmax <= 0:
        return None

    f_row = np.full(n_cols, np.nan)
    m = np.isfinite(F)
    if m.any():
        f_row[m] = np.interp(F[m], strikes, np.arange(len(strikes), dtype=np.float64))

    return IntervalGrid(
        strikes=strikes, t_idx=t_idx, times=[day.times[int(t)] for t in t_idx],
        total=total, call_part=call_part, put_part=put_part,
        F=F, f_row=f_row, vmax=vmax, units_label=units_label_for(params),
    )
