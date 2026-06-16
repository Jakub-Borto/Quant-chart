"""Footprint chart canvas (QPainter).

Renders candles, footprint cells (orders + volume), passive orders, volume
profiles, VWAP lines, big-trade bubbles, and a draggable CVD bottom panel,
with pan, independent X/Y zoom, and H/V-line + volume-profile drawing tools.
"""
import math
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core.viewport import Viewport
from views.footprint_chart.volume_profile import compute_profile
from views.footprint_chart.footprint_settings import (
    OrderFootprintSettings, PassiveOrderSettings, VolumeFootprintSettings,
    BigTradeSettings, GeneralSettings, VolumeProfileSettings,
)

# ── Layout constants (pixels) ─────────────────────────────────────────
DELTA_H       = 0
PRICE_AXIS_W  = 60
TIME_AXIS_H   = 20
HIT_THRESHOLD = 6
HANDLE_R      = 5

# ── Colors ────────────────────────────────────────────────────────────
C_BG          = QColor(13, 17, 23)
C_PANEL       = QColor(19, 27, 42)
C_GRID        = QColor(30, 42, 61)
C_AXIS_TEXT   = QColor(120, 135, 160)
C_PANEL_LINE  = QColor(42, 58, 82)

C_DELTA_POS   = QColor(68, 170, 153)
C_DELTA_NEG   = QColor(204, 85, 85)

C_BULL_STROKE = QColor(70, 210, 100)
C_BULL_BODY   = QColor(55, 190, 85)
C_BEAR_STROKE = QColor(160, 100, 205)
C_BEAR_BODY   = QColor(148, 90, 196)

C_FP_BASE     = QColor(196, 196, 196)   # balanced cell (light gray)
C_FP_BUY      = QColor(46, 200, 78)      # buy-dominant target (green)
C_FP_SELL     = QColor(150, 92, 198)     # sell-dominant target (purple)
C_FP_TEXT     = QColor(15, 15, 15)       # black numbers
C_FP_HIGHLIGHT = QColor(232, 222, 96)    # imbalance highlight border
C_FP_VOL_POC   = QColor(235, 218, 60)    # volume-footprint POC bar (yellow)

C_VP_POC      = QColor(255, 105, 180)
C_VP_INVA     = QColor(224, 112, 32)
C_VP_OUTVA    = QColor(184, 144, 32)
C_VP_DLT_POS  = QColor(58, 138, 58)
C_VP_DLT_NEG  = QColor(106, 42, 154)
C_VP_VA_LINE  = QColor(136, 136, 136)

C_HLINE       = QColor(70, 150, 255)
C_VLINE       = QColor(255, 136, 0)
C_BOX         = QColor(70, 150, 255)
C_BOX_FILL    = QColor(70, 150, 255, 28)   # faint blue tint inside boxes
C_COMPOSITE   = QColor(150, 165, 195, 90)  # right-side composite volume bars
C_RAY         = QColor(40, 105, 200)       # right-extending horizontal ray (darker blue)
# long / short position tool
C_POS_ENTRY   = QColor(120, 120, 130)      # entry line (dark gray)
C_POS_TP      = QColor(46, 200, 78)        # take-profit (platform green)
C_POS_SL      = QColor(150, 92, 198)       # stop-loss (platform purple)
C_POS_TP_FILL = QColor(46, 200, 78, 40)    # profit zone (transparent green)
C_POS_SL_FILL = QColor(150, 92, 198, 40)   # loss zone (transparent purple)
C_LINE_HOVER  = QColor(255, 68, 68)
C_VP_PREVIEW  = QColor(68, 204, 68)

C_EDIT_H      = QColor(170, 170, 0)
C_EDIT_H_HOV  = QColor(255, 255, 68)
C_EDIT_V      = QColor(170, 102, 0)
C_EDIT_V_HOV  = QColor(255, 170, 0)
C_EDIT_VP     = QColor(34, 170, 136)
C_EDIT_VP_HOV = QColor(68, 255, 68)

C_TOOLTIP_BG  = QColor(20, 28, 44, 240)
C_TOOLTIP_BD  = QColor(60, 80, 110)
C_TEXT_DIM    = QColor(150, 165, 185)

# VWAP line colors per anchor type (band shades derive from these)
C_VWAP = {
    "bar_globex":  QColor(255, 160, 40),
    "bar_rth":     QColor(40, 190, 235),
    "tick_globex": QColor(255, 110, 110),
    "tick_rth":    QColor(110, 210, 120),
}

# big-trade bubbles
C_BT_BUY  = QColor(60, 130, 240)    # blue  (side B)
C_BT_SELL = QColor(175, 90, 230)    # purple (side A) — distinct from footprint sell

# CVD panel
C_CVD_PANEL   = QColor(16, 22, 34)
C_CVD_DIVIDER = QColor(70, 90, 120)
C_CVD_LINE    = QColor(120, 205, 205)

VP_OPACITY = 0.75


def _fmt(v: float) -> str:
    return f"{v:.10g}"


def _nice_step(rough: float) -> float:
    import math
    if rough <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(rough))
    norm = rough / mag
    if norm < 1.5:
        return mag
    if norm < 3:
        return 2 * mag
    if norm < 7:
        return 5 * mag
    return 10 * mag


