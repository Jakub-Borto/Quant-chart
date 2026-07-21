"""Plugin API + loader for the trade replay window.

A plugin is a Python file in ``views/trade_replay/plugins/`` defining::

    NAME = "My plugin"          # optional, shown in the Plugins menu

    def run(ctx):
        ...

Plugins are re-imported **fresh on every run** — edit the file and re-run,
no app restart needed (unlike everything else in this app).

``ctx`` is a :class:`PluginContext`; each open footprint/OHLCV chart is a
:class:`ChartHandle`. Times passed to chart methods may be ``"HH:MM"``
(resolved on that chart's anchor date, session-corrected for Globex),
``"YYYY-MM-DD HH:MM"``, a ``pd.Timestamp``/``datetime`` (naive → New York),
or raw epoch nanoseconds. Colors may be names (``"orange"``), ``"#rrggbb"``,
or rgb(a) tuples.
"""
import importlib.util
import re
import shlex
from pathlib import Path

import numpy as np
import pandas as pd
from PyQt6.QtGui import QColor

from core.drawing_anchors import times_ns_of
from views.footprint_chart.volume_profile import compute_profile
from views.footprint_chart.window import FootprintWindow
from views.ohlcv_chart.window import OhlcvWindow

NY_TZ = "America/New_York"


# ── coercion helpers ───────────────────────────────────────────────────
def _resolve_color(c) -> tuple:
    """Any reasonable color spec -> (r, g, b, a). Loud on typos."""
    if isinstance(c, (tuple, list)) and len(c) in (3, 4):
        rgba = tuple(int(v) for v in c)
        return rgba if len(rgba) == 4 else rgba + (255,)
    if isinstance(c, str):
        qc = QColor(c)
        if qc.isValid():
            return (qc.red(), qc.green(), qc.blue(), qc.alpha())
    raise ValueError(
        f"Unknown color {c!r} — use a name ('orange'), '#rrggbb', or an (r,g,b[,a]) tuple")


_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


