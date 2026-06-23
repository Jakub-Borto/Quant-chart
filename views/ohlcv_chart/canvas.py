"""OHLCV chart canvas (QPainter).

Plain candlestick chart with VWAP overlay and drawing tools
(horizontal lines, rays, vertical lines, boxes, long/short positions).
No footprint cells, no CVD panel, no big-trade bubbles, no volume profiles.
"""
import math
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core.viewport import Viewport
from views.ohlcv_chart.ohlcv_settings import OhlcvGeneralSettings

# ── Layout constants ──────────────────────────────────────────────────
PRICE_AXIS_W  = 60
TIME_AXIS_H   = 20
HIT_THRESHOLD = 6
HANDLE_R      = 5

# ── Colors ────────────────────────────────────────────────────────────
C_BG          = QColor(13, 17, 23)
C_PANEL       = QColor(19, 27, 42)
C_GRID        = QColor(30, 42, 61)
C_AXIS_TEXT   = QColor(120, 135, 160)

C_BULL_STROKE = QColor(70, 210, 100)
C_BULL_BODY   = QColor(55, 190, 85)
C_BEAR_STROKE = QColor(160, 100, 205)
C_BEAR_BODY   = QColor(148, 90, 196)

C_HLINE       = QColor(70, 150, 255)
C_VLINE       = QColor(255, 136, 0)
C_BOX         = QColor(70, 150, 255)
C_BOX_FILL    = QColor(70, 150, 255, 28)
C_RAY         = QColor(40, 105, 200)
C_POS_ENTRY   = QColor(120, 120, 130)
C_POS_TP      = QColor(46, 200, 78)
C_POS_SL      = QColor(150, 92, 198)
C_POS_TP_FILL = QColor(46, 200, 78, 40)
C_POS_SL_FILL = QColor(150, 92, 198, 40)
C_LINE_HOVER  = QColor(255, 68, 68)

C_EDIT_H      = QColor(170, 170, 0)
C_EDIT_H_HOV  = QColor(255, 255, 68)
C_EDIT_V      = QColor(170, 102, 0)
C_EDIT_V_HOV  = QColor(255, 170, 0)

C_TOOLTIP_BG  = QColor(20, 28, 44, 240)
C_TOOLTIP_BD  = QColor(60, 80, 110)
C_TEXT_DIM    = QColor(150, 165, 185)

C_VWAP = {
    "bar_globex":  QColor(255, 160, 40),
    "bar_rth":     QColor(40, 190, 235),
    "tick_globex": QColor(255, 110, 110),
    "tick_rth":    QColor(110, 210, 120),
}


def _fmt(v: float) -> str:
    return f"{v:.10g}"


def _nice_step(rough: float) -> float:
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


