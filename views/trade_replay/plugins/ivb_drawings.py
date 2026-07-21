"""Initial-balance volume profile with its key levels marked.

Draws a VP over the initial balance window (end-exclusive: 30 minutes from
09:30 covers 09:30..09:59), horizontal lines at its VAH/VAL (blue) and POC
(orange), and a white vertical line marking the end of the IB period.

Override defaults in the Params box, e.g.:  initial_balance_minutes=60
"""
NAME = "IVB drawings"

PARAMS = {
    "start_time": "09:30",
    "initial_balance_minutes": 30,
}

MINUTE_NS = 60 * 1_000_000_000


def run(ctx):
    start = ctx.param("start_time")
    minutes = int(ctx.param("initial_balance_minutes"))

    if not ctx.footprints:
        ctx.log("No footprint chart open — volume profile needs footprint data")

    for chart in ctx.footprints:
        t0 = chart.to_ts(start)
        t1 = t0 + minutes * MINUTE_NS - 1   # 1 ns short of the next bar -> end-exclusive

        vp = chart.draw_profile(t0, t1)
        if vp is None:
            ctx.log(f"{chart.name}: no profile (chart empty or no volume in range)")
            continue

        chart.hline(vp["vah"], color="dodgerblue", label="IB VAH")
        chart.hline(vp["val"], color="dodgerblue", label="IB VAL")
        chart.hline(vp["poc"], color="orange", label="IB POC")
        chart.vline(t1, color="white", label="IB end")

        ctx.log(f"{chart.name}: IB {start}+{minutes}m  "
                f"POC {vp['poc']:.2f}  VAH {vp['vah']:.2f}  VAL {vp['val']:.2f}  "
                f"vol {vp['total']:.0f}")