class ChartHandle:
    """Plugin-facing wrapper around one footprint or OHLCV chart window."""

    def __init__(self, window) -> None:
        self.window = window
        self.canvas = window.canvas
        self.is_footprint = isinstance(window, FootprintWindow)

    # ── info ───────────────────────────────────────────────────────────
    @property
    def name(self) -> str:
        kind = "footprint" if self.is_footprint else "ohlcv"
        cfg = self.window.config
        return f"{kind} · {cfg.asset} · {cfg.tf_value}{cfg.tf_unit[0].lower()}"

    @property
    def date(self) -> str:
        return self.window.config.date

    def _data(self):
        d = self.canvas.data
        return d if d is not None and len(d) else None

    # ── time coercion ──────────────────────────────────────────────────
    def to_ts(self, t) -> int:
        """Public alias: anything time-like -> epoch ns (for time math)."""
        return self._to_ts(t)

    def _to_ts(self, t) -> int:
        """Anything time-like -> epoch ns (America/New_York)."""
        if isinstance(t, (int, np.integer)):
            return int(t)
        if isinstance(t, str):
            s = t.strip()
            m = _HHMM_RE.match(s)
            if m:
                def clock_on(day_offset: int) -> int:
                    day = (pd.Timestamp(self.date)
                           + pd.Timedelta(days=day_offset)).date()
                    return pd.Timestamp(f"{day} {s}", tz=NY_TZ).value

                ns = clock_on(0)
                # session correction: a Globex day runs 18:00 (prev evening)
                # to 17:00, so clock times outside the loaded span roll over
                d = self._data()
                if d is not None:
                    tarr = times_ns_of(d)
                    if ns > tarr[-1] and clock_on(-1) >= tarr[0]:
                        ns = clock_on(-1)
                    elif ns < tarr[0] and clock_on(1) <= tarr[-1]:
                        ns = clock_on(1)
                return ns
            ts = pd.Timestamp(s)   # raises on garbage — loud on purpose
            if ts.tzinfo is None:
                ts = ts.tz_localize(NY_TZ)
            return ts.value
        ts = pd.Timestamp(t)
        if ts.tzinfo is None:
            ts = ts.tz_localize(NY_TZ)
        return int(ts.value)

    # ── drawing (annotations — colored, timestamp-anchored) ───────────
    def hline(self, price, color="orange", label=None, width=1.0, dash=True) -> None:
        self.canvas.annotations.append({
            "kind": "hline", "price": float(price),
            "color": _resolve_color(color), "label": label,
            "width": float(width), "dash": bool(dash)})
        self.canvas.update()

    def vline(self, t, color="#888888", label=None, width=1.0) -> None:
        self.canvas.annotations.append({
            "kind": "vline", "ts": self._to_ts(t),
            "color": _resolve_color(color), "label": label,
            "width": float(width)})
        self.canvas.update()

    def ray(self, t, price, color="#4a90d9", label=None, width=1.6) -> None:
        self.canvas.annotations.append({
            "kind": "ray", "ts": self._to_ts(t), "price": float(price),
            "color": _resolve_color(color), "label": label,
            "width": float(width)})
        self.canvas.update()

    def box(self, t1, t2, price1, price2, color="#4a90d9",
            fill_alpha=40, width=1.6) -> None:
        self.canvas.annotations.append({
            "kind": "box", "ts1": self._to_ts(t1), "ts2": self._to_ts(t2),
            "price1": float(price1), "price2": float(price2),
            "color": _resolve_color(color), "fill_alpha": int(fill_alpha),
            "width": float(width)})
        self.canvas.update()

    def text(self, t, price, s, color="white", px=10) -> None:
        self.canvas.annotations.append({
            "kind": "text", "ts": self._to_ts(t), "price": float(price),
            "text": str(s), "color": _resolve_color(color), "px": int(px)})
        self.canvas.update()

    def position(self, direction, t1, t2, entry, tp=None, sl=None) -> None:
        """A real long/short position drawing (standard colors, editable)."""
        d = self._data()
        if d is None:
            return
        t = times_ns_of(d)
        i1 = int(np.clip(np.searchsorted(t, self._to_ts(t1), side="right") - 1,
                         0, len(t) - 1))
        i2 = int(np.clip(np.searchsorted(t, self._to_ts(t2), side="right") - 1,
                         i1, len(t) - 1))
        entry = float(entry)
        tick = self.canvas.tick_size or 0.25
        up = 1.0 if direction == "long" else -1.0
        tp = float(tp) if tp is not None else entry + up * tick
        sl = float(sl) if sl is not None else entry - up * tick
        self.canvas.positions.append({
            "dir": str(direction), "idx1": i1, "idx2": i2,
            "entry": entry, "tp": tp, "sl": sl})
        self.canvas.update()

    # ── volume profile ─────────────────────────────────────────────────
    def profile(self, t1, t2):
        """Compute a volume profile between two times (no drawing).

        Returns {"poc","vah","val","total","max_total","levels"} or None
        (OHLCV charts have no per-price volume; empty range -> None).
        """
        prof = self._compute_profile(t1, t2)
        return self._profile_dict(prof)

    def draw_profile(self, t1, t2):
        """Compute AND draw the volume profile on the chart. Same return."""
        prof = self._compute_profile(t1, t2)
        if prof is not None:
            self.canvas.profiles.append(prof)
            self.canvas.update()
        return self._profile_dict(prof)

    def _compute_profile(self, t1, t2):
        if not self.is_footprint:
            return None
        d = self._data()
        if d is None:
            return None
        t = times_ns_of(d)
        i1 = int(np.clip(np.searchsorted(t, self._to_ts(t1), side="right") - 1,
                         0, len(t) - 1))
        i2 = int(np.clip(np.searchsorted(t, self._to_ts(t2), side="right") - 1,
                         0, len(t) - 1))
        return compute_profile(d, min(i1, i2), max(i1, i2), self.canvas.tick_size)

    @staticmethod
    def _profile_dict(prof):
        if prof is None:
            return None
        return {
            "poc": prof.poc, "vah": prof.vah, "val": prof.val,
            "total": prof.total, "max_total": prof.max_total,
            "levels": {e["p"]: {"total": e["total"], "buy": e["buy"],
                                "sell": e["sell"]}
                       for e in prof.levels.values()},
        }

    # ── layers / misc ──────────────────────────────────────────────────
    def vwap(self, on=True, vtype=None) -> None:
        """Toggle the VWAP layer; vtype: bar_globex|bar_rth|tick_globex|tick_rth."""
        if vtype is not None:
            combo = getattr(self.window, "vwap_type_combo", None)
            i = combo.findData(vtype) if combo is not None else -1
            if i >= 0:
                combo.setCurrentIndex(i)   # signal calls canvas.set_vwap_type
            else:
                self.canvas.set_vwap_type(vtype)
        if bool(on) != self.canvas.layers.get("vwap", False):
            self.canvas.toggle_layer("vwap")   # emits state_changed -> toolbar

    def clear(self, everything=False) -> None:
        """Clear plugin annotations; everything=True wipes ALL drawings."""
        if everything:
            self.canvas.clear_all()
        else:
            self.canvas.clear_annotations()

    def set_date(self, date) -> None:
        self.window.set_date(str(date)[:10])


