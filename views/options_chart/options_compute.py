"""Per-timestamp exposure computation for the options exposure chart.

Turns a column slice of an OptionsDay (state at one slider time) into
per-strike exposure bars: implied vols -> Black-76 greeks -> signed dealer
position -> unit scaling -> per-strike aggregation.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

import numpy as np
import pandas as pd

from views.options_chart.black76 import greeks, implied_vol, fill_iv_by_strike

YEAR_NS = 365 * 86400 * 10**9
T_MIN = 60 * 10**9 / YEAR_NS          # one minute, in years

EXPIRY_BUCKETS = ["All", "0DTE", "This Week", "Next Week",
                  "This Month", "Next Month", "This Quarter", "This Year"]

GREEK_LABELS = {"delta": "Delta", "gamma": "Gamma", "vanna": "Vanna", "charm": "Charm"}
UNIT_LABELS = {"pct": "$ / 1% move", "point": "$ / 1 point", "contracts": "Contracts"}


@dataclass(frozen=True)
class ExposureParams:
    greek: str        # "delta" | "gamma" | "vanna" | "charm"
    oi_source: str    # "open_interest" | "est_oi" | "dealer_flow"
    sign_mode: str    # "calls_long" | "puts_long" | "all_long"
    units: str        # "pct" | "point" | "contracts"
    bucket: str       # one of EXPIRY_BUCKETS
    r: float


@dataclass
class StrikeExposure:
    strikes: np.ndarray      # float64 [n_strikes] (ref to day.strikes_sorted)
    total: np.ndarray        # float64 [n_strikes] = primary + fallback
    primary: np.ndarray      # full-color component
    fallback: np.ndarray     # dimmed component (est-OI fallback under dealer_flow)
    call_part: np.ndarray
    put_part: np.ndarray
    n_contracts: np.ndarray  # int64, contracts included per strike
    F: float
    time: pd.Timestamp
    units_label: str


def bucket_mask(day, bucket: str, anchor: datetime.date) -> np.ndarray:
    """Boolean contract mask for a calendar expiry bucket relative to anchor."""
    if bucket == "All":
        return np.ones(day.n_inst, dtype=bool)
    exp_days = day.expiry_ns // (86400 * 10**9)
    # expiry timestamps are NY-local wall times stored tz-aware; epoch-day of the
    # UTC instant can differ from the NY calendar day only for late-evening
    # expiries, which don't exist (settles are 09:30/16:00 NY) — safe to floor.
    exp_dates = np.array([datetime.date.fromordinal(719163 + int(d)) for d in
                          np.unique(exp_days)])
    lookup = {int(d): dt for d, dt in zip(np.unique(exp_days), exp_dates)}
    dates = np.array([lookup[int(d)] for d in exp_days])

    monday = anchor - datetime.timedelta(days=anchor.weekday())
    if bucket == "0DTE":
        keep = dates == anchor
    elif bucket == "This Week":
        keep = (dates >= anchor) & (dates <= monday + datetime.timedelta(days=6))
    elif bucket == "Next Week":
        keep = (dates >= monday + datetime.timedelta(days=7)) & \
               (dates <= monday + datetime.timedelta(days=13))
    elif bucket == "This Month":
        keep = np.array([d.year == anchor.year and d.month == anchor.month for d in dates])
    elif bucket == "Next Month":
        ny, nm = (anchor.year, anchor.month + 1) if anchor.month < 12 else (anchor.year + 1, 1)
        keep = np.array([d.year == ny and d.month == nm for d in dates])
    elif bucket == "This Quarter":
        q = (anchor.month - 1) // 3
        keep = np.array([d.year == anchor.year and (d.month - 1) // 3 == q for d in dates])
    elif bucket == "This Year":
        keep = np.array([d.year == anchor.year for d in dates])
    else:
        keep = np.ones(day.n_inst, dtype=bool)
    return keep


def iv_at(day, t: int, r: float, cache: dict) -> np.ndarray:
    """Implied vols for all contracts at time index t (cached per t)."""
    iv = cache.get(t)
    if iv is not None:
        return iv
    mid = (day.bid[:, t] + day.ask[:, t]).astype(np.float64) * 0.5
    T = (day.expiry_ns - day.times_ns[t]) / YEAR_NS
    F = day.F[t]
    iv = implied_vol(mid, F, day.strike, T, r, day.cp)
    iv = fill_iv_by_strike(iv, day.strike, day.expiry_ns)
    cache[t] = iv
    return iv


def compute_exposure(day, t: int, params: ExposureParams,
                     iv_cache: dict, result_cache: dict) -> StrikeExposure | None:
    key = (t, params)
    hit = result_cache.get(key)
    if hit is not None:
        return hit

    F = float(day.F[t])
    if not np.isfinite(F) or F <= 0:
        return None

    T = (day.expiry_ns - day.times_ns[t]) / YEAR_NS
    iv = iv_at(day, t, params.r, iv_cache)
    bkey = ("_bucket", params.bucket)
    bmask = result_cache.get(bkey)
    if bmask is None:
        bmask = bucket_mask(day, params.bucket, pd.Timestamp(day.date).date())
        result_cache[bkey] = bmask
    include = (T > T_MIN) & bmask & np.isfinite(iv)

    delta, gamma, vanna, charm = greeks(F, day.strike, T, iv, params.r, day.cp)
    g = {"delta": delta, "gamma": gamma, "vanna": vanna, "charm": charm}[params.greek]

    # Signed dealer position per contract
    sign_c = {"calls_long": day.cp.astype(np.float64),
              "puts_long": -day.cp.astype(np.float64),
              "all_long": np.ones(day.n_inst)}[params.sign_mode]
    if params.oi_source == "open_interest":
        pos_primary = sign_c * np.nan_to_num(day.oi[:, t].astype(np.float64))
        pos_fallback = np.zeros(day.n_inst)
    elif params.oi_source == "est_oi":
        pos_primary = sign_c * np.nan_to_num(day.est_oi[:, t].astype(np.float64))
        pos_fallback = np.zeros(day.n_inst)
    else:
        # dealer_flow is our own exposure algorithm — the sign-assumption combo
        # must not affect this source. Data sign where traded; the est-OI
        # fallback uses the FIXED naive convention (calls long / puts short).
        flow = day.flow[:, t].astype(np.float64)
        traded = np.isfinite(flow)
        sign_fixed = day.cp.astype(np.float64)
        pos_primary = np.where(traded, np.nan_to_num(flow), 0.0)
        pos_fallback = np.where(traded, 0.0,
                                sign_fixed * np.nan_to_num(day.est_oi[:, t].astype(np.float64)))

    # Unit scaling (vanna is per 1.00 sigma -> /100 per vol-pt; charm per year -> /365 per day)
    mult = day.mult
    if params.units == "contracts":
        u = 1.0
    elif params.units == "point":
        u = mult
    else:  # "pct"
        u = mult * (F * F * 0.01 if params.greek == "gamma" else F)
    if params.greek == "vanna":
        u /= 100.0
    elif params.greek == "charm":
        u /= 365.0

    e_primary = np.where(include, g * pos_primary * u, 0.0)
    e_fallback = np.where(include, g * pos_fallback * u, 0.0)
    e_primary = np.nan_to_num(e_primary)
    e_fallback = np.nan_to_num(e_fallback)

    n_s = day.n_strikes
    primary = np.zeros(n_s)
    fallback = np.zeros(n_s)
    call_part = np.zeros(n_s)
    put_part = np.zeros(n_s)
    n_contracts = np.zeros(n_s, dtype=np.int64)
    slots = day.strike_slot
    np.add.at(primary, slots, e_primary)
    np.add.at(fallback, slots, e_fallback)
    e_total = e_primary + e_fallback
    is_call = day.cp > 0
    np.add.at(call_part, slots[is_call], e_total[is_call])
    np.add.at(put_part, slots[~is_call], e_total[~is_call])
    np.add.at(n_contracts, slots[include], 1)

    res = StrikeExposure(
        strikes=day.strikes_sorted, total=primary + fallback,
        primary=primary, fallback=fallback,
        call_part=call_part, put_part=put_part, n_contracts=n_contracts,
        F=F, time=day.times[t], units_label=UNIT_LABELS[params.units],
    )
    result_cache[key] = res
    return res