class FootprintCanvas(QWidget):
    state_changed = pyqtSignal()   # mode/layer changed -> toolbar re-syncs

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.vt = Viewport()
        self.data = None
        self.tick_size = 0.25
        self._initialized = False
        self._focus_last_session = True

        # layers (footprint + passive come from candle data itself)
        self.layers = {"footprint": False, "passive": False, "volume": False,
                       "vwap": False, "cvd": False, "big_trades": False}
        self.fp_settings = OrderFootprintSettings.load()
        self.passive_settings = PassiveOrderSettings.load()
        self.volume_settings = VolumeFootprintSettings.load()
        self.bt_settings = BigTradeSettings.load()
        self.general_settings = GeneralSettings.load()
        self.vp_settings = VolumeProfileSettings.load()

        # indicator / big-trade data (set after load)
        self.indicators = None
        self.big_trades = None
        self.vwap_type = "bar_globex"   # bar_globex | bar_rth | tick_globex | tick_rth

        # CVD bottom panel
        self.cvd_height = 150.0
        self._cvd_drag = False

        # drawing tools
        self.draw_mode = None       # 'hline'|'vline'|'ray'|'box'|'long'|'short'|'edit'|'delete'|'vp'
        self.h_lines: list = []     # prices
        self.v_lines: list = []     # candle indices
        self.rays: list = []        # {"idx","price"} horizontal rays extending right
        self.boxes: list = []       # {"idx1","price1","idx2","price2"}
        self.positions: list = []   # {"dir","idx1","idx2","entry","tp","sl"}
        self.profiles: list = []    # Profile objects
        self.vp_start_idx = None
        self._box_anchor = None     # (idx, price) first corner while dragging
        self._box_current = None    # (idx, price) live opposite corner
        self._pos_anchor = None     # (idx, entry_price) while dragging a position
        self._pos_current = None    # (idx, price) live drag point
        # composite volume profile (right-side, multi-day total volume)
        self.composite_on = False
        self.composite_levels: dict = {}
        self.composite_days = 0

        # edit/hover state
        self.edit_drag = None       # {"type","index"}
        self.edit_hover = None
        self.hovered_line = None    # {"type","index"} for delete hover

        # interaction
        self._dragging = False
        self._drag_start_x = 0.0
        self._drag_offset_x = 0.0
        self._drag_start_y = 0.0
        self._drag_center_price = 0.0
        self._mx = 0.0
        self._my = 0.0
        self._show_tooltip = False

    # ── public API ────────────────────────────────────────────────────
    def set_data(self, data, tick_size: float, focus_last_session: bool = True) -> None:
        self.data = data
        self.tick_size = tick_size if tick_size > 0 else 0.25
        self._focus_last_session = focus_last_session
        self._initialized = False
        self.update()

    def set_indicators(self, indicators) -> None:
        self.indicators = indicators
        self.update()

    def set_big_trades(self, big_trades) -> None:
        self.big_trades = big_trades
        self.update()

    def set_vwap_type(self, vtype: str) -> None:
        self.vwap_type = vtype
        self.update()

    # ── auto volume profiles (ETH / RTH per session) ──────────────────
    def _session_bounds(self):
        d = self.data
        starts = list(d.session_starts) if getattr(d, "session_starts", None) else [0]
        if not starts or starts[0] != 0:
            starts = [0] + [s for s in starts if s != 0]
        bounds = []
        for j, s0 in enumerate(starts):
            s1 = starts[j + 1] if j + 1 < len(starts) else d.n
            bounds.append((s0, s1))
        return bounds

    def _tod(self, i):
        t = self.data.times[i]
        return t.hour * 60 + t.minute

    def _session_rth_start(self, s0, s1):
        """First bar at/after RTH start on the day side (after the midnight wrap)."""
        rth_min = self.general_settings.rth_start_min()
        wrap = s0
        for i in range(s0 + 1, s1):
            if self._tod(i) < self._tod(i - 1):
                wrap = i
                break
        for i in range(wrap, s1):
            if self._tod(i) >= rth_min:
                return i
        return None

    def add_session_profiles(self, kind: str) -> None:
        """Append an ETH or RTH volume profile for each loaded session."""
        d = self.data
        if not d or d.n == 0:
            return
        rth_min = self.general_settings.rth_start_min()
        end_min = rth_min + max(1, self.vp_settings.rth_minutes)
        for s0, s1 in self._session_bounds():
            rth_idx = self._session_rth_start(s0, s1)
            if rth_idx is None:
                continue
            if kind == "eth":
                a, b = s0, rth_idx - 1            # globex start .. bar before RTH
            else:  # rth: RTH start .. last bar before rth_start + N minutes
                a = rth_idx
                b = rth_idx
                for i in range(rth_idx, s1):
                    if self._tod(i) < end_min:
                        b = i
                    else:
                        break
            if b < a:
                continue
            prof = compute_profile(d, a, b, self.tick_size)
            if prof:
                self.profiles.append(prof)
        self.update()

    # ── composite volume profile (right-side, multi-day) ──────────────
    def set_composite(self, levels: dict, days: int) -> None:
        self.composite_levels = levels or {}
        self.composite_days = days
        self.composite_on = bool(self.composite_levels)
        self.update()

    def clear_composite(self) -> None:
        self.composite_on = False
        self.composite_levels = {}
        self.composite_days = 0
        self.update()

    def toggle_layer(self, name: str) -> None:
        if name in self.layers:
            self.layers[name] = not self.layers[name]
            # the two footprint types are mutually exclusive
            if self.layers[name] and name in ("footprint", "volume"):
                other = "volume" if name == "footprint" else "footprint"
                self.layers[other] = False
            self.state_changed.emit()
            self.update()

    def set_draw_mode(self, mode) -> None:
        self.draw_mode = None if self.draw_mode == mode else mode
        self.vp_start_idx = None
        self._box_anchor = None
        self._box_current = None
        self._pos_anchor = None
        self._pos_current = None
        self.edit_drag = None
        self.edit_hover = None
        self.hovered_line = None
        self._apply_cursor()
        self.state_changed.emit()
        self.update()

    def clear_all(self) -> None:
        self.h_lines.clear()
        self.v_lines.clear()
        self.rays.clear()
        self.boxes.clear()
        self.positions.clear()
        self.profiles.clear()
        self.hovered_line = None
        self.vp_start_idx = None
        self._box_anchor = None
        self._box_current = None
        self._pos_anchor = None
        self._pos_current = None
        self.edit_drag = None
        self.edit_hover = None
        self.update()

    def reset_view(self) -> None:
        self._init_view()
        self.update()

    # ── view init ─────────────────────────────────────────────────────
    def _init_view(self) -> None:
        d = self.data
        if not d or len(d) == 0:
            return
        n = len(d)

        # default viewport: last session if more than one, else everything
        start_idx = 0
        if (self._focus_last_session and d.session_starts
                and len(d.session_starts) > 1):
            start_idx = d.session_starts[-1]

        # price scale fitted to the visible range
        pmin = float(d.l[start_idx:].min())
        pmax = float(d.h[start_idx:].max())
        if pmax <= pmin:
            pmax = pmin + self.tick_size
        self.vt.price_min = pmin
        self.vt.price_max = pmax
        self.vt.center_price = (pmin + pmax) / 2
        self.vt.scale_y = 1.0

        # size candles to fit the visible range, then left-align start_idx
        visible = max(1, n - start_idx)
        chart_w = max(1.0, self.width() - PRICE_AXIS_W)
        slot_needed = chart_w / visible
        self.vt.candle_w = max(0.1, min(120.0, slot_needed / (1 + Viewport.GAP_RATIO)))
        self.vt.offset_x = start_idx * self.vt.slot_w()
        self._initialized = True

    def _apply_cursor(self) -> None:
        if self.draw_mode == "delete":
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self.draw_mode == "edit":
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self.draw_mode:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    # ── painting ──────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), C_BG)

        if not self.data or len(self.data) == 0:
            self._draw_center_text(p, "No data for this selection")
            p.end()
            return

        if not self._initialized and self.width() > 0:
            self._init_view()

        vt = self.vt
        vt.left = PRICE_AXIS_W
        vt.top = DELTA_H
        vt.right = self.width()
        cvd_on = self._cvd_active()
        if cvd_on:
            vt.bottom = self.height() - TIME_AXIS_H - self.cvd_height
        else:
            vt.bottom = self.height() - TIME_AXIS_H

        self._draw_price_axis(p)
        self._draw_time_axis(p)
        self._draw_candles(p)
        if self.layers["vwap"]:
            self._draw_vwap(p)
        if self.layers["big_trades"]:
            self._draw_big_trades(p)
        self._draw_composite(p)
        self._draw_profiles(p)
        self._draw_lines(p)
        self._draw_rays(p)
        self._draw_boxes(p)
        self._draw_positions(p)
        if cvd_on:
            self._draw_cvd_panel(p)
        if self.draw_mode == "edit":
            self._draw_edit_handles(p)
        if self.draw_mode == "hline":
            self._draw_hline_preview(p)
        if self.draw_mode == "vline":
            self._draw_vline_preview(p)
        if self.draw_mode == "box" and self._box_anchor is not None:
            self._draw_box_preview(p)
        if self.draw_mode in ("long", "short") and self._pos_anchor is not None:
            self._draw_position_preview(p)
        if self.draw_mode == "vp" and self.vp_start_idx is not None:
            self._draw_vp_preview(p)
        if self._show_tooltip:
            self._draw_tooltip(p)
        p.end()

    def _cvd_active(self) -> bool:
        return (self.layers["cvd"] and self.indicators is not None
                and self.indicators.has("cumulative_delta"))

    # ── small text helper ─────────────────────────────────────────────
    def _text(self, p, x, y, s, color, align="left", px=10):
        f = QFont("monospace")
        f.setPixelSize(int(px))
        p.setFont(f)
        if align != "left":
            w = QFontMetricsF(f).horizontalAdvance(s)
            if align == "center":
                x -= w / 2
            elif align == "right":
                x -= w
        p.setPen(color)
        p.drawText(QPointF(x, y), s)

    def _draw_center_text(self, p, s):
        f = QFont("monospace")
        f.setPixelSize(15)
        p.setFont(f)
        p.setPen(C_TEXT_DIM)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, s)

    # ── axes / panels ─────────────────────────────────────────────────
    def _draw_price_axis(self, p):
        vt = self.vt
        p.fillRect(QRectF(0, vt.top, PRICE_AXIS_W, vt.chart_h()), C_PANEL)
        vis = vt.price_span()
        vmin = vt.center_price - vis / 2
        vmax = vt.center_price + vis / 2
        step = _nice_step(vis / 10)
        pen = QPen(C_GRID)
        pen.setWidthF(0.5)
        import math
        start = math.ceil(vmin / step) * step
        pcur = start
        while pcur <= vmax:
            y = vt.price_to_y(pcur)
            if vt.top <= y <= vt.bottom:
                p.setPen(pen)
                p.drawLine(QPointF(PRICE_AXIS_W, y), QPointF(vt.right, y))
                self._text(p, PRICE_AXIS_W - 4, y + 3, _fmt(pcur), C_AXIS_TEXT, "right", 10)
            pcur += step

    def _draw_time_axis(self, p):
        vt = self.vt
        d = self.data
        p.fillRect(QRectF(0, self.height() - TIME_AXIS_H, vt.right, TIME_AXIS_H), C_PANEL)
        import math
        step = max(1, math.floor(60 / vt.candle_w)) if vt.candle_w > 0 else 1
        for i in range(0, len(d), step):
            x = vt.candle_x(i) + vt.candle_w / 2
            if x < PRICE_AXIS_W or x > vt.right:
                continue
            self._text(p, x, self.height() - 5, d.times[i].strftime("%H:%M"),
                       C_AXIS_TEXT, "center", 9)

    # ── candles + footprint + passive ─────────────────────────────────
    def _draw_candles(self, p):
        vt = self.vt
        d = self.data
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        footprint_on = self.layers["footprint"]
        passive_on = self.layers["passive"]
        volume_on = self.layers["volume"]
        use_thin = footprint_on or passive_on or volume_on
        for i in range(len(d)):
            x = vt.candle_x(i)
            if x + vt.candle_w < PRICE_AXIS_W or x > vt.right:
                continue
            o, h, l, c = d.o[i], d.h[i], d.l[i], d.c[i]
            oy, hy, ly, cy = (vt.price_to_y(o), vt.price_to_y(h),
                              vt.price_to_y(l), vt.price_to_y(c))
            bull = c >= o
            body_top = min(oy, cy)
            body_h = max(1.0, abs(cy - oy))

            if use_thin:
                # thin body bar on the left, footprint/passive fills the rest
                body_w = max(2.0, min(8.0, vt.candle_w * 0.15))
                wick_x = x + body_w / 2
                pen = QPen(C_BULL_BODY if bull else C_BEAR_BODY)
                pen.setWidthF(1)
                p.setPen(pen)
                p.drawLine(QPointF(wick_x, hy), QPointF(wick_x, ly))
                p.fillRect(QRectF(x, body_top, body_w, body_h),
                           C_BULL_BODY if bull else C_BEAR_BODY)
                fx = x + body_w + 1
                fw = max(0.0, vt.candle_w - body_w - 1)
                if volume_on:
                    self._draw_volume_footprint(p, i, fx, fw)
                if passive_on:
                    self._draw_passive(p, i, fx, fw)
                if footprint_on:
                    self._draw_footprint(p, i, fx, fw)
            else:
                midx = x + vt.candle_w / 2
                pen = QPen(C_BULL_STROKE if bull else C_BEAR_STROKE)
                pen.setWidthF(1)
                p.setPen(pen)
                p.drawLine(QPointF(midx, hy), QPointF(midx, ly))
                p.fillRect(QRectF(x + vt.candle_w * 0.2, body_top, vt.candle_w * 0.6, body_h),
                           C_BULL_BODY if bull else C_BEAR_BODY)
        p.restore()

    @staticmethod
    def _lerp_color(c1, c2, t):
        return QColor(
            int(c1.red()   + (c2.red()   - c1.red())   * t),
            int(c1.green() + (c2.green() - c1.green()) * t),
            int(c1.blue()  + (c2.blue()  - c1.blue())  * t),
        )

    def _cell_bg(self, value, other, target, settings=None):
        """Light gray when balanced/non-dominant; tinted toward target by ratio."""
        if value <= other:
            return C_FP_BASE
        s = settings if settings is not None else self.fp_settings
        ratio = value / max(1, other)
        start, full = s.gradient_start_ratio, s.gradient_full_ratio
        if full <= start:
            full = start + 1e-6
        t = max(0.0, min(1.0, (ratio - start) / (full - start)))
        return self._lerp_color(C_FP_BASE, target, t)

    def _is_highlight(self, value, other):
        s = self.fp_settings
        if not s.show_highlight or value <= other:
            return False
        ratio = value / max(1, other)
        return ratio >= s.highlight_ratio

    def _draw_footprint(self, p, i, fx, fw):
        vt = self.vt
        tv = self.data.tick_volume[i]
        if not tv:
            return
        cell_h = vt.tick_px(self.tick_size)
        if cell_h < 4:
            return
        col_w = fw / 2
        if col_w < 9:
            return
        px = max(6, min(11, cell_h * 0.7))
        x_slot = vt.candle_x(i)
        p.save()
        p.setClipRect(QRectF(x_slot, vt.top, vt.candle_w, vt.chart_h()))
        for price, (buy, sell) in tv.items():
            y = vt.price_to_y(price) - cell_h / 2
            # left = sell (purple), right = buy (green)
            p.fillRect(QRectF(fx, y, col_w - 1, cell_h), self._cell_bg(sell, buy, C_FP_SELL))
            p.fillRect(QRectF(fx + col_w, y, col_w - 1, cell_h), self._cell_bg(buy, sell, C_FP_BUY))
            if self._is_highlight(sell, buy):
                self._highlight_rect(p, fx, y, col_w - 1, cell_h)
            if self._is_highlight(buy, sell):
                self._highlight_rect(p, fx + col_w, y, col_w - 1, cell_h)
            self._text(p, fx + col_w / 2, y + cell_h * 0.65, str(sell), C_FP_TEXT, "center", px)
            self._text(p, fx + col_w + col_w / 2, y + cell_h * 0.65, str(buy), C_FP_TEXT, "center", px)
        p.restore()

    def _highlight_rect(self, p, x, y, w, h):
        pen = QPen(C_FP_HIGHLIGHT)
        pen.setWidthF(2.5)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        inset = pen.widthF() / 2
        p.drawRect(QRectF(x + inset, y + inset, w - pen.widthF(), max(1.0, h - pen.widthF())))

    def _draw_volume_footprint(self, p, i, fx, fw):
        """Per-candle volume bars: length = total volume at the level, colored
        by buy/sell imbalance, POC bar in yellow, white delta number."""
        vt = self.vt
        tv = self.data.tick_volume[i]
        if not tv:
            return
        cell_h = vt.tick_px(self.tick_size)
        if cell_h < 4 or fw < 9:
            return
        # totals + POC (highest total-volume level)
        max_total = 0
        poc_price = None
        for price, (buy, sell) in tv.items():
            tot = buy + sell
            if tot > max_total:
                max_total, poc_price = tot, price
        if max_total <= 0:
            return
        px = max(6, min(11, cell_h * 0.7))
        p.save()
        p.setClipRect(QRectF(vt.candle_x(i), vt.top, vt.candle_w, vt.chart_h()))
        for price, (buy, sell) in tv.items():
            tot = buy + sell
            y = vt.price_to_y(price) - cell_h / 2
            bar_w = max(1.0, (tot / max_total) * fw)
            is_poc = price == poc_price
            if buy >= sell:
                color = self._cell_bg(buy, sell, C_FP_BUY, self.volume_settings)
            else:
                color = self._cell_bg(sell, buy, C_FP_SELL, self.volume_settings)
            p.fillRect(QRectF(fx, y, bar_w, cell_h), color)
            if is_poc:
                pen = QPen(C_FP_VOL_POC)
                pen.setWidthF(1.5)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(fx + 0.75, y + 0.75, bar_w - 1.5, max(1.0, cell_h - 1.5)))
            if self.volume_settings.show_delta:
                delta = buy - sell
                txt = ("+" if delta >= 0 else "") + str(delta)
                self._text(p, fx + 3, y + cell_h * 0.65, txt, QColor(245, 245, 245), "left", px)
        p.restore()


    # ── VWAP ───────────────────────────────────────────────────────────
    def _draw_series(self, p, arr, color, width):
        """Polyline across candles, breaking on NaN."""
        if arr is None:
            return
        vt = self.vt
        d = self.data
        pen = QPen(color)
        pen.setWidthF(width)
        p.setPen(pen)
        prev = None
        n = min(len(d), len(arr))
        for i in range(n):
            v = arr[i]
            if v is None or (isinstance(v, float) and math.isnan(v)):
                prev = None
                continue
            x = vt.candle_x(i) + vt.candle_w / 2
            y = vt.price_to_y(v)
            if prev is not None:
                p.drawLine(QPointF(prev[0], prev[1]), QPointF(x, y))
            prev = (x, y)

    def _draw_vwap(self, p):
        ind = self.indicators
        if ind is None:
            return
        base = f"vwap_{self.vwap_type}"
        if not ind.has(base):
            return
        vt = self.vt
        color = C_VWAP.get(self.vwap_type, QColor(255, 200, 80))
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        # std bands, fainter the further out
        for std, alpha in ((3, 55), (2, 90), (1, 130)):
            for side in ("up", "dn"):
                cname = f"{base}_std{std}_{side}"
                if ind.has(cname):
                    bc = QColor(color)
                    bc.setAlpha(alpha)
                    self._draw_series(p, ind.col(cname), bc, 1.0)
        # the VWAP line itself on top
        self._draw_series(p, ind.col(base), color, 1.8)
        p.restore()

    # ── Big trades ─────────────────────────────────────────────────────
    def _draw_big_trades(self, p):
        bt = self.big_trades
        if bt is None or bt.n == 0:
            return
        d = self.data
        vt = self.vt
        s = self.bt_settings
        max_c = max(1.0, s.max_contracts)
        min_px = max(0.5, s.min_bubble_px)
        max_px = max(min_px, s.max_bubble_px)
        rth_start = self.general_settings.rth_start_min()
        rth_end = self.general_settings.rth_end_min()
        n = len(d)
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(bt.n):
            side = bt.side[k]
            if side == "B":
                color = C_BT_BUY
            elif side == "A":
                color = C_BT_SELL
            else:
                continue  # skip N / unknown aggressor side
            size = bt.size[k]
            is_rth = rth_start <= bt.tod_min[k] < rth_end
            floor = s.rth_min_contracts if is_rth else s.eth_min_contracts
            if size < floor:
                continue
            idx = int(np.searchsorted(d.times_ns, bt.ts_ns[k], side="right") - 1)
            if idx < 0 or idx >= n:
                continue
            x = vt.candle_x(idx) + vt.candle_w / 2
            if x < PRICE_AXIS_W or x > vt.right:
                continue
            y = vt.price_to_y(bt.price[k])
            if y < vt.top or y > vt.bottom:
                continue
            # size the bubble between the session threshold (min_px) and the cap (max_px)
            denom = max(1e-9, max_c - floor)
            t = min(1.0, max(0.0, (min(float(size), max_c) - floor) / denom))
            r = min_px + t * (max_px - min_px)
            fill = QColor(color)
            fill.setAlpha(150)
            p.setBrush(fill)
            p.drawEllipse(QPointF(x, y), r, r)
        p.restore()

    # ── CVD bottom panel ───────────────────────────────────────────────
    def _draw_cvd_panel(self, p):
        ind = self.indicators
        cvd = ind.col("cumulative_delta") if ind else None
        if cvd is None:
            return
        d = self.data
        vt = self.vt
        top = vt.bottom
        bottom = self.height() - TIME_AXIS_H
        h = bottom - top
        if h < 8:
            return
        p.fillRect(QRectF(0, top, vt.right, h), C_CVD_PANEL)
        # draggable divider
        pen = QPen(C_CVD_DIVIDER)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawLine(QPointF(0, top), QPointF(vt.right, top))

        # min/max over visible candles
        first = max(0, vt.x_to_candle_floor(PRICE_AXIS_W))
        last = min(len(d) - 1, vt.x_to_candle_round(vt.right))
        vis = [cvd[i] for i in range(first, last + 1)
               if i < len(cvd) and not (isinstance(cvd[i], float) and math.isnan(cvd[i]))]
        self._text(p, PRICE_AXIS_W + 6, top + 14, "CVD", C_TEXT_DIM, "left", 10)
        if not vis:
            return
        vmin, vmax = min(vis), max(vis)
        if vmax == vmin:
            vmax = vmin + 1
        pad = (vmax - vmin) * 0.12
        vmin -= pad
        vmax += pad

        def yv(v):
            return bottom - (v - vmin) / (vmax - vmin) * h

        # zero baseline
        if vmin <= 0 <= vmax:
            zp = QPen(C_GRID)
            zp.setWidthF(0.5)
            p.setPen(zp)
            p.drawLine(QPointF(PRICE_AXIS_W, yv(0)), QPointF(vt.right, yv(0)))
        # the CVD line
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, top, vt.right - PRICE_AXIS_W, h))
        pen = QPen(C_CVD_LINE)
        pen.setWidthF(1.4)
        p.setPen(pen)
        prev = None
        for i in range(len(d)):
            v = cvd[i] if i < len(cvd) else float("nan")
            if v is None or (isinstance(v, float) and math.isnan(v)):
                prev = None
                continue
            x = vt.candle_x(i) + vt.candle_w / 2
            y = yv(v)
            if prev is not None:
                p.drawLine(QPointF(prev[0], prev[1]), QPointF(x, y))
            prev = (x, y)
        p.restore()
        self._text(p, PRICE_AXIS_W - 4, yv(vis[-1]) + 3, f"{vis[-1]:,.0f}", C_AXIS_TEXT, "right", 9)

    def _cvd_divider_hit(self, cy) -> bool:
        if not self._cvd_active():
            return False
        top = self.height() - TIME_AXIS_H - self.cvd_height
        return abs(cy - top) <= 5

    def _passive_cell_bg(self, size, target):
        """Light gray scaling toward target by resting size."""
        full = self.passive_settings.gradient_full_size
        if full <= 0:
            full = 1.0
        t = max(0.0, min(1.0, size / full))
        return self._lerp_color(C_FP_BASE, target, t)

    def _draw_passive(self, p, i, fx, fw):
        vt = self.vt
        d = self.data
        po = d.passive_orders[i]
        if not po:
            return
        cell_h = vt.tick_px(self.tick_size)
        if cell_h < 4 or fw < 9:
            return
        px = max(6, min(11, cell_h * 0.7))
        s = self.passive_settings
        open_p = d.o[i]
        x_slot = vt.candle_x(i)
        p.save()
        p.setClipRect(QRectF(x_slot, vt.top, vt.candle_w, vt.chart_h()))
        for price, (size, count) in po.items():
            y = vt.price_to_y(price) - cell_h / 2
            above = price > open_p
            # above open = resting ask / resistance (purple); below = bid / support (green)
            target = C_FP_SELL if above else C_FP_BUY
            p.fillRect(QRectF(fx, y, fw - 1, cell_h), self._passive_cell_bg(size, target))
            if s.show_highlight and size >= s.highlight_size:
                self._highlight_rect(p, fx, y, fw - 1, cell_h)
            self._text(p, fx + fw / 2, y + cell_h * 0.65, f"{size}({count})",
                       C_FP_TEXT, "center", px)
        p.restore()

    # ── volume profiles ───────────────────────────────────────────────
    def _draw_profiles(self, p):
        for prof in self.profiles:
            self._draw_one_profile(p, prof)

    def _draw_one_profile(self, p, prof):
        vt = self.vt
        start_x = vt.candle_x(prof.start_idx)
        end_x = vt.candle_x(prof.end_idx) + vt.candle_w
        range_w = end_x - start_x
        bar_max_w = min(self.vp_settings.vol_width, range_w * 0.4)
        if bar_max_w < 4:
            return
        delta_max_w = self.vp_settings.delta_width
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        cell_h = vt.tick_px(self.tick_size)
        max_total = prof.max_total or 1

        for lv in prof.levels.values():
            y = vt.price_to_y(lv["p"]) - cell_h / 2
            in_va = prof.val <= lv["p"] <= prof.vah
            is_poc = lv["p"] == prof.poc
            p.setOpacity(VP_OPACITY)
            color = C_VP_POC if is_poc else (C_VP_INVA if in_va else C_VP_OUTVA)
            p.fillRect(QRectF(start_x, y, (lv["total"] / max_total) * bar_max_w, max(1.0, cell_h)), color)
            delta = lv["buy"] - lv["sell"]
            dw = (abs(delta) / max_total) * delta_max_w
            p.fillRect(QRectF(start_x - dw, y, dw, max(1.0, cell_h)),
                       C_VP_DLT_POS if delta >= 0 else C_VP_DLT_NEG)
            p.setOpacity(1.0)

        poc_y = vt.price_to_y(prof.poc)
        pen = QPen(C_VP_POC)
        pen.setWidthF(1.5)
        pen.setDashPattern([3, 3])
        p.setPen(pen)
        p.drawLine(QPointF(start_x, poc_y), QPointF(end_x, poc_y))
        vah_y = vt.price_to_y(prof.vah)
        val_y = vt.price_to_y(prof.val)
        pen = QPen(C_VP_VA_LINE)
        pen.setWidthF(0.5)
        pen.setDashPattern([2, 4])
        p.setPen(pen)
        p.drawLine(QPointF(start_x, vah_y), QPointF(end_x, vah_y))
        p.drawLine(QPointF(start_x, val_y), QPointF(end_x, val_y))

        if bar_max_w > 20:
            self._text(p, start_x + 2, poc_y - 2, f"POC {_fmt(prof.poc)}", C_VP_POC, "left", 9)
            self._text(p, start_x + 2, vah_y - 2, f"VAH {_fmt(prof.vah)}", C_VP_VA_LINE, "left", 9)
            self._text(p, start_x + 2, val_y - 2, f"VAL {_fmt(prof.val)}", C_VP_VA_LINE, "left", 9)
        p.restore()

    def _draw_vp_preview(self, p):
        vt = self.vt
        x = vt.candle_x(self.vp_start_idx) + vt.candle_w / 2
        pen = QPen(C_VP_PREVIEW)
        pen.setWidthF(1.5)
        pen.setDashPattern([3, 3])
        p.setPen(pen)
        p.drawLine(QPointF(x, vt.top), QPointF(x, vt.bottom))

    # ── lines ─────────────────────────────────────────────────────────
    def _draw_lines(self, p):
        vt = self.vt
        d = self.data
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        for i, price in enumerate(self.h_lines):
            y = vt.price_to_y(price)
            hov = self.hovered_line and self.hovered_line["type"] == "h" and self.hovered_line["index"] == i
            pen = QPen(C_LINE_HOVER if hov else C_HLINE)
            pen.setWidthF(2 if hov else 1)
            pen.setDashPattern([4, 4])
            p.setPen(pen)
            p.drawLine(QPointF(PRICE_AXIS_W, y), QPointF(vt.right, y))
            self._text(p, PRICE_AXIS_W + 4, y - 3, _fmt(price),
                       C_LINE_HOVER if hov else C_HLINE, "left", 10)
        for i, idx in enumerate(self.v_lines):
            x = vt.candle_x(idx) + vt.candle_w / 2
            hov = self.hovered_line and self.hovered_line["type"] == "v" and self.hovered_line["index"] == i
            pen = QPen(C_LINE_HOVER if hov else C_VLINE)
            pen.setWidthF(2 if hov else 1)
            p.setPen(pen)
            p.drawLine(QPointF(x, vt.top), QPointF(x, vt.bottom))
            if 0 <= idx < len(d):
                lbl = d.times[idx].strftime("%m/%d %H:%M")
                self._text(p, x, vt.top + 14, lbl, C_LINE_HOVER if hov else C_VLINE, "center", 10)
        p.restore()

    # ── boxes ─────────────────────────────────────────────────────────
    def _draw_composite(self, p):
        if not self.composite_on or not self.composite_levels:
            return
        vt = self.vt
        max_vol = max(self.composite_levels.values())
        if max_vol <= 0:
            return
        MAXW = float(self.vp_settings.composite_width)
        right = vt.right
        cell_h = max(1.0, vt.tick_px(self.tick_size))
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        for price, vol in self.composite_levels.items():
            y = vt.price_to_y(price)
            if y < vt.top - cell_h or y > vt.bottom + cell_h:
                continue
            w = (vol / max_vol) * MAXW
            p.fillRect(QRectF(right - w, y - cell_h / 2, w, cell_h), C_COMPOSITE)
        p.restore()
        self._text(p, vt.right - 6, vt.top + 12,
                   f"days loaded: {self.composite_days}", C_TEXT_DIM, "right", 10)

    # ── rays (right-extending horizontal lines) ───────────────────────
    def _draw_rays(self, p):
        if not self.rays:
            return
        vt = self.vt
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        for i, ray in enumerate(self.rays):
            y = vt.price_to_y(ray["price"])
            if y < vt.top or y > vt.bottom:
                continue
            x0 = max(PRICE_AXIS_W, vt.candle_x(ray["idx"]) + vt.candle_w / 2)
            hov = (self.hovered_line and self.hovered_line["type"] == "ray"
                   and self.hovered_line["index"] == i)
            pen = QPen(C_LINE_HOVER if hov else C_RAY)
            pen.setWidthF(2.5 if hov else 1.6)   # continuous (no dash)
            p.setPen(pen)
            p.drawLine(QPointF(x0, y), QPointF(vt.right, y))
        p.restore()

    # ── long / short positions ────────────────────────────────────────
    def _make_position(self, direction, anchor, current):
        """anchor = (idx, entry); current = (idx, drag price). SL mirrors TP."""
        idx1, entry = anchor
        idx2, drag = current
        if idx2 == idx1:
            idx2 = idx1 + 20            # default width when not dragged sideways
        tick = self.tick_size
        if direction == "long":
            tp = max(drag, entry + tick)
            sl = entry - (tp - entry)
        else:
            tp = min(drag, entry - tick)
            sl = entry + (entry - tp)
        return {"dir": direction, "idx1": min(idx1, idx2), "idx2": max(idx1, idx2),
                "entry": entry, "tp": tp, "sl": sl}

    def _draw_positions(self, p):
        for i, pos in enumerate(self.positions):
            hov = (self.hovered_line and self.hovered_line["type"] == "position"
                   and self.hovered_line["index"] == i)
            self._draw_one_position(p, pos, hovered=hov)

    def _draw_one_position(self, p, pos, hovered=False):
        vt = self.vt
        xa = vt.candle_x(pos["idx1"]) + vt.candle_w / 2
        xb = vt.candle_x(pos["idx2"]) + vt.candle_w / 2
        if xb < xa:
            xa, xb = xb, xa
        y_entry = vt.price_to_y(pos["entry"])
        y_tp = vt.price_to_y(pos["tp"])
        y_sl = vt.price_to_y(pos["sl"])
        tick = self.tick_size

        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        # zones
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C_POS_TP_FILL)
        p.drawRect(QRectF(xa, min(y_tp, y_entry), xb - xa, abs(y_entry - y_tp)))
        p.setBrush(C_POS_SL_FILL)
        p.drawRect(QRectF(xa, min(y_sl, y_entry), xb - xa, abs(y_entry - y_sl)))
        if hovered:
            pen = QPen(C_LINE_HOVER); pen.setWidthF(2.0)
            p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
            top = min(y_tp, y_sl); bot = max(y_tp, y_sl)
            p.drawRect(QRectF(xa, top, xb - xa, bot - top))
        # entry line (dark gray, continuous)
        pen = QPen(C_POS_ENTRY); pen.setWidthF(1.4); p.setPen(pen)
        p.drawLine(QPointF(xa, y_entry), QPointF(xb, y_entry))
        # tp / sl lines (dotted, full color)
        for y, col in ((y_tp, C_POS_TP), (y_sl, C_POS_SL)):
            pen = QPen(col); pen.setWidthF(1.4); pen.setDashPattern([2, 3])
            p.setPen(pen)
            p.drawLine(QPointF(xa, y), QPointF(xb, y))
        p.restore()

        # stats labels
        reward = abs(pos["tp"] - pos["entry"])
        risk = abs(pos["entry"] - pos["sl"])
        rr = reward / risk if risk > 0 else 0.0
        tp_ticks = int(round(reward / tick)) if tick else 0
        sl_ticks = int(round(risk / tick)) if tick else 0
        cx_lbl = (xa + xb) / 2
        self._pos_label(p, cx_lbl, y_tp, f"+{reward:.2f} pts · {tp_ticks} ticks",
                        C_POS_TP, above=(y_tp < y_entry))
        self._pos_label(p, cx_lbl, y_entry, f"{pos['dir'].upper()} · R:R {rr:.2f}",
                        C_POS_ENTRY, above=True, center=True)
        self._pos_label(p, cx_lbl, y_sl, f"-{risk:.2f} pts · {sl_ticks} ticks",
                        C_POS_SL, above=(y_sl < y_entry))

    def _pos_label(self, p, cx, y, text, color, above=True, center=False):
        f = QFont("Arial", 8)
        p.setFont(f)
        fm = QFontMetricsF(f)
        tw = fm.horizontalAdvance(text) + 10
        th = fm.height() + 4
        ly = (y - th - 2) if above else (y + 2)
        if center:
            ly = y - th / 2
        lx = cx - tw / 2
        lx = max(PRICE_AXIS_W + 2, min(lx, self.vt.right - tw - 2))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(lx, ly, tw, th), 3, 3)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(lx, ly, tw, th), Qt.AlignmentFlag.AlignCenter, text)

    def _draw_position_preview(self, p):
        if self._pos_anchor is None or self._pos_current is None:
            return
        pos = self._make_position(self.draw_mode, self._pos_anchor, self._pos_current)
        if pos:
            self._draw_one_position(p, pos)

    def _hovered_ray(self, cx, cy):
        vt = self.vt
        for i, ray in enumerate(self.rays):
            y = vt.price_to_y(ray["price"])
            x0 = vt.candle_x(ray["idx"]) + vt.candle_w / 2
            if abs(cy - y) <= HIT_THRESHOLD and cx >= x0 - HIT_THRESHOLD:
                return i
        return -1

    def _hovered_position(self, cx, cy):
        vt = self.vt
        for i, pos in enumerate(self.positions):
            xa = vt.candle_x(pos["idx1"]) + vt.candle_w / 2
            xb = vt.candle_x(pos["idx2"]) + vt.candle_w / 2
            if xb < xa:
                xa, xb = xb, xa
            ys = [vt.price_to_y(pos["entry"]), vt.price_to_y(pos["tp"]), vt.price_to_y(pos["sl"])]
            if (xa - HIT_THRESHOLD <= cx <= xb + HIT_THRESHOLD
                    and min(ys) - HIT_THRESHOLD <= cy <= max(ys) + HIT_THRESHOLD):
                return i
        return -1

    def _box_point(self, cx, cy):
        """Screen -> (candle index, tick-snapped price) anchor."""
        vt = self.vt
        d = self.data
        idx = max(0, min(len(d) - 1, vt.x_to_candle_round(cx)))
        price = round(vt.y_to_price(cy) / self.tick_size) * self.tick_size
        return (idx, price)

    def _box_rect(self, box) -> QRectF:
        vt = self.vt
        x1 = vt.candle_x(box["idx1"]) + vt.candle_w / 2
        x2 = vt.candle_x(box["idx2"]) + vt.candle_w / 2
        y1 = vt.price_to_y(box["price1"])
        y2 = vt.price_to_y(box["price2"])
        return QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def _draw_boxes(self, p):
        if not self.boxes:
            return
        vt = self.vt
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        for i, box in enumerate(self.boxes):
            hov = (self.hovered_line and self.hovered_line["type"] == "box"
                   and self.hovered_line["index"] == i)
            rect = self._box_rect(box)
            p.fillRect(rect, C_BOX_FILL)
            pen = QPen(C_LINE_HOVER if hov else C_BOX)
            pen.setWidthF(2.5 if hov else 1.6)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
        p.restore()

    def _draw_box_preview(self, p):
        if self._box_anchor is None or self._box_current is None:
            return
        vt = self.vt
        rect = self._box_rect({
            "idx1": self._box_anchor[0], "price1": self._box_anchor[1],
            "idx2": self._box_current[0], "price2": self._box_current[1],
        })
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        pen = QPen(QColor(70, 150, 255, 150))
        pen.setWidthF(1.5)
        pen.setDashPattern([4, 4])
        p.setPen(pen)
        p.setBrush(C_BOX_FILL)
        p.drawRect(rect)
        p.restore()

    def _draw_hline_preview(self, p):
        vt = self.vt
        raw = vt.y_to_price(self._my)
        snapped = round(raw / self.tick_size) * self.tick_size
        y = vt.price_to_y(snapped)
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        pen = QPen(QColor(70, 150, 255, 120))
        pen.setWidthF(1)
        pen.setDashPattern([4, 4])
        p.setPen(pen)
        p.drawLine(QPointF(PRICE_AXIS_W, y), QPointF(vt.right, y))
        self._text(p, PRICE_AXIS_W + 4, y - 3, _fmt(snapped), C_HLINE, "left", 10)
        p.restore()

    def _draw_vline_preview(self, p):
        vt = self.vt
        d = self.data
        idx = vt.x_to_candle_floor(self._mx)
        if idx < 0 or idx >= len(d):
            return
        x = vt.candle_x(idx) + vt.candle_w / 2
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        pen = QPen(QColor(255, 136, 0, 110))
        pen.setWidthF(1)
        pen.setDashPattern([4, 4])
        p.setPen(pen)
        p.drawLine(QPointF(x, vt.top), QPointF(x, vt.bottom))
        self._text(p, x, vt.top + 14, d.times[idx].strftime("%m/%d %H:%M"), C_VLINE, "center", 10)
        p.restore()

    # ── edit handles ──────────────────────────────────────────────────
    def _draw_edit_handles(self, p):
        vt = self.vt
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        for i, price in enumerate(self.h_lines):
            y = vt.price_to_y(price)
            hov = self.edit_hover and self.edit_hover["type"] == "h" and self.edit_hover["index"] == i
            p.setBrush(C_EDIT_H_HOV if hov else C_EDIT_H)
            p.setPen(QPen(QColor(255, 255, 255), 1))
            p.drawRect(QRectF(PRICE_AXIS_W + 8, y - 5, 10, 10))
        for i, idx in enumerate(self.v_lines):
            x = vt.candle_x(idx) + vt.candle_w / 2
            hov = self.edit_hover and self.edit_hover["type"] == "v" and self.edit_hover["index"] == i
            p.setBrush(C_EDIT_V_HOV if hov else C_EDIT_V)
            p.setPen(QPen(QColor(255, 255, 255), 1))
            p.drawRect(QRectF(x - 5, vt.top + 8, 10, 10))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for i, prof in enumerate(self.profiles):
            start_x = vt.candle_x(prof.start_idx) + vt.candle_w / 2
            end_x = vt.candle_x(prof.end_idx) + vt.candle_w / 2
            mid_y = (vt.price_to_y(prof.vah) + vt.price_to_y(prof.val)) / 2
            hov_s = self.edit_hover and self.edit_hover["type"] == "vp_start" and self.edit_hover["index"] == i
            hov_e = self.edit_hover and self.edit_hover["type"] == "vp_end" and self.edit_hover["index"] == i
            p.setPen(QPen(QColor(255, 255, 255), 1.5))
            p.setBrush(C_EDIT_VP_HOV if hov_s else C_EDIT_VP)
            p.drawEllipse(QPointF(start_x, mid_y), HANDLE_R, HANDLE_R)
            p.setBrush(C_EDIT_VP_HOV if hov_e else C_EDIT_VP)
            p.drawEllipse(QPointF(end_x, mid_y), HANDLE_R, HANDLE_R)
        for i, box in enumerate(self.boxes):
            x1 = vt.candle_x(box["idx1"]) + vt.candle_w / 2
            x2 = vt.candle_x(box["idx2"]) + vt.candle_w / 2
            y1 = vt.price_to_y(box["price1"])
            y2 = vt.price_to_y(box["price2"])
            for corner, (hx, hy) in (("box1", (x1, y1)), ("box2", (x2, y2))):
                hov = (self.edit_hover and self.edit_hover["type"] == corner
                       and self.edit_hover["index"] == i)
                p.setPen(QPen(QColor(255, 255, 255), 1.5))
                p.setBrush(C_LINE_HOVER if hov else C_BOX)
                p.drawEllipse(QPointF(hx, hy), HANDLE_R, HANDLE_R)
        for i, ray in enumerate(self.rays):
            hx = vt.candle_x(ray["idx"]) + vt.candle_w / 2
            hy = vt.price_to_y(ray["price"])
            hov = (self.edit_hover and self.edit_hover["type"] == "ray"
                   and self.edit_hover["index"] == i)
            p.setPen(QPen(QColor(255, 255, 255), 1.5))
            p.setBrush(C_LINE_HOVER if hov else C_RAY)
            p.drawEllipse(QPointF(hx, hy), HANDLE_R, HANDLE_R)
        for i, pos in enumerate(self.positions):
            xa = vt.candle_x(pos["idx1"]) + vt.candle_w / 2
            xb = vt.candle_x(pos["idx2"]) + vt.candle_w / 2
            ye = vt.price_to_y(pos["entry"])
            yt = vt.price_to_y(pos["tp"])
            ys = vt.price_to_y(pos["sl"])
            for typ, hx, hy, col in (("pos_tp", xa, yt, C_POS_TP),
                                     ("pos_sl", xa, ys, C_POS_SL),
                                     ("pos_entry", xa, ye, C_POS_ENTRY),
                                     ("pos_width", xb, ye, QColor(200, 200, 210))):
                hov = (self.edit_hover and self.edit_hover["type"] == typ
                       and self.edit_hover["index"] == i)
                p.setPen(QPen(QColor(255, 255, 255), 1.5))
                p.setBrush(C_LINE_HOVER if hov else col)
                p.drawEllipse(QPointF(hx, hy), HANDLE_R, HANDLE_R)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.restore()

    def _hovered_box(self, cx, cy):
        """Index of a box whose outline is near the cursor, else -1."""
        vt = self.vt
        for i, box in enumerate(self.boxes):
            r = self._box_rect(box)
            near_x = (abs(cx - r.left()) <= HIT_THRESHOLD or abs(cx - r.right()) <= HIT_THRESHOLD)
            near_y = (abs(cy - r.top()) <= HIT_THRESHOLD or abs(cy - r.bottom()) <= HIT_THRESHOLD)
            inside_x = r.left() - HIT_THRESHOLD <= cx <= r.right() + HIT_THRESHOLD
            inside_y = r.top() - HIT_THRESHOLD <= cy <= r.bottom() + HIT_THRESHOLD
            if (near_x and inside_y) or (near_y and inside_x):
                return i
        return -1

    # ── hit testing ───────────────────────────────────────────────────
    def _edit_target(self, cx, cy):
        vt = self.vt
        for i, price in enumerate(self.h_lines):
            if abs(cy - vt.price_to_y(price)) <= HIT_THRESHOLD:
                return {"type": "h", "index": i}
        for i, idx in enumerate(self.v_lines):
            x = vt.candle_x(idx) + vt.candle_w / 2
            if abs(cx - x) <= HIT_THRESHOLD:
                return {"type": "v", "index": i}
        import math
        for i, prof in enumerate(self.profiles):
            start_x = vt.candle_x(prof.start_idx) + vt.candle_w / 2
            end_x = vt.candle_x(prof.end_idx) + vt.candle_w / 2
            mid_y = (vt.price_to_y(prof.vah) + vt.price_to_y(prof.val)) / 2
            if math.hypot(cx - start_x, cy - mid_y) <= HANDLE_R + 4:
                return {"type": "vp_start", "index": i}
            if math.hypot(cx - end_x, cy - mid_y) <= HANDLE_R + 4:
                return {"type": "vp_end", "index": i}
        for i, box in enumerate(self.boxes):
            x1 = vt.candle_x(box["idx1"]) + vt.candle_w / 2
            x2 = vt.candle_x(box["idx2"]) + vt.candle_w / 2
            y1 = vt.price_to_y(box["price1"])
            y2 = vt.price_to_y(box["price2"])
            if math.hypot(cx - x1, cy - y1) <= HANDLE_R + 4:
                return {"type": "box1", "index": i}
            if math.hypot(cx - x2, cy - y2) <= HANDLE_R + 4:
                return {"type": "box2", "index": i}
        for i, ray in enumerate(self.rays):
            hx = vt.candle_x(ray["idx"]) + vt.candle_w / 2
            hy = vt.price_to_y(ray["price"])
            if math.hypot(cx - hx, cy - hy) <= HANDLE_R + 4:
                return {"type": "ray", "index": i}
        for i, pos in enumerate(self.positions):
            xa = vt.candle_x(pos["idx1"]) + vt.candle_w / 2
            xb = vt.candle_x(pos["idx2"]) + vt.candle_w / 2
            ye = vt.price_to_y(pos["entry"])
            yt = vt.price_to_y(pos["tp"])
            ys = vt.price_to_y(pos["sl"])
            if math.hypot(cx - xa, cy - yt) <= HANDLE_R + 4:
                return {"type": "pos_tp", "index": i}
            if math.hypot(cx - xa, cy - ys) <= HANDLE_R + 4:
                return {"type": "pos_sl", "index": i}
            if math.hypot(cx - xa, cy - ye) <= HANDLE_R + 4:
                return {"type": "pos_entry", "index": i}
            if math.hypot(cx - xb, cy - ye) <= HANDLE_R + 4:
                return {"type": "pos_width", "index": i}
        return None

    def _edit_cursor(self, target):
        if not target:
            return Qt.CursorShape.ArrowCursor
        if target["type"] in ("h", "pos_tp", "pos_sl"):
            return Qt.CursorShape.SizeVerCursor
        if target["type"] in ("box1", "box2", "ray", "pos_entry"):
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.SizeHorCursor

    def _hovered_line(self, cx, cy):
        vt = self.vt
        for i, price in enumerate(self.h_lines):
            if abs(cy - vt.price_to_y(price)) <= HIT_THRESHOLD:
                return {"type": "h", "index": i}
        for i, idx in enumerate(self.v_lines):
            if abs(cx - (vt.candle_x(idx) + vt.candle_w / 2)) <= HIT_THRESHOLD:
                return {"type": "v", "index": i}
        return None

    def _hovered_profile(self, cx, cy):
        vt = self.vt
        for i, prof in enumerate(self.profiles):
            start_x = vt.candle_x(prof.start_idx)
            end_x = vt.candle_x(prof.end_idx) + vt.candle_w
            if cx < start_x or cx > end_x:
                continue
            for price in (prof.poc, prof.vah, prof.val):
                if abs(cy - vt.price_to_y(price)) <= HIT_THRESHOLD:
                    return i
            vah_y, val_y = vt.price_to_y(prof.vah), vt.price_to_y(prof.val)
            if min(vah_y, val_y) <= cy <= max(vah_y, val_y):
                return i
        return -1

    # ── mouse ─────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if not self.data:
            return
        cx, cy = e.position().x(), e.position().y()
        if e.button() != Qt.MouseButton.LeftButton:
            return

        if self.draw_mode == "edit":
            target = self._edit_target(cx, cy)
            if target:
                self.edit_drag = target
                self.setCursor(self._edit_cursor(target))
            return

        if self.draw_mode == "box":
            self._box_anchor = self._box_point(cx, cy)
            self._box_current = self._box_anchor
            self._show_tooltip = False
            self.update()
            return

        if self.draw_mode in ("long", "short"):
            self._pos_anchor = self._box_point(cx, cy)   # (idx, entry price)
            self._pos_current = self._pos_anchor
            self._show_tooltip = False
            self.update()
            return

        if self.draw_mode in ("hline", "vline", "ray", "vp", "delete"):
            self._handle_draw_click(cx, cy)
            return

        # CVD panel divider -> resize drag
        if self.draw_mode is None and self._cvd_divider_hit(cy):
            self._cvd_drag = True
            self._show_tooltip = False
            return

        # no mode -> pan
        self._dragging = True
        self._drag_start_x = cx
        self._drag_offset_x = self.vt.offset_x
        self._drag_start_y = cy
        self._drag_center_price = self.vt.center_price

    def _handle_draw_click(self, cx, cy):
        vt = self.vt
        d = self.data
        if self.draw_mode == "vp":
            idx = max(0, min(len(d) - 1, vt.x_to_candle_round(cx)))
            if self.vp_start_idx is None:
                self.vp_start_idx = idx
                self.update()
            else:
                prof = compute_profile(d, self.vp_start_idx, idx, self.tick_size)
                if prof:
                    self.profiles.append(prof)
                self.vp_start_idx = None
                self.set_draw_mode(None)
            return
        if self.draw_mode == "hline":
            raw = vt.y_to_price(cy)
            snapped = round(raw / self.tick_size) * self.tick_size
            self.h_lines.append(snapped)
            self.set_draw_mode(None)
            return
        if self.draw_mode == "vline":
            idx = vt.x_to_candle_floor(cx)
            if 0 <= idx < len(d):
                self.v_lines.append(idx)
            self.set_draw_mode(None)
            return
        if self.draw_mode == "ray":
            idx = max(0, min(len(d) - 1, vt.x_to_candle_round(cx)))
            price = round(vt.y_to_price(cy) / self.tick_size) * self.tick_size
            self.rays.append({"idx": idx, "price": price})
            self.set_draw_mode(None)
            return
        if self.draw_mode == "delete":
            hit = self._hovered_line(cx, cy)
            if hit:
                (self.h_lines if hit["type"] == "h" else self.v_lines).pop(hit["index"])
                self.hovered_line = None
                self.update()
                return
            ridx = self._hovered_ray(cx, cy)
            if ridx >= 0:
                self.rays.pop(ridx); self.hovered_line = None; self.update(); return
            bidx = self._hovered_box(cx, cy)
            if bidx >= 0:
                self.boxes.pop(bidx); self.hovered_line = None; self.update(); return
            pidx = self._hovered_position(cx, cy)
            if pidx >= 0:
                self.positions.pop(pidx); self.hovered_line = None; self.update(); return
            prof = self._hovered_profile(cx, cy)
            if prof >= 0:
                self.profiles.pop(prof)
            self.update()

    def mouseMoveEvent(self, e):
        if not self.data:
            return
        cx, cy = e.position().x(), e.position().y()
        self._mx, self._my = cx, cy
        vt = self.vt
        d = self.data

        # CVD panel divider resize
        if self._cvd_drag:
            new_h = (self.height() - TIME_AXIS_H) - cy
            self.cvd_height = max(60.0, min(self.height() * 0.6, new_h))
            self.update()
            return

        # resize cursor when hovering the divider (idle)
        if (self.draw_mode is None and not self._dragging and not self.edit_drag):
            if self._cvd_divider_hit(cy):
                if self.cursor().shape() != Qt.CursorShape.SizeVerCursor:
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                self._show_tooltip = False
                self.update()
                return
            elif self.cursor().shape() == Qt.CursorShape.SizeVerCursor:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        # live box drag
        if self.draw_mode == "box" and self._box_anchor is not None:
            self._box_current = self._box_point(cx, cy)
            self.update()
            return

        # live long/short position drag
        if self.draw_mode in ("long", "short") and self._pos_anchor is not None:
            self._pos_current = self._box_point(cx, cy)
            self.update()
            return

        if self.draw_mode == "edit":
            if self.edit_drag:
                t = self.edit_drag["type"]
                if t == "h":
                    raw = vt.y_to_price(cy)
                    self.h_lines[self.edit_drag["index"]] = round(raw / self.tick_size) * self.tick_size
                    self._show_tooltip = False
                elif t == "v":
                    self.v_lines[self.edit_drag["index"]] = max(0, min(len(d) - 1, vt.x_to_candle_round(cx)))
                    self._show_tooltip = False
                elif t in ("box1", "box2"):
                    box = self.boxes[self.edit_drag["index"]]
                    idx, price = self._box_point(cx, cy)
                    if t == "box1":
                        box["idx1"], box["price1"] = idx, price
                    else:
                        box["idx2"], box["price2"] = idx, price
                    self._show_tooltip = False
                elif t == "ray":
                    ray = self.rays[self.edit_drag["index"]]
                    ray["idx"] = max(0, min(len(d) - 1, vt.x_to_candle_round(cx)))
                    ray["price"] = round(vt.y_to_price(cy) / self.tick_size) * self.tick_size
                    self._show_tooltip = False
                elif t in ("pos_entry", "pos_tp", "pos_sl", "pos_width"):
                    pos = self.positions[self.edit_drag["index"]]
                    price = round(vt.y_to_price(cy) / self.tick_size) * self.tick_size
                    if t == "pos_tp":
                        pos["tp"] = price
                    elif t == "pos_sl":
                        pos["sl"] = price
                    elif t == "pos_entry":           # translate the whole position
                        delta = price - pos["entry"]
                        pos["entry"] += delta
                        pos["tp"] += delta
                        pos["sl"] += delta
                    else:  # pos_width
                        pos["idx2"] = max(pos["idx1"] + 1,
                                          min(len(d) - 1, vt.x_to_candle_round(cx)))
                    self._show_tooltip = False
                else:  # vp_start / vp_end -> keep candle info visible while dragging
                    self._show_tooltip = True
                self.update()
            else:
                self._show_tooltip = False
                target = self._edit_target(cx, cy)
                if target != self.edit_hover:
                    self.edit_hover = target
                    self.setCursor(self._edit_cursor(target))
                    self.update()
            return

        if self._dragging:
            vt.offset_x = self._drag_offset_x - (cx - self._drag_start_x)
            dy = cy - self._drag_start_y
            vt.center_price = self._drag_center_price + dy * vt.price_span() / vt.chart_h()
            self.update()
            return

        if self.draw_mode == "delete":
            hit = self._hovered_line(cx, cy)
            if not hit:
                ridx = self._hovered_ray(cx, cy)
                bidx = self._hovered_box(cx, cy)
                pidx = self._hovered_position(cx, cy)
                if ridx >= 0:
                    hit = {"type": "ray", "index": ridx}
                elif bidx >= 0:
                    hit = {"type": "box", "index": bidx}
                elif pidx >= 0:
                    hit = {"type": "position", "index": pidx}
            if hit != self.hovered_line:
                self.hovered_line = hit
                self.update()
            return

        if self.draw_mode in ("hline", "vline", "ray", "box", "long", "short"):
            self.update()
            return

        # plain hover -> tooltip
        self._show_tooltip = True
        self.update()

    def mouseReleaseEvent(self, e):
        if self._cvd_drag:
            self._cvd_drag = False
            return
        if self.draw_mode == "box" and self._box_anchor is not None:
            a = self._box_anchor
            b = self._box_point(e.position().x(), e.position().y())
            if a[0] != b[0] or a[1] != b[1]:   # ignore zero-size boxes
                self.boxes.append({"idx1": a[0], "price1": a[1],
                                   "idx2": b[0], "price2": b[1]})
            self._box_anchor = None
            self._box_current = None
            self.set_draw_mode(None)
            return
        if self.draw_mode in ("long", "short") and self._pos_anchor is not None:
            pos = self._make_position(self.draw_mode, self._pos_anchor,
                                      self._box_point(e.position().x(), e.position().y()))
            if pos:
                self.positions.append(pos)
            self._pos_anchor = None
            self._pos_current = None
            self.set_draw_mode(None)
            return
        if self.draw_mode == "edit" and self.edit_drag:
            t = self.edit_drag["type"]
            if t in ("vp_start", "vp_end"):
                cx = e.position().x()
                new_idx = max(0, min(len(self.data) - 1, self.vt.x_to_candle_round(cx)))
                prof = self.profiles[self.edit_drag["index"]]
                other = prof.end_idx if t == "vp_start" else prof.start_idx
                new_prof = compute_profile(self.data, new_idx, other, self.tick_size)
                if new_prof:
                    self.profiles[self.edit_drag["index"]] = new_prof
                self.update()
            self.edit_drag = None
            return
        self._dragging = False

    def leaveEvent(self, e):
        self._dragging = False
        self.edit_drag = None
        self._show_tooltip = False
        if self.hovered_line:
            self.hovered_line = None
        self.update()

    def wheelEvent(self, e):
        if not self.data:
            return
        vt = self.vt
        dy = e.angleDelta().y()
        factor = 1.1 if dy > 0 else 0.9
        mods = e.modifiers()
        cx = e.position().x()
        cy = e.position().y()
        if mods & Qt.KeyboardModifier.ControlModifier:
            # zoom Y (price)
            mp = vt.y_to_price(cy)
            vt.scale_y = max(0.02, min(50.0, vt.scale_y * factor))
            vt.center_price += (cy - vt.price_to_y(mp)) * vt.price_span() / vt.chart_h()
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            # zoom X (time)
            idx = vt.x_to_candle_floor(cx)
            prev_x = vt.candle_x(idx)
            vt.candle_w = max(0.02, min(300.0, vt.candle_w * factor))
            vt.offset_x += vt.candle_x(idx) - prev_x
        else:
            vt.offset_x += 60 if dy > 0 else -60
        self.update()

    # ── tooltip ───────────────────────────────────────────────────────
    def _draw_tooltip(self, p):
        vt = self.vt
        d = self.data
        vp_dragging = (self.edit_drag is not None
                       and self.edit_drag["type"] in ("vp_start", "vp_end"))
        if self.draw_mode in ("hline", "vline", "delete"):
            return
        if self.draw_mode == "edit" and not vp_dragging:
            return
        idx = vt.x_to_candle_floor(self._mx)
        if idx < 0 or idx >= len(d):
            return
        t = d.times[idx]
        dv = int(d.delta[idx])
        sign = "+" if dv >= 0 else ""
        lines = [
            (t.strftime("%m/%d/%Y %H:%M"), C_TEXT_DIM),
            (f"O {_fmt(d.o[idx])}   H {_fmt(d.h[idx])}", QColor(220, 225, 235)),
            (f"L {_fmt(d.l[idx])}   C {_fmt(d.c[idx])}", QColor(220, 225, 235)),
            (f"Vol {int(d.volume[idx]):,}", QColor(220, 225, 235)),
            (f"Buy {int(d.buy_volume[idx]):,}", QColor(85, 204, 85)),
            (f"Sell {int(d.sell_volume[idx]):,}", QColor(204, 85, 85)),
            (f"Delta {sign}{dv:,} ({d.delta_pct[idx]:.1f}%)",
             C_DELTA_POS if dv >= 0 else C_DELTA_NEG),
        ]
        if self._cvd_active():
            cvd = self.indicators.col("cumulative_delta")
            if cvd is not None and idx < len(cvd):
                cv = cvd[idx]
                if not (isinstance(cv, float) and math.isnan(cv)):
                    lines.append((f"CVD {cv:,.0f}", C_CVD_LINE))
        # big trades sitting in this candle's time bin
        if self.layers["big_trades"] and self.big_trades is not None and self.big_trades.n:
            bt = self.big_trades
            s = self.bt_settings
            rth_start = self.general_settings.rth_start_min()
            rth_end = self.general_settings.rth_end_min()
            lo_ns = d.times_ns[idx]
            hi_ns = d.times_ns[idx + 1] if idx + 1 < len(d.times_ns) else np.iinfo(np.int64).max
            a = int(np.searchsorted(bt.ts_ns, lo_ns, "left"))
            b = int(np.searchsorted(bt.ts_ns, hi_ns, "left"))
            trades = []
            for j in range(a, b):
                if bt.side[j] not in ("B", "A"):
                    continue
                is_rth = rth_start <= bt.tod_min[j] < rth_end
                floor = s.rth_min_contracts if is_rth else s.eth_min_contracts
                if bt.size[j] < floor:
                    continue
                trades.append((bt.price[j], int(bt.size[j]), bt.side[j]))
            if trades:
                trades.sort(key=lambda r: r[0], reverse=True)   # price high -> low
                lines.append((f"Big trades ({len(trades)})", C_TEXT_DIM))
                CAP = 14
                for price, size, side in trades[:CAP]:
                    col = C_BT_BUY if side == "B" else C_BT_SELL
                    lines.append((f"  {side} {_fmt(price)}  x{size:,}", col))
                if len(trades) > CAP:
                    lines.append((f"  +{len(trades) - CAP} more", C_TEXT_DIM))
        f = QFont("monospace")
        f.setPixelSize(11)
        fm = QFontMetricsF(f)
        line_h = 16
        pad = 8
        w = max(fm.horizontalAdvance(s) for s, _ in lines) + pad * 2
        h = line_h * len(lines) + pad * 2
        tx = min(self._mx + 12, vt.right - w - 2)
        ty = max(self._my - 10, 0)
        ty = min(ty, self.height() - h - 2)
        p.setBrush(C_TOOLTIP_BG)
        p.setPen(QPen(C_TOOLTIP_BD, 1))
        p.drawRoundedRect(QRectF(tx, ty, w, h), 4, 4)
        yy = ty + pad + 11
        for s, color in lines:
            self._text(p, tx + pad, yy, s, color, "left", 11)
            yy += line_h