class PluginContext:
    """What a plugin's run(ctx) receives."""

    def __init__(self, trade, notes, charts, params=None) -> None:
        self.trade = trade          # pd.Series — the selected trade row
        self.notes = notes          # parsed notes dict ({} if none)
        self.charts = charts        # list[ChartHandle]
        self.params = params or {}  # parsed Params box, e.g. {"start": "09:30"}
        self.lines: list = []       # collected ctx.log output

    @property
    def footprints(self):
        return [c for c in self.charts if c.is_footprint]

    @property
    def ohlcv(self):
        return [c for c in self.charts if not c.is_footprint]

    @property
    def chart(self):
        """First footprint chart, else first chart, else None."""
        return (self.footprints or self.charts or [None])[0]

    def param(self, key, default=None):
        return self.params.get(key, default)

    def log(self, *args) -> None:
        self.lines.append(" ".join(str(a) for a in args))


# ── params box parsing ─────────────────────────────────────────────────
def parse_params(text: str) -> dict:
    """'start=09:30 mult=2.5 label="my note" fast' -> typed dict.

    Bare tokens become True flags; values auto-coerce int -> float -> bool
    -> str. Never raises — best effort on malformed input.
    """
    out = {}
    if not text or not text.strip():
        return out
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    for tok in tokens:
        if "=" in tok:
            key, _, raw = tok.partition("=")
            key = key.strip()
            if key:
                out[key] = _coerce(raw)
        elif tok.strip():
            out[tok.strip()] = True
    return out


def _coerce(raw: str):
    s = raw.strip()
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


# ── plugin discovery / running ─────────────────────────────────────────
_NAME_RE = re.compile(r"""^NAME\s*=\s*["'](.+?)["']""", re.MULTILINE)


def plugins_dir() -> Path:
    folder = Path(__file__).parent / "plugins"
    folder.mkdir(exist_ok=True)
    return folder


def discover_plugins() -> list:
    """[(display_name, path)] for plugins/*.py, skipping _-prefixed files."""
    out = []
    for path in sorted(plugins_dir().glob("*.py")):
        if path.name.startswith("_"):
            continue
        name = path.stem.replace("_", " ").title()
        try:
            m = _NAME_RE.search(path.read_text(encoding="utf-8")[:4000])
            if m:
                name = m.group(1)
        except OSError:
            pass
        out.append((name, path))
    return out


def run_plugin(path, ctx: PluginContext) -> None:
    """Import the plugin FRESH and call run(ctx). Exceptions propagate."""
    path = Path(path)
    spec = importlib.util.spec_from_file_location(f"_tr_plugin_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)   # not in sys.modules -> hot-reload
    run = getattr(module, "run", None)
    if not callable(run):
        raise RuntimeError(f"{path.name} does not define a run(ctx) function")
    # plugin-declared defaults: PARAMS = {...}; the Params box overrides per key
    defaults = getattr(module, "PARAMS", None)
    if isinstance(defaults, dict):
        for key, value in defaults.items():
            ctx.params.setdefault(key, value)
    run(ctx)
