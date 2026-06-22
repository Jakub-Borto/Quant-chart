"""Heatmap data loader — 1-second MBO order-book snapshots.

Reuses the low-level day-file / time-filter / session helpers from
footprint_data.  The depth books are kept as raw JSON strings and parsed
lazily (per second, on first access) because a full session is 82,800 rows
with ~1,700 price levels each — parsing all of it eagerly would be multi-GB.

For zoomed-out views, a multi-resolution aggregation pyramid (`HeatmapPyramid`)
is precomputed once and cached to disk, so wide views render as a single
vectorized image blit instead of a per-column parse-and-loop.
"""
import json
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from views.footprint_chart.footprint_data import (
    select_day_files,
    _apply_time_filter,
    _session_starts,
)

# Fast JSON if available (orjson ~2x faster); stdlib fallback.
try:
    import orjson as _orjson

    def _loads(s):
        return _orjson.loads(s)
except ImportError:
    def _loads(s):
        return json.loads(s)

# Price window (in points) around the touch used only to estimate a default
# color-normalization reference; keeps far-resting levels from skewing it.
_REF_WINDOW_PTS = 25.0
_REF_PERCENTILE = 90.0
_REF_FALLBACK = 200.0

# ── Aggregation pyramid parameters ────────────────────────────────────
# Base bucket is 1s (exact per-second) so the most zoomed-in view loses no
# detail; the pyramid is used at every zoom level. Steps: 1/4/16/64/256 s.
_PYR_BASE_SEC = 1          # base bucket size (seconds)
_PYR_FACTOR = 4            # each coarser level aggregates this many buckets
_PYR_EXTRA_LEVELS = 4      # number of coarser levels above the base
_PYR_MIN_MARGIN_TICKS = 256  # grid half-window beyond the traded range
_PYR_MAX_DEPTH = 32767     # int16 clip
_PYR_REF_PERCENTILE = 99.7  # depth percentile mapped near full color
_CACHE_VERSION = 6


def _parse_depth(raw) -> dict:
    """JSON string -> {price(float): qty(int)}. Empty dict on missing/bad."""
    if not raw or isinstance(raw, float):   # None / NaN
        return {}
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    out = {}
    for k, v in obj.items():
        try:
            out[float(k)] = int(v)
        except (ValueError, TypeError):
            continue
    return out


