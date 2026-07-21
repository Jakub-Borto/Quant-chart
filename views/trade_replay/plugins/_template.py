"""Plugin cheat-sheet. Copy this file, drop the leading underscore, edit, run.

Files starting with "_" are hidden from the Plugins menu. Plugins are
re-imported FRESH on every run — edit and re-run, no app restart needed.

A plugin is just:

    NAME = "Shown in the plugin selector"       # optional

    PARAMS = {                                  # optional defaults, merged
        "start_time": "09:30",                  # into ctx.params — entries
        "initial_balance_minutes": 30,          # in the Params box override
    }                                           # these per key

    def run(ctx):
        ...

── ctx ────────────────────────────────────────────────────────────────
ctx.trade        pd.Series of the selected trade: .date .direction
                 .entry_time .exit_time .entry_price .exit_price .sl .tp
                 .exit_reason .ticks .trade_type ...
ctx.notes        parsed notes JSON as a dict ({} if the file has none)
ctx.params       dict from the Params box, e.g. "start=09:30 mult=2 fast"
                 -> {"start": "09:30", "mult": 2, "fast": True}
ctx.param(k, d)  ctx.params.get with a default
ctx.charts       all open footprint/OHLCV charts (heatmap never included)
ctx.footprints   only footprint charts   ctx.ohlcv   only OHLCV charts
ctx.chart        first footprint chart, else first chart, else None
ctx.log(*args)   collect output — shown in the Plugin output window

── chart (ChartHandle) ────────────────────────────────────────────────
Times: "09:30" (chart's anchor date, Globex-corrected: "18:30" = previous
evening), "2026-04-29 10:15", pd.Timestamp / datetime, or epoch ns.
Colors: names ("orange", "dodgerblue"), "#rrggbb", or (r, g, b[, a]).

chart.hline(price, color="orange", label=None, width=1.0, dash=True)
chart.vline(time, color="#888888", label=None, width=1.0)
chart.ray(time, price, color="#4a90d9", label=None, width=1.6)
chart.box(t1, t2, price1, price2, color="#4a90d9", fill_alpha=40)
chart.text(time, price, "hello", color="white", px=10)
chart.position("long"|"short", t1, t2, entry, tp=None, sl=None)
                 -> a real editable position drawing (standard colors)
chart.profile(t1, t2)       -> {"poc","vah","val","total","max_total",
                                "levels": {price: {...}}} or None
                               (compute only; always None on OHLCV charts)
chart.draw_profile(t1, t2)  -> same dict, but also draws the profile
chart.vwap(on=True, vtype=None)   # bar_globex|bar_rth|tick_globex|tick_rth
chart.clear()               # clear plugin annotations on this chart
chart.clear(everything=True)      # wipe ALL drawings (like the Clear button)
chart.set_date("2026-04-29")
chart.to_ts(time)           # -> epoch ns, for time math (e.g. + 30*60*1e9)
chart.name / chart.date / chart.is_footprint
chart.window / chart.canvas       # escape hatches to the real objects

── cleanup rules ──────────────────────────────────────────────────────
- hline/vline/ray/box/text are "annotations": wiped by every Load to
  charts, by Plugins ▾ -> Clear annotations, and by the chart's Clear.
- draw_profile() and position() create REAL chart drawings — remove them
  with the chart's own delete tool or Clear button.
"""


def run(ctx):
    chart = ctx.chart
    if chart is None:
        ctx.log("open a chart first")
        return
    trade = ctx.trade
    chart.vline(trade.entry_time, color="yellow", label="entry")
    chart.hline(trade.entry_price, color="yellow", label="entry px")
    ctx.log("hello from the template:", trade.date, trade.direction)
