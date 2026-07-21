"""Timestamp-based capture/restore of index-anchored drawings.

Drawings (v-lines, rays, boxes, positions) are anchored by candle index, so
changing the timeframe or the anchor date would leave them pointing at whatever
candle now occupies that index. Before a reload the window captures each
drawing's timestamps here; after the reload it restores them onto the new
candle array. Dicts are mutated in place so object identity is preserved
(the trade-replay module tracks its auto-drawn position by identity).
"""
import numpy as np
import pandas as pd


def times_ns_of(data) -> np.ndarray:
    """Epoch-ns of each bar start for any chart data model."""
    t = getattr(data, "times_ns", None)
    if t is not None:
        return t
    if not len(data.times):
        return np.array([], dtype="int64")
    return np.asarray(pd.DatetimeIndex(data.times).as_unit("ns").asi8)


def _idx_ts(t: np.ndarray, idx) -> int:
    return int(t[int(np.clip(round(idx), 0, len(t) - 1))])


def _drawing_ts(t: np.ndarray, d: dict, key: str) -> int:
    """Timestamp for one index field of a drawing dict.

    Prefers the timestamp stashed by the last restore — it survives a visit
    to a date range that doesn't contain the drawing (where the index gets
    clamped to the data edge). The stash is honored only while the index is
    untouched; once the user drags the drawing, the index wins.
    """
    stashed = d.get("_anchors", {}).get(key)
    if stashed is not None and stashed[1] == d[key]:
        return stashed[0]
    return _idx_ts(t, d[key])


def capture_anchors(canvas):
    """Snapshot index-anchored drawings as timestamps. None if no data."""
    d = canvas.data
    if d is None or not len(d):
        return None
    t = times_ns_of(d)
    return {
        "v_lines": [_idx_ts(t, i) for i in canvas.v_lines],
        "rays": [(r, _drawing_ts(t, r, "idx")) for r in canvas.rays],
        "boxes": [(b, _drawing_ts(t, b, "idx1"), _drawing_ts(t, b, "idx2"))
                  for b in canvas.boxes],
        "positions": [(p, _drawing_ts(t, p, "idx1"), _drawing_ts(t, p, "idx2"))
                      for p in canvas.positions],
    }


def restore_anchors(canvas, snapshot) -> None:
    """Re-anchor drawings onto the (new) candle array, mutating in place."""
    d = canvas.data
    if snapshot is None or d is None or not len(d):
        return
    t = times_ns_of(d)

    def to_idx(ts) -> int:
        # candle containing the timestamp (bar-start convention), clamped
        return int(np.clip(np.searchsorted(t, ts, side="right") - 1, 0, len(t) - 1))

    canvas.v_lines[:] = [to_idx(ts) for ts in snapshot["v_lines"]]
    for ray, ts in snapshot["rays"]:
        ray["idx"] = to_idx(ts)
        ray["_anchors"] = {"idx": (ts, ray["idx"])}
    for box, ts1, ts2 in snapshot["boxes"]:
        if ts1 > ts2:
            ts1, ts2 = ts2, ts1
        box["idx1"], box["idx2"] = to_idx(ts1), to_idx(ts2)
        box["_anchors"] = {"idx1": (ts1, box["idx1"]),
                           "idx2": (ts2, box["idx2"])}
    for pos, ts1, ts2 in snapshot["positions"]:
        if ts1 > ts2:
            ts1, ts2 = ts2, ts1
        pos["idx1"], pos["idx2"] = to_idx(ts1), to_idx(ts2)
        pos["_anchors"] = {"idx1": (ts1, pos["idx1"]),
                           "idx2": (ts2, pos["idx2"])}
