"""Options exposure chart canvas (QPainter).

Bar chart of dealer exposure by strike: ordinal strike slots on the x-axis,
exposure dollars on the y-axis (Viewport's price axis repurposed as a value
axis, negative allowed). Green/red bars, a dimmer stacked segment for
estimated-OI fallback contributions (dealer-flow source), a dashed vertical
line at the underlying price. No drawing tools.
"""
import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core.viewport import Viewport

# ── Layout constants ──────────────────────────────────────────────────
VALUE_AXIS_W  = 60
STRIKE_AXIS_H = 20

# ── Colors ────────────────────────────────────────────────────────────
C_BG          = QColor(13, 17, 23)
C_PANEL       = QColor(19, 27, 42)
C_GRID        = QColor(30, 42, 61)
C_ZERO        = QColor(70, 90, 120)
C_AXIS_TEXT   = QColor(120, 135, 160)
C_POS         = QColor(46, 200, 78)
C_NEG         = QColor(224, 70, 70)
C_UNDERLYING  = QColor(255, 200, 60)
C_TOOLTIP_BG  = QColor(20, 28, 44, 240)
C_TOOLTIP_BD  = QColor(60, 80, 110)
C_TEXT_DIM    = QColor(150, 165, 185)
C_TEXT        = QColor(220, 225, 235)


def _fmt_money(v: float) -> str:
    """$ with B/M/k suffix and sign, e.g. -$1.25B, $310M, $85k, $120."""
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e9:
        return f"{sign}${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.0f}M" if a >= 1e7 else f"{sign}${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:.0f}k"
    return f"{sign}${a:.0f}"


def _fmt_value(v: float, dollars: bool) -> str:
    if dollars:
        return _fmt_money(v)
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e6:
        return f"{sign}{a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}{a / 1e3:.0f}k"
    return f"{sign}{a:.6g}"


def _nice_step(rough: float) -> float:
    """Smallest 1/2/2.5/5 x 10^k >= rough."""
    if rough <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(rough))
    for m in (1.0, 2.0, 2.5, 5.0, 10.0):
        if m * mag >= rough:
            return m * mag
    return 10.0 * mag


