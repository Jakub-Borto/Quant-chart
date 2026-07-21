"""Per-column filter mini-language for the trades table.

Spec grammar (whitespace-tolerant):
    spec := term ("," term)*        comma = OR of terms
    term := CMP value | value ".." value | value
    CMP  := >= | <= | == | = | > | <

Values are numbers for numeric columns, "HH:MM" for time columns, and
"YYYY-MM-DD" for the date column. All matching is vectorized over numpy
arrays; NaN rows never match. Parsers return None on a syntax error so the
UI can flag the field and ignore the filter.
"""
import re

import numpy as np

_CMP_RE = re.compile(r"^(>=|<=|==|=|>|<)\s*(.+)$")
_RANGE_RE = re.compile(r"^(.+?)\.\.(.+)$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _num_token(tok: str):
    try:
        return float(tok)
    except ValueError:
        return None


def _time_token(tok: str):
    m = _TIME_RE.match(tok)
    if m:
        return float(int(m.group(1)) * 60 + int(m.group(2)))
    return _num_token(tok)   # bare minutes also accepted


def _date_token(tok: str):
    m = _DATE_RE.match(tok)
    if m:
        return float(m.group(1) + m.group(2) + m.group(3))
    return None


_TOKEN_PARSERS = {"numeric": _num_token, "time": _time_token,
                  "date": _date_token}

_OPS = {
    ">":  lambda v, x: v > x,
    "<":  lambda v, x: v < x,
    ">=": lambda v, x: v >= x,
    "<=": lambda v, x: v <= x,
    "=":  lambda v, x: np.isclose(v, x),
    "==": lambda v, x: np.isclose(v, x),
}


def parse_spec(spec: str, kind: str = "numeric"):
    """Compile a spec into mask_fn(values: np.ndarray) -> bool mask.

    Returns None on a syntax error; empty/blank spec returns a pass-all fn.
    """
    spec = spec.strip()
    if not spec:
        return lambda v: np.ones(len(v), dtype=bool)
    token = _TOKEN_PARSERS[kind]

    term_fns = []
    for raw in spec.split(","):
        raw = raw.strip()
        if not raw:
            return None
        m = _CMP_RE.match(raw)
        if m:
            x = token(m.group(2).strip())
            if x is None:
                return None
            term_fns.append((lambda op, x: lambda v: _OPS[op](v, x))(m.group(1), x))
            continue
        m = _RANGE_RE.match(raw)
        if m:
            a, b = token(m.group(1).strip()), token(m.group(2).strip())
            if a is None or b is None:
                return None
            lo, hi = min(a, b), max(a, b)
            term_fns.append((lambda lo, hi: lambda v: (v >= lo) & (v <= hi))(lo, hi))
            continue
        x = token(raw)
        if x is None:
            return None
        term_fns.append((lambda x: lambda v: np.isclose(v, x))(x))

    def mask_fn(values: np.ndarray) -> np.ndarray:
        v = np.asarray(values, dtype=float)
        out = np.zeros(len(v), dtype=bool)
        with np.errstate(invalid="ignore"):
            for fn in term_fns:
                out |= fn(v)
        return out & ~np.isnan(v)

    return mask_fn


def categorical_mask(values: np.ndarray, checked: set) -> np.ndarray:
    """Multi-select filter. Empty set = pass-all (nothing selected == no filter)."""
    if not checked:
        return np.ones(len(values), dtype=bool)
    return np.isin(np.array([str(v) for v in values]), list(checked))


def compute_mask(trade_set, filters: dict) -> np.ndarray:
    """AND all per-column filters. `filters` maps column -> spec str or set.
    Invalid specs are skipped (the UI flags them separately)."""
    n = len(trade_set)
    mask = np.ones(n, dtype=bool)
    for col, spec in filters.items():
        if col not in trade_set.df.columns:
            continue
        values = trade_set.filter_values(col)
        if isinstance(spec, set):
            mask &= categorical_mask(values, spec)
        else:
            kind = trade_set.column_kind(col)
            fn = parse_spec(spec, kind if kind in ("time", "date") else "numeric")
            if fn is not None:
                mask &= fn(values)
    return mask