class OhlcvCanvas(QWidget):
    state_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.vt = Viewport()
        self.data = None
        self.tick_size = 0.25
        self._initialized = False
        self._focus_last_session = True

        self.layers = {"vwap": False}
        self.general_settings = OhlcvGeneralSettings.load()

        self.indicators = None
        self.vwap_type = "bar_globex"

        # drawing tools
        self.draw_mode = None
        self.h_lines: list = []
        self.v_lines: list = []
        self.rays: list = []
        self.boxes: list = []
        self.positions: list = []
        self._box_anchor = None
        self._box_current = None
        self._pos_anchor = None
        self._pos_current = None

        # edit/hover state
        self.edit_drag = None
        self.edit_hover = None
        self.hovered_line = None

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

    def set_vwap_type(self, vtype: str) -> None:
        self.vwap_type = vtype
        self.update()

    def toggle_layer(self, name: str) -> None:
        if name in self.layers:
            self.layers[name] = not self.layers[name]
            self.state_changed.emit()
            self.update()

    def set_draw_mode(self, mode) -> None:
        self.draw_mode = None if self.draw_mode == mode else mode
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
        self.hovered_line = None
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
        start_idx = 0
        if (self._focus_last_session and d.session_starts
                and len(d.session_starts) > 1):
            start_idx = d.session_starts[-1]

        pmin = float(d.l[start_idx:].min())
        pmax = float(d.h[start_idx:].max())
        if pmax <= pmin:
            pmax = pmin + self.tick_size
        self.vt.price_min = pmin
        self.vt.price_max = pmax
        self.vt.center_price = (pmin + pmax) / 2
        self.vt.scale_y = 1.0

        visible = max(1, n - start_idx)
        chart_w = max(1.0, self.width() - PRICE_AXIS_W)
        slot_needed = chart_w / visible
        self.vt.candle_w = max(0.1, min(120.0, slot_needed / (1 + Viewport.GAP_RATIO)))
        self.vt.offset_x = start_idx * self.vt.slot_w()
        self._initialized = True

    def _apply_cursor(self) -> None:
        if self.draw_mode == "delete":
            self.setCursor(Qt.CursorShape.PointingHandCursor)
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
        vt.top = 0
        vt.right = self.width()
        vt.bottom = self.height() - TIME_AXIS_H

        self._draw_price_axis(p)
        self._draw_time_axis(p)
        self._draw_candles(p)
        if self.layers["vwap"]:
            self._draw_vwap(p)
        self._draw_lines(p)
        self._draw_rays(p)
        self._draw_boxes(p)
        self._draw_positions(p)
        if self.draw_mode is None:
            self._draw_edit_handles(p)
        if self.draw_mode == "hline":
            self._draw_hline_preview(p)
        if self.draw_mode == "vline":
            self._draw_vline_preview(p)
        if self.draw_mode == "box" and self._box_anchor is not None:
            self._draw_box_preview(p)
        if self.draw_mode in ("long", "short") and self._pos_anchor is not None:
            self._draw_position_preview(p)
        if self._show_tooltip:
            self._draw_tooltip(p)
        p.end()

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

    # ── axes ──────────────────────────────────────────────────────────
    def _draw_price_axis(self, p):
        vt = self.vt
        p.fillRect(QRectF(0, vt.top, PRICE_AXIS_W, vt.chart_h()), C_PANEL)
        vis = vt.price_span()
        vmin = vt.center_price - vis / 2
        vmax = vt.center_price + vis / 2
        step = _nice_step(vis / 10)
        pen = QPen(C_GRID)
        pen.setWidthF(0.5)
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
        step = max(1, math.floor(60 / vt.candle_w)) if vt.candle_w > 0 else 1
        for i in range(0, len(d), step):
            x = vt.candle_x(i) + vt.candle_w / 2
            if x < PRICE_AXIS_W or x > vt.right:
                continue
            self._text(p, x, self.height() - 5, d.times[i].strftime("%H:%M"),
                       C_AXIS_TEXT, "center", 9)

    # ── candles ───────────────────────────────────────────────────────
    def _draw_candles(self, p):
        vt = self.vt
        d = self.data
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
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
            midx = x + vt.candle_w / 2
            pen = QPen(C_BULL_STROKE if bull else C_BEAR_STROKE)
            pen.setWidthF(1)
            p.setPen(pen)
            p.drawLine(QPointF(midx, hy), QPointF(midx, ly))
            p.fillRect(QRectF(x + vt.candle_w * 0.2, body_top, vt.candle_w * 0.6, body_h),
                       C_BULL_BODY if bull else C_BEAR_BODY)
        p.restore()

    # ── VWAP ──────────────────────────────────────────────────────────
    def _draw_series(self, p, arr, color, width):
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
        for std, alpha in ((3, 55), (2, 90), (1, 130)):
            for side in ("up", "dn"):
                cname = f"{base}_std{std}_{side}"
                if ind.has(cname):
                    bc = QColor(color)
                    bc.setAlpha(alpha)
                    self._draw_series(p, ind.col(cname), bc, 1.0)
        self._draw_series(p, ind.col(base), color, 1.8)
        p.restore()

    # ── drawing objects ───────────────────────────────────────────────
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
            pen.setWidthF(2.5 if hov else 1.6)
            p.setPen(pen)
            p.drawLine(QPointF(x0, y), QPointF(vt.right, y))
        p.restore()

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
        pen = QPen(C_POS_ENTRY); pen.setWidthF(1.4); p.setPen(pen)
        p.drawLine(QPointF(xa, y_entry), QPointF(xb, y_entry))
        for y, col in ((y_tp, C_POS_TP), (y_sl, C_POS_SL)):
            pen = QPen(col); pen.setWidthF(1.4); pen.setDashPattern([2, 3])
            p.setPen(pen)
            p.drawLine(QPointF(xa, y), QPointF(xb, y))
        p.restore()

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

    # ── previews ──────────────────────────────────────────────────────
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

    def _draw_position_preview(self, p):
        if self._pos_anchor is None or self._pos_current is None:
            return
        pos = self._make_position(self.draw_mode, self._pos_anchor, self._pos_current)
        if pos:
            self._draw_one_position(p, pos)

    # ── edit handles ──────────────────────────────────────────────────
    def _h_handle(self, price):
        # x from the widest label the price range can produce (stable), so the
        # dot doesn't flicker horizontally as the dragged line's label changes.
        return (PRICE_AXIS_W + 4 + self._price_label_w() + 6 + HANDLE_R,
                self.vt.price_to_y(price))

    def _price_label_w(self) -> float:
        f = QFont("monospace"); f.setPixelSize(10)
        hi = max(abs(self.vt.price_min), abs(self.vt.price_max), 1.0)
        ts = f"{self.tick_size:.10g}"
        dec = len(ts.split(".")[1]) if "." in ts else 0
        sample = "0" * len(str(int(hi))) + ("." + "0" * dec if dec else "")
        if self.vt.price_min < 0:
            sample = "-" + sample
        return QFontMetricsF(f).horizontalAdvance(sample)

    def _v_handle(self, idx):
        # below the time label so the dot doesn't cover it
        return (self.vt.candle_x(idx) + self.vt.candle_w / 2, self.vt.top + 28)

    def _draw_edit_handles(self, p):
        vt = self.vt
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for i, price in enumerate(self.h_lines):
            hx, hy = self._h_handle(price)
            hov = self.edit_hover and self.edit_hover["type"] == "h" and self.edit_hover["index"] == i
            p.setPen(QPen(QColor(255, 255, 255), 1.5))
            p.setBrush(C_EDIT_H_HOV if hov else C_EDIT_H)
            p.drawEllipse(QPointF(hx, hy), HANDLE_R, HANDLE_R)
        for i, idx in enumerate(self.v_lines):
            hx, hy = self._v_handle(idx)
            hov = self.edit_hover and self.edit_hover["type"] == "v" and self.edit_hover["index"] == i
            p.setPen(QPen(QColor(255, 255, 255), 1.5))
            p.setBrush(C_EDIT_V_HOV if hov else C_EDIT_V)
            p.drawEllipse(QPointF(hx, hy), HANDLE_R, HANDLE_R)
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

    # ── hit testing ───────────────────────────────────────────────────
    def _edit_target(self, cx, cy):
        vt = self.vt
        for i, price in enumerate(self.h_lines):
            hx, hy = self._h_handle(price)
            if math.hypot(cx - hx, cy - hy) <= HANDLE_R + 4:
                return {"type": "h", "index": i}
        for i, idx in enumerate(self.v_lines):
            hx, hy = self._v_handle(idx)
            if math.hypot(cx - hx, cy - hy) <= HANDLE_R + 4:
                return {"type": "v", "index": i}
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

    def _hovered_ray(self, cx, cy):
        vt = self.vt
        for i, ray in enumerate(self.rays):
            y = vt.price_to_y(ray["price"])
            x0 = vt.candle_x(ray["idx"]) + vt.candle_w / 2
            if abs(cy - y) <= HIT_THRESHOLD and cx >= x0 - HIT_THRESHOLD:
                return i
        return -1

    def _hovered_box(self, cx, cy):
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

    def _make_position(self, direction, anchor, current):
        idx1, entry = anchor
        idx2, drag = current
        if idx2 == idx1:
            idx2 = idx1 + 20
        tick = self.tick_size
        if direction == "long":
            tp = max(drag, entry + tick)
            sl = entry - (tp - entry)
        else:
            tp = min(drag, entry - tick)
            sl = entry + (entry - tp)
        return {"dir": direction, "idx1": min(idx1, idx2), "idx2": max(idx1, idx2),
                "entry": entry, "tp": tp, "sl": sl}

    # ── mouse ─────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if not self.data:
            return
        cx, cy = e.position().x(), e.position().y()
        if e.button() != Qt.MouseButton.LeftButton:
            return

        if self.draw_mode == "box":
            self._box_anchor = self._box_point(cx, cy)
            self._box_current = self._box_anchor
            self._show_tooltip = False
            self.update()
            return

        if self.draw_mode in ("long", "short"):
            self._pos_anchor = self._box_point(cx, cy)
            self._pos_current = self._pos_anchor
            self._show_tooltip = False
            self.update()
            return

        if self.draw_mode in ("hline", "vline", "ray", "delete"):
            self._handle_draw_click(cx, cy)
            return

        # default (no tool): grab a drawing handle if one is under the cursor,
        # otherwise pan.
        target = self._edit_target(cx, cy)
        if target:
            self.edit_drag = target
            self.setCursor(self._edit_cursor(target))
            self._show_tooltip = False
            return

        self._dragging = True
        self._drag_start_x = cx
        self._drag_offset_x = self.vt.offset_x
        self._drag_start_y = cy
        self._drag_center_price = self.vt.center_price

    def _handle_draw_click(self, cx, cy):
        vt = self.vt
        d = self.data
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
            self.update()

    def mouseMoveEvent(self, e):
        if not self.data:
            return
        cx, cy = e.position().x(), e.position().y()
        self._mx, self._my = cx, cy
        vt = self.vt
        d = self.data

        if self.draw_mode == "box" and self._box_anchor is not None:
            self._box_current = self._box_point(cx, cy)
            self.update()
            return

        if self.draw_mode in ("long", "short") and self._pos_anchor is not None:
            self._pos_current = self._box_point(cx, cy)
            self.update()
            return

        if self.edit_drag:
            t = self.edit_drag["type"]
            if t == "h":
                raw = vt.y_to_price(cy)
                self.h_lines[self.edit_drag["index"]] = round(raw / self.tick_size) * self.tick_size
            elif t == "v":
                self.v_lines[self.edit_drag["index"]] = max(0, min(len(d) - 1, vt.x_to_candle_round(cx)))
            elif t in ("box1", "box2"):
                box = self.boxes[self.edit_drag["index"]]
                idx, price = self._box_point(cx, cy)
                if t == "box1":
                    box["idx1"], box["price1"] = idx, price
                else:
                    box["idx2"], box["price2"] = idx, price
            elif t == "ray":
                ray = self.rays[self.edit_drag["index"]]
                ray["idx"] = max(0, min(len(d) - 1, vt.x_to_candle_round(cx)))
                ray["price"] = round(vt.y_to_price(cy) / self.tick_size) * self.tick_size
            elif t in ("pos_entry", "pos_tp", "pos_sl", "pos_width"):
                pos = self.positions[self.edit_drag["index"]]
                price = round(vt.y_to_price(cy) / self.tick_size) * self.tick_size
                if t == "pos_tp":
                    pos["tp"] = price
                elif t == "pos_sl":
                    pos["sl"] = price
                elif t == "pos_entry":           # move the whole trade (both axes)
                    delta = price - pos["entry"]
                    pos["entry"] += delta; pos["tp"] += delta; pos["sl"] += delta
                    width = pos["idx2"] - pos["idx1"]
                    new_i1 = max(0, min(len(d) - 1 - width, vt.x_to_candle_round(cx)))
                    pos["idx1"] = new_i1
                    pos["idx2"] = new_i1 + width
                else:
                    pos["idx2"] = max(pos["idx1"] + 1,
                                      min(len(d) - 1, vt.x_to_candle_round(cx)))
            self._show_tooltip = False
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

        # default: hover a handle (suppress tooltip, show resize cursor) or show tooltip
        target = self._edit_target(cx, cy)
        if target != self.edit_hover:
            self.edit_hover = target
            self.setCursor(self._edit_cursor(target) if target
                           else Qt.CursorShape.ArrowCursor)
            self.update()
        if target:
            self._show_tooltip = False
        else:
            self._show_tooltip = True
        self.update()

    def mouseReleaseEvent(self, e):
        if self.draw_mode == "box" and self._box_anchor is not None:
            a = self._box_anchor
            b = self._box_point(e.position().x(), e.position().y())
            if a[0] != b[0] or a[1] != b[1]:
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
        if self.edit_drag:
            self.edit_drag = None
            self.setCursor(self._edit_cursor(self.edit_hover))
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
            mp = vt.y_to_price(cy)
            vt.scale_y = max(0.02, min(50.0, vt.scale_y * factor))
            vt.center_price += (cy - vt.price_to_y(mp)) * vt.price_span() / vt.chart_h()
        elif mods & Qt.KeyboardModifier.ShiftModifier:
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
        if self.draw_mode in ("hline", "vline", "delete"):
            return
        idx = vt.x_to_candle_floor(self._mx)
        if idx < 0 or idx >= len(d):
            return
        t = d.times[idx]
        lines = [
            (t.strftime("%m/%d/%Y %H:%M"), C_TEXT_DIM),
            (f"O {_fmt(d.o[idx])}   H {_fmt(d.h[idx])}", QColor(220, 225, 235)),
            (f"L {_fmt(d.l[idx])}   C {_fmt(d.c[idx])}", QColor(220, 225, 235)),
            (f"Vol {int(d.volume[idx]):,}", QColor(220, 225, 235)),
        ]
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