class OptionsCanvas(QWidget):
    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.vt = Viewport()
        self.settings = settings
        self.day = None
        self.result = None          # StrikeExposure | None
        self.message = "No data for this selection"
        self._initialized = False
        self._rescale = True

        self._dragging = False
        self._drag_start_x = 0.0
        self._drag_offset_x = 0.0
        self._drag_start_y = 0.0
        self._drag_center_price = 0.0
        self._mx = 0.0
        self._my = 0.0
        self._show_tooltip = False

    # ── public API ────────────────────────────────────────────────────
    def set_day(self, day) -> None:
        self.day = day
        self._initialized = False
        self._rescale = True
        self.update()

    def set_result(self, res) -> None:
        self.result = res
        self.update()

    def set_message(self, msg: str) -> None:
        self.message = msg
        self.update()

    def request_rescale(self) -> None:
        self._rescale = True
        self.update()

    def reset_view(self) -> None:
        self._initialized = False
        self._rescale = True
        self.update()

    # ── view init / scaling ───────────────────────────────────────────
    def _init_view(self) -> None:
        d = self.day
        if d is None or d.n_strikes == 0:
            return
        n = d.n_strikes
        center = n / 2.0
        if self.result is not None and np.isfinite(self.result.F):
            center = float(np.interp(self.result.F, d.strikes_sorted, np.arange(n)))
        visible = min(n, 80)
        chart_w = max(1.0, self.width() - VALUE_AXIS_W)
        slot_needed = chart_w / visible
        self.vt.candle_w = max(0.5, min(200.0, slot_needed / (1 + Viewport.GAP_RATIO)))
        self.vt.offset_x = (center - visible / 2) * self.vt.slot_w()
        self._initialized = True

    def _rescale_y(self) -> None:
        res = self.result
        vt = self.vt
        m = 1.0
        if res is not None:
            # cover both segment extents (primary alone and stacked total)
            hi = max(np.abs(res.total).max(initial=0.0),
                     np.abs(res.primary).max(initial=0.0))
            if np.isfinite(hi) and hi > 0:
                m = hi * 1.1
        vt.price_min = -m
        vt.price_max = m
        vt.center_price = 0.0
        vt.scale_y = 1.0
        self._rescale = False

    # ── painting ──────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), C_BG)

        if self.day is None or self.day.n_strikes == 0:
            self._draw_center_text(p, self.message)
            p.end()
            return

        if not self._initialized and self.width() > 0:
            self._init_view()

        vt = self.vt
        vt.left = VALUE_AXIS_W
        vt.top = 0
        vt.right = self.width()
        vt.bottom = self.height() - STRIKE_AXIS_H

        if self._rescale:
            self._rescale_y()

        self._draw_value_axis(p)
        self._draw_strike_axis(p)
        if self.result is None:
            self._draw_center_text(p, self.message)
            p.end()
            return
        self._draw_bars(p)
        self._draw_underlying_line(p)
        self._draw_header(p)
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

    def _dollars(self) -> bool:
        return self.result is not None and self.result.units_label.startswith("$")

    # ── axes ──────────────────────────────────────────────────────────
    def _draw_value_axis(self, p):
        vt = self.vt
        p.fillRect(QRectF(0, vt.top, VALUE_AXIS_W, vt.chart_h()), C_PANEL)
        vis = vt.price_span()
        vmin = vt.center_price - vis / 2
        vmax = vt.center_price + vis / 2
        step = _nice_step(vis / 8)
        dollars = self._dollars()
        pen = QPen(C_GRID)
        pen.setWidthF(0.5)
        vcur = math.ceil(vmin / step) * step
        while vcur <= vmax:
            y = vt.price_to_y(vcur)
            if vt.top <= y <= vt.bottom:
                if abs(vcur) < step / 2:            # the zero baseline
                    zpen = QPen(C_ZERO)
                    zpen.setWidthF(1.2)
                    p.setPen(zpen)
                else:
                    p.setPen(pen)
                p.drawLine(QPointF(VALUE_AXIS_W, y), QPointF(vt.right, y))
                self._text(p, VALUE_AXIS_W - 4, y + 3, _fmt_value(vcur, dollars),
                           C_AXIS_TEXT, "right", 9)
            vcur += step

    def _draw_strike_axis(self, p):
        vt = self.vt
        d = self.day
        p.fillRect(QRectF(0, self.height() - STRIKE_AXIS_H, vt.right, STRIKE_AXIS_H),
                   C_PANEL)
        if vt.slot_w() <= 0:
            return
        step = max(1, math.ceil(52 / vt.slot_w()))
        for i in range(0, d.n_strikes, step):
            x = vt.candle_x(i) + vt.candle_w / 2
            if x < VALUE_AXIS_W or x > vt.right:
                continue
            self._text(p, x, self.height() - 5, f"{d.strikes_sorted[i]:g}",
                       C_AXIS_TEXT, "center", 9)

    # ── content ───────────────────────────────────────────────────────
    def _visible_slots(self) -> range:
        vt = self.vt
        d = self.day
        lo = max(0, vt.x_to_candle_floor(VALUE_AXIS_W))
        hi = min(d.n_strikes - 1, vt.x_to_candle_floor(vt.right) + 1)
        return range(lo, hi + 1)

    def _draw_bars(self, p):
        vt = self.vt
        res = self.result
        p.save()
        p.setClipRect(QRectF(VALUE_AXIS_W, vt.top, vt.right - VALUE_AXIS_W, vt.chart_h()))
        p.setPen(Qt.PenStyle.NoPen)
        y0 = vt.price_to_y(0.0)
        bar_w = vt.candle_w * 0.8
        dim = max(0.0, min(1.0, self.settings.dim_factor))
        for i in self._visible_slots():
            prim = res.primary[i]
            fall = res.fallback[i]
            x = vt.candle_x(i) + (vt.candle_w - bar_w) / 2
            if prim != 0.0:
                y1 = vt.price_to_y(prim)
                c = C_POS if prim >= 0 else C_NEG
                p.setBrush(c)
                p.drawRect(QRectF(x, min(y0, y1), bar_w, abs(y1 - y0)))
            if fall != 0.0:
                ya = vt.price_to_y(prim)
                yb = vt.price_to_y(prim + fall)
                c = QColor(C_POS if fall >= 0 else C_NEG)
                c.setAlphaF(c.alphaF() * dim)
                p.setBrush(c)
                p.drawRect(QRectF(x, min(ya, yb), bar_w, abs(yb - ya)))
        p.restore()

    def _draw_underlying_line(self, p):
        vt = self.vt
        d = self.day
        res = self.result
        if not np.isfinite(res.F):
            return
        fx = float(np.interp(res.F, d.strikes_sorted, np.arange(d.n_strikes)))
        x = vt.candle_x(fx) + vt.candle_w / 2
        if x < VALUE_AXIS_W or x > vt.right:
            return
        pen = QPen(C_UNDERLYING)
        pen.setWidthF(1.0)
        pen.setDashPattern([5, 4])
        p.setPen(pen)
        p.drawLine(QPointF(x, vt.top), QPointF(x, vt.bottom))
        self._text(p, x + 4, vt.top + 12, f"{res.F:g}", C_UNDERLYING, "left", 10)

    def _draw_header(self, p):
        res = self.result
        net = res.total.sum()
        s = (f"{res.time.strftime('%m/%d %H:%M')}   {res.units_label}   "
             f"net {_fmt_value(net, self._dollars())}")
        self._text(p, VALUE_AXIS_W + 8, 16, s, C_TEXT_DIM, "left", 11)

    # ── mouse ─────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if self.day is None:
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        self._drag_start_x = e.position().x()
        self._drag_offset_x = self.vt.offset_x
        self._drag_start_y = e.position().y()
        self._drag_center_price = self.vt.center_price

    def mouseMoveEvent(self, e):
        if self.day is None:
            return
        cx, cy = e.position().x(), e.position().y()
        self._mx, self._my = cx, cy
        vt = self.vt
        if self._dragging:
            vt.offset_x = self._drag_offset_x - (cx - self._drag_start_x)
            dy = cy - self._drag_start_y
            vt.center_price = self._drag_center_price + dy * vt.price_span() / vt.chart_h()
            self.update()
            return
        self._show_tooltip = True
        self.update()

    def mouseReleaseEvent(self, e):
        self._dragging = False

    def leaveEvent(self, e):
        self._dragging = False
        self._show_tooltip = False
        self.update()

    def wheelEvent(self, e):
        if self.day is None:
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
            vt.candle_w = max(0.5, min(200.0, vt.candle_w * factor))
            vt.offset_x += vt.candle_x(idx) - prev_x
        else:
            vt.offset_x += 60 if dy > 0 else -60
        self.update()

    # ── tooltip ───────────────────────────────────────────────────────
    def _draw_tooltip(self, p):
        vt = self.vt
        d = self.day
        res = self.result
        i = vt.x_to_candle_floor(self._mx)
        if i < 0 or i >= d.n_strikes:
            return
        dollars = self._dollars()
        lines = [
            (f"Strike {d.strikes_sorted[i]:g}", C_TEXT_DIM),
            (f"Total {_fmt_value(res.total[i], dollars)}", C_TEXT),
            (f"Calls {_fmt_value(res.call_part[i], dollars)}   "
             f"Puts {_fmt_value(res.put_part[i], dollars)}", C_TEXT),
        ]
        if res.fallback[i] != 0.0:
            lines.append((f"Flow {_fmt_value(res.primary[i], dollars)}   "
                          f"Est {_fmt_value(res.fallback[i], dollars)}", C_TEXT_DIM))
        lines.append((f"{int(res.n_contracts[i])} contracts", C_TEXT_DIM))
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