class HeatmapData:
    def __init__(self, df: pd.DataFrame) -> None:
        self.times = list(df.index)
        self.n = len(df)
        self.o = df["open"].to_numpy(dtype=float)
        self.h = df["high"].to_numpy(dtype=float)
        self.l = df["low"].to_numpy(dtype=float)
        self.c = df["close"].to_numpy(dtype=float)
        self.volume = (df["volume"].to_numpy(dtype=float)
                       if "volume" in df.columns else np.zeros(self.n))
        self.best_bid = (df["best_bid"].to_numpy(dtype=float)
                         if "best_bid" in df.columns else np.full(self.n, np.nan))
        self.best_ask = (df["best_ask"].to_numpy(dtype=float)
                         if "best_ask" in df.columns else np.full(self.n, np.nan))
        self.session_starts = _session_starts(self.times)
        # minute-of-day per second, for labelling columns ETH vs RTH
        idx = df.index
        self.tod_min = (idx.hour * 60 + idx.minute).to_numpy().astype(np.int32)

        # raw JSON books, parsed lazily
        self._bid_raw = (df["bid_depth"].to_numpy(dtype=object)
                         if "bid_depth" in df.columns else np.full(self.n, "{}", dtype=object))
        self._ask_raw = (df["ask_depth"].to_numpy(dtype=object)
                         if "ask_depth" in df.columns else np.full(self.n, "{}", dtype=object))
        self._cache: dict = {}
        self._arr_cache: dict = {}

        self.default_ref = self._estimate_ref()

    def __len__(self) -> int:
        return self.n

    def levels(self, i: int):
        """Return (bid: {price:qty}, ask: {price:qty}) for second i, cached."""
        hit = self._cache.get(i)
        if hit is None:
            hit = (_parse_depth(self._bid_raw[i]), _parse_depth(self._ask_raw[i]))
            self._cache[i] = hit
        return hit

    def level_arrays(self, i: int):
        """(bid_prices, bid_qtys, ask_prices, ask_qtys) as float arrays, cached.

        Used by the heatmap renderer for vectorized drawing.
        """
        hit = self._arr_cache.get(i)
        if hit is None:
            bid, ask = self.levels(i)
            bp = np.fromiter(bid.keys(), dtype=float, count=len(bid))
            bq = np.fromiter(bid.values(), dtype=float, count=len(bid))
            ap = np.fromiter(ask.keys(), dtype=float, count=len(ask))
            aq = np.fromiter(ask.values(), dtype=float, count=len(ask))
            hit = (bp, bq, ap, aq)
            self._arr_cache[i] = hit
        return hit

    def _estimate_ref(self) -> float:
        """A representative 'large' resting size near the touch, for coloring."""
        if self.n == 0:
            return _REF_FALLBACK
        step = max(1, self.n // 500)
        samples = []
        for i in range(0, self.n, step):
            bid_px, ask_px = self.best_bid[i], self.best_ask[i]
            if np.isnan(bid_px) or np.isnan(ask_px):
                continue
            lo, hi = bid_px - _REF_WINDOW_PTS, ask_px + _REF_WINDOW_PTS
            bid, ask = self.levels(i)
            for book in (bid, ask):
                for price, qty in book.items():
                    if lo <= price <= hi and qty > 0:
                        samples.append(qty)
        if not samples:
            return _REF_FALLBACK
        return float(np.percentile(samples, _REF_PERCENTILE)) or _REF_FALLBACK


def load_heatmap(config) -> Optional[HeatmapData]:
    if not config.has_dataset():
        return None
    selected = select_day_files(Path(config.dataset_path()), config.date, config.days_back)
    if not selected:
        return None
    df = pd.concat([pd.read_parquet(f) for f in selected])
    df = _apply_time_filter(df, config.time_start, config.time_end)
    if df.empty:
        return None
    data = HeatmapData(df)
    data._source_files = [str(f) for f in selected]
    return data


# ── Aggregation pyramid ────────────────────────────────────────────────
class HeatmapPyramid:
    """Multi-resolution max-depth grid for fast zoomed-out rendering.

    Each level is a max-pooled (over time) grid of resting size on a fixed
    absolute price grid, plus the bid/ask envelope per time bucket.
    """

    def __init__(self, p0: float, tick: float, nbins: int, levels: list,
                 ref_eth: float = 0.0, ref_rth: float = 0.0) -> None:
        self.p0 = p0
        self.tick = tick
        self.nbins = nbins
        self.levels = levels  # list of dict: {B, depth(int16 [nb,nbins]), o, h, l, c}
        # per-session color reference (full-color qty); RTH books are larger
        self.ref_eth = ref_eth
        self.ref_rth = ref_rth

    def pick_level(self, secs_per_pixel: float) -> int:
        """Index of the finest level whose bucket is >= secs_per_pixel."""
        target = max(1.0, secs_per_pixel)
        best = 0
        for i, lv in enumerate(self.levels):
            if lv["B"] <= target:
                best = i
            else:
                break
        return best

    def bin_of(self, price: float) -> int:
        return int(round((price - self.p0) / self.tick))

    def price_of_bin(self, b: int) -> float:
        return self.p0 + b * self.tick


def _scatter_chunk(bid_slice, ask_slice, row_offset, p0, tick, nbins, B0):
    """Build a partial flat max-depth grid for one contiguous row slice.

    `row_offset` must be aligned to B0 so buckets never split across chunks.
    Returns (bucket_lo, depth[nb_chunk, nbins] int16). Top-level so it can run
    in a worker process.
    """
    m = len(bid_slice)
    nb = (m + B0 - 1) // B0
    base = np.zeros(nb * nbins, dtype=np.int16)
    keys, vals, rb, rc = [], [], [], []

    def flush():
        if not keys:
            return
        pr = np.array(keys, dtype=np.float64)
        v = np.array(vals, dtype=np.float64)
        bk = np.repeat(np.array(rb, dtype=np.int64), np.array(rc, dtype=np.int64))
        bins = np.rint((pr - p0) / tick).astype(np.int64)
        ok = (bins >= 0) & (bins < nbins) & (v > 0)
        if ok.any():
            np.maximum.at(base, bk[ok] * nbins + bins[ok],
                          np.minimum(v[ok], _PYR_MAX_DEPTH).astype(np.int16))
        keys.clear(); vals.clear(); rb.clear(); rc.clear()

    for j in range(m):
        lb = j // B0
        for raw in (bid_slice[j], ask_slice[j]):
            if not raw or isinstance(raw, float):
                continue
            try:
                obj = _loads(raw)
            except (ValueError, TypeError):
                continue
            if not obj:
                continue
            keys.extend(obj.keys()); vals.extend(obj.values())
            rb.append(lb); rc.append(len(obj))
        if (j + 1) % 4000 == 0:
            flush()
    flush()
    return row_offset // B0, base.reshape(nb, nbins)


def _downsample(depth, o, h, l, c, factor):
    """Coarsen one level: depth max-pooled; OHLC aggregated (O=first, H=max,
    L=min, C=last) over each group of `factor` buckets."""
    nb = depth.shape[0]
    nb2 = (nb + factor - 1) // factor
    pad = nb2 * factor - nb
    if pad:
        depth = np.concatenate([depth, np.zeros((pad, depth.shape[1]), depth.dtype)])
        # edge-pad OHLC so the final partial group keeps real first/last values
        o = np.pad(o, (0, pad), mode="edge")
        h = np.pad(h, (0, pad), mode="edge")
        l = np.pad(l, (0, pad), mode="edge")
        c = np.pad(c, (0, pad), mode="edge")
    d2 = depth.reshape(nb2, factor, depth.shape[1]).max(axis=1)
    o2 = o.reshape(nb2, factor)[:, 0]
    h2 = h.reshape(nb2, factor).max(axis=1)
    l2 = l.reshape(nb2, factor).min(axis=1)
    c2 = c.reshape(nb2, factor)[:, -1]
    return d2, o2.astype(np.float32), h2.astype(np.float32), l2.astype(np.float32), c2.astype(np.float32)


def _scatter_base_mp(data, p0, tick, nbins, B0, nb0, n_workers,
                     progress_cb=None, cancel_cb=None):
    """Build the base max-depth grid across a process pool. None on failure."""
    from concurrent.futures import ProcessPoolExecutor
    n = data.n
    per = ((n // B0) // n_workers + 1) * B0   # chunk size, aligned to B0
    bounds = []
    s = 0
    while s < n:
        e = min(n, s + per)
        bounds.append((s, e))
        s = e
    base = np.zeros((nb0, nbins), dtype=np.int16)
    done = 0
    try:
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            futs = {ex.submit(_scatter_chunk, data._bid_raw[s:e], data._ask_raw[s:e],
                              s, p0, tick, nbins, B0): (e - s) for s, e in bounds}
            from concurrent.futures import as_completed
            for fut in as_completed(futs):
                blo, part = fut.result()
                base[blo:blo + part.shape[0]] = np.maximum(base[blo:blo + part.shape[0]], part)
                done += futs[fut]
                if progress_cb is not None:
                    progress_cb(done, n)
                if cancel_cb is not None and cancel_cb():
                    for f in futs:
                        f.cancel()
                    return None
    except Exception:
        return None
    return base


def _scatter_base_sp(data, p0, tick, nbins, B0, nb0, progress_cb=None, cancel_cb=None):
    """Single-process fallback for the base grid."""
    n = data.n
    base = np.zeros((nb0, nbins), dtype=np.int16)
    # reuse the chunk builder in slabs so progress + cancel stay responsive
    slab = 8000
    s = 0
    while s < n:
        e = min(n, s + slab)
        bl, part = _scatter_chunk(data._bid_raw[s:e], data._ask_raw[s:e], s,
                                  p0, tick, nbins, B0)
        base[bl:bl + part.shape[0]] = np.maximum(base[bl:bl + part.shape[0]], part)
        if progress_cb is not None:
            progress_cb(min(e, n), n)
        if cancel_cb is not None and cancel_cb():
            return None
        s = e
    return base


def _build_pyramid(data: "HeatmapData", tick: float, crop_ticks: int,
                   rth_lo: int, rth_hi: int,
                   progress_cb=None, cancel_cb=None) -> Optional[HeatmapPyramid]:
    n = data.n
    fl = data.l[np.isfinite(data.l)]
    fh = data.h[np.isfinite(data.h)]
    if fl.size == 0 or fh.size == 0:
        return None
    margin_ticks = max(int(crop_ticks), _PYR_MIN_MARGIN_TICKS)
    margin = margin_ticks * tick
    p0 = float(np.floor((fl.min() - margin) / tick) * tick)
    p1 = float(np.ceil((fh.max() + margin) / tick) * tick)
    nbins = int(round((p1 - p0) / tick)) + 1
    if nbins <= 0:
        return None

    B0 = _PYR_BASE_SEC
    nb0 = (n + B0 - 1) // B0

    n_workers = min(8, (os.cpu_count() or 2))
    base = None
    if n_workers >= 2 and n >= 20000:
        base = _scatter_base_mp(data, p0, tick, nbins, B0, nb0, n_workers,
                                progress_cb=progress_cb, cancel_cb=cancel_cb)
    if base is None:
        if cancel_cb is not None and cancel_cb():
            return None
        base = _scatter_base_sp(data, p0, tick, nbins, B0, nb0,
                                progress_cb=progress_cb, cancel_cb=cancel_cb)
    if base is None:
        return None

    # OHLC per base bucket (O=first, H=max, L=min, C=last over the bucket)
    pad0 = nb0 * B0 - n
    oo = np.pad(data.o, (0, pad0), mode="edge") if pad0 else data.o
    hh = np.pad(data.h, (0, pad0), mode="edge") if pad0 else data.h
    ll = np.pad(data.l, (0, pad0), mode="edge") if pad0 else data.l
    cc = np.pad(data.c, (0, pad0), mode="edge") if pad0 else data.c
    o0 = oo.reshape(nb0, B0)[:, 0].astype(np.float32)
    h0 = hh.reshape(nb0, B0).max(axis=1).astype(np.float32)
    l0 = ll.reshape(nb0, B0).min(axis=1).astype(np.float32)
    c0 = cc.reshape(nb0, B0)[:, -1].astype(np.float32)

    levels = [{"B": B0, "depth": base, "o": o0, "h": h0, "l": l0, "c": c0}]
    cd, co, ch, cl, cc2, cB = base, o0, h0, l0, c0, B0
    for _ in range(_PYR_EXTRA_LEVELS):
        if cd.shape[0] < 2:
            break
        cd, co, ch, cl, cc2 = _downsample(cd, co, ch, cl, cc2, _PYR_FACTOR)
        cB *= _PYR_FACTOR
        levels.append({"B": cB, "depth": cd, "o": co, "h": ch, "l": cl, "c": cc2})

    # per-session color reference: high percentile of resting size so typical
    # liquidity stays dark and only large walls glow (Bookmap-style). RTH and
    # ETH get separate refs because RTH books are far larger.
    is_rth = (data.tod_min >= rth_lo) & (data.tod_min < rth_hi)
    if base.shape[0] == n:
        rth_rows, eth_rows = base[is_rth], base[~is_rth]
    else:                       # base bucketed (B0>1) — fall back to all rows
        rth_rows = eth_rows = base

    def _pct(grid):
        nz = grid[grid > 0]
        v = float(np.percentile(nz, _PYR_REF_PERCENTILE)) if nz.size else 0.0
        return v or _REF_FALLBACK

    ref_rth = _pct(rth_rows)
    ref_eth = _pct(eth_rows)

    return HeatmapPyramid(p0, tick, nbins, levels, ref_eth=ref_eth, ref_rth=ref_rth)


# ── disk cache ─────────────────────────────────────────────────────────
def _cache_path(config) -> Path:
    safe = f"{config.date}_db{config.days_back}_{config.time_start}-{config.time_end}"
    safe = safe.replace(":", "")
    return Path(config.dataset_path()) / ".heatmap_cache" / f"{safe}.npz"


def _source_signature(files) -> list:
    sig = []
    for f in files or []:
        try:
            st = os.stat(f)
            sig.append([os.path.basename(f), int(st.st_mtime), int(st.st_size)])
        except OSError:
            sig.append([os.path.basename(f), 0, 0])
    return sig


def _build_params(crop_ticks: int, rth_lo: int, rth_hi: int) -> dict:
    return {
        "version": _CACHE_VERSION,
        "base": _PYR_BASE_SEC,
        "factor": _PYR_FACTOR,
        "extra": _PYR_EXTRA_LEVELS,
        "margin": max(int(crop_ticks), _PYR_MIN_MARGIN_TICKS),
        "rth": [int(rth_lo), int(rth_hi)],
    }


def _load_cache(path: Path, files, params) -> Optional[HeatmapPyramid]:
    if not path.is_file():
        return None
    try:
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            if meta.get("params") != params:
                return None
            if meta.get("sig") != _source_signature(files):
                return None
            levels = []
            for k in range(int(meta["nlevels"])):
                levels.append({
                    "B": int(meta["B"][k]),
                    "depth": z[f"depth{k}"],
                    "o": z[f"o{k}"], "h": z[f"h{k}"],
                    "l": z[f"l{k}"], "c": z[f"c{k}"],
                })
            return HeatmapPyramid(float(meta["p0"]), float(meta["tick"]),
                                  int(meta["nbins"]), levels,
                                  ref_eth=float(meta.get("ref_eth", 0.0)),
                                  ref_rth=float(meta.get("ref_rth", 0.0)))
    except (OSError, ValueError, KeyError):
        return None


def _save_cache(path: Path, pyr: HeatmapPyramid, files, params) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "params": params,
            "sig": _source_signature(files),
            "p0": pyr.p0, "tick": pyr.tick, "nbins": pyr.nbins,
            "ref_eth": pyr.ref_eth, "ref_rth": pyr.ref_rth,
            "nlevels": len(pyr.levels),
            "B": [lv["B"] for lv in pyr.levels],
        }
        arrays = {"meta": np.array(json.dumps(meta))}
        for k, lv in enumerate(pyr.levels):
            arrays[f"depth{k}"] = lv["depth"]
            arrays[f"o{k}"] = lv["o"]
            arrays[f"h{k}"] = lv["h"]
            arrays[f"l{k}"] = lv["l"]
            arrays[f"c{k}"] = lv["c"]
        np.savez_compressed(path, **arrays)
    except OSError:
        pass


def build_or_load_pyramid(data: "HeatmapData", config, tick: float,
                          crop_ticks: int = 256, rth_lo: int = 570, rth_hi: int = 960,
                          progress_cb=None, cancel_cb=None,
                          use_cache: bool = True) -> Optional[HeatmapPyramid]:
    """Load the cached aggregation pyramid, or build it (and cache it).

    Returns None if cancelled or unbuildable (caller falls back to the exact
    per-second render path).
    """
    if data is None or data.n == 0:
        return None
    files = getattr(data, "_source_files", None)
    params = _build_params(crop_ticks, rth_lo, rth_hi)
    path = _cache_path(config)
    if use_cache:
        pyr = _load_cache(path, files, params)
        if pyr is not None:
            return pyr
    pyr = _build_pyramid(data, tick, crop_ticks, rth_lo, rth_hi,
                         progress_cb=progress_cb, cancel_cb=cancel_cb)
    if pyr is not None and use_cache:
        _save_cache(path, pyr, files, params)
    return pyr
