"""Coordinate system shared by every chart.

Maps between data space (candle index, price) and screen space (pixels).
Zoom and pan are just mutations of this object — every renderer reads from
it, so the whole chart stays consistent.

Screen layout (set by the widget each paint):
    left .. right   horizontal chart region (after the price axis)
    top  .. bottom  vertical chart region (between delta panel and time axis)
"""
import math


class Viewport:
    GAP_RATIO = 0.025  # gap between candles as a fraction of candle width

    def __init__(self) -> None:
        # data-view state
        self.offset_x: float     = 0.0   # horizontal pan, pixels
        self.candle_w: float     = 80.0  # candle slot body width, pixels
        self.center_price: float = 0.0
        self.scale_y: float      = 1.0   # >1 zooms in (smaller visible range)
        self.price_min: float    = 0.0   # data extent (defines base scale)
        self.price_max: float    = 1.0

        # screen region, pixels (assigned by the widget before each paint)
        self.left: float   = 60.0
        self.top: float    = 28.0
        self.right: float  = 0.0
        self.bottom: float = 0.0

    # ── geometry ──────────────────────────────────────────────────────
    def slot_w(self) -> float:
        return self.candle_w * (1 + self.GAP_RATIO)

    def chart_h(self) -> float:
        return max(1.0, self.bottom - self.top)

    def chart_w(self) -> float:
        return max(1.0, self.right - self.left)

    def price_span(self) -> float:
        span = (self.price_max - self.price_min) / self.scale_y
        return span if span > 1e-12 else 1e-12

    def pixels_per_price(self) -> float:
        return self.chart_h() / self.price_span()

    def tick_px(self, tick_size: float) -> float:
        return tick_size * self.pixels_per_price()

    # ── price <-> y ───────────────────────────────────────────────────
    def price_to_y(self, price: float) -> float:
        vis = self.price_span()
        vmin = self.center_price - vis / 2
        return self.top + self.chart_h() * (1 - (price - vmin) / vis)

    def y_to_price(self, y: float) -> float:
        vis = self.price_span()
        vmax = self.center_price + vis / 2
        return vmax - (y - self.top) / self.chart_h() * vis

    # ── index <-> x ───────────────────────────────────────────────────
    def candle_x(self, i: float) -> float:
        return self.left + i * self.slot_w() - self.offset_x

    def x_to_candle_round(self, x: float) -> int:
        return round((x + self.offset_x - self.left) / self.slot_w())

    def x_to_candle_floor(self, x: float) -> int:
        return math.floor((x + self.offset_x - self.left) / self.slot_w())
