"""Black-76 options math on futures — pure numpy, no scipy, no Qt.

Conventions:
    cp    +1 for calls, -1 for puts (int8 array)
    F     underlying futures price (scalar or array)
    K     strike
    T     time to expiry in YEARS (365-day)
    sigma implied volatility (annualized, 1.00 = 100%)
    r     continuously compounded discount rate
Vanna is per 1.00 of sigma; charm is per YEAR — callers rescale to
per-vol-point / per-day.
"""
from __future__ import annotations

import numpy as np

_SQRT_2PI = np.sqrt(2.0 * np.pi)
_INV_SQRT2 = 1.0 / np.sqrt(2.0)


def norm_pdf(x: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * x * x) / _SQRT_2PI


def _erf(x: np.ndarray) -> np.ndarray:
    """Vectorized Abramowitz & Stegun 7.1.26 erf approximation (|err| < 1.5e-7)."""
    sign = np.sign(x)
    z = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * z)
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741
               + t * (-1.453152027 + t * 1.061405429))))
    return sign * (1.0 - poly * np.exp(-z * z))


def norm_cdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + _erf(np.asarray(x, dtype=np.float64) * _INV_SQRT2))


def _d1_d2(F, K, T, sigma):
    v = sigma * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sigma * sigma * T) / v
    return d1, d1 - v


def price(F, K, T, sigma, r, cp) -> np.ndarray:
    d1, d2 = _d1_d2(F, K, T, sigma)
    disc = np.exp(-r * T)
    return cp * disc * (F * norm_cdf(cp * d1) - K * norm_cdf(cp * d2))


def greeks(F, K, T, sigma, r, cp):
    """Return (delta, gamma, vanna, charm) — vectorized, NaN where inputs are NaN.

    vanna = dDelta/dSigma per 1.00 of sigma; charm = dDelta/dt per year.
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        d1, d2 = _d1_d2(F, K, T, sigma)
        disc = np.exp(-r * T)
        pdf1 = norm_pdf(d1)
        delta = cp * disc * norm_cdf(cp * d1)
        gamma = disc * pdf1 / (F * sigma * np.sqrt(T))
        vanna = -disc * pdf1 * d2 / sigma
        charm_call = disc * (r * norm_cdf(d1) + pdf1 * d2 / (2.0 * T))
        charm = np.where(cp > 0, charm_call, charm_call - r * disc)
    return delta, gamma, vanna, charm


def implied_vol(mid, F, K, T, r, cp, n_iter: int = 24) -> np.ndarray:
    """Vectorized safeguarded-Newton Black-76 implied vol. NaN where unsolvable.

    Works on the undiscounted price so the discount factor drops out of the
    iteration. The undiscounted price is strictly increasing in sigma, which
    makes the [lo, hi] bracket + bisection fallback globally convergent.
    """
    mid = np.asarray(mid, dtype=np.float64)
    K = np.asarray(K, dtype=np.float64)
    T = np.asarray(T, dtype=np.float64)
    cp = np.asarray(cp, dtype=np.float64)

    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        p_und = mid * np.exp(r * T)                      # undiscounted target
        intrinsic = np.maximum(cp * (F - K), 0.0)
        ok = (
            np.isfinite(p_und) & np.isfinite(K) & (K > 0) & (T > 0)
            & (mid > 0)
            & (p_und > intrinsic + 0.01)                 # at/below intrinsic: no vol info
            & (p_und < np.where(cp > 0, F, K))           # upper no-arbitrage bound
        )

        sqrt_T = np.sqrt(T)
        # Brenner-Subrahmanyam initial guess
        sigma = np.clip(_SQRT_2PI / sqrt_T * p_und / F, 0.05, 3.0)
        lo = np.full_like(sigma, 1e-3)
        hi = np.full_like(sigma, 10.0)
        for _ in range(n_iter):
            d1, d2 = _d1_d2(F, K, T, sigma)
            model = cp * (F * norm_cdf(cp * d1) - K * norm_cdf(cp * d2))
            diff = model - p_und
            hi = np.where(diff > 0, sigma, hi)
            lo = np.where(diff < 0, sigma, lo)
            vega = F * norm_pdf(d1) * sqrt_T
            step = sigma - diff / np.maximum(vega, 1e-12)
            mid_br = 0.5 * (lo + hi)
            sigma = np.where(np.isfinite(step) & (step > lo) & (step < hi), step, mid_br)

        d1, d2 = _d1_d2(F, K, T, sigma)
        diff = cp * (F * norm_cdf(cp * d1) - K * norm_cdf(cp * d2)) - p_und
        iv = np.where(ok & (np.abs(diff) < 0.05), sigma, np.nan)
    return iv


def fill_iv_by_strike(iv: np.ndarray, strike: np.ndarray, expiry_ns: np.ndarray) -> np.ndarray:
    """Fill NaN IVs by linear interpolation across strikes within each expiry.

    Calls and puts at the same strike share vol (put-call parity on futures), so
    duplicate strikes are averaged. Wings extrapolate flat (np.interp clamping).
    Expiries with fewer than 2 valid points are left NaN.
    """
    out = iv.copy()
    missing = ~np.isfinite(iv)
    if not missing.any():
        return out
    for exp in np.unique(expiry_ns[missing]):
        grp = expiry_ns == exp
        valid = grp & np.isfinite(iv)
        if valid.sum() < 2:
            continue
        ks, inv = np.unique(strike[valid], return_inverse=True)
        sums = np.zeros(len(ks))
        counts = np.zeros(len(ks))
        np.add.at(sums, inv, iv[valid])
        np.add.at(counts, inv, 1.0)
        if len(ks) < 2:
            continue
        tgt = grp & missing
        out[tgt] = np.interp(strike[tgt], ks, sums / counts)
    return out
