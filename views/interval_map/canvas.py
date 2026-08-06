"""Interval map canvas (QPainter).

Time on the x-axis (ordinal interval columns), actual strikes on the y-axis
(ordinal rows: the Viewport's "price" is a fractional row index; row i spans
[i, i+1) with its dot and label centered at i + 0.5). Each nonzero (row, col)
cell is a dot with area proportional to |exposure| (green positive / red
negative); a blue polyline tracks the underlying price across the day.
No drawing tools.
"""
import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from core.viewport import Viewport
from views.interval_map.interval_compute import DOT_THRESHOLD

# ── Layout constants ──────────────────────────────────────────────────
STRIKE_AXIS_W = 60
TIME_AXIS_H   = 20

# ── Colors ────────────────────────────────────────────────────────────
C_BG          = QColor(13, 17, 23)
C_PANEL       = QColor(19, 27, 42)
C_GRID        = QColor(30, 42, 61)
C_AXIS_TEXT   = QColor(120, 135, 160)
C_POS         = QColor(46, 200, 78)
C_NEG         = QColor(224, 70, 70)
C_LINE        = QColor(80, 160, 255)
C_TOOLTIP_BG  = QColor(20, 28, 44, 240)
C_TOOLTIP_BD  = QColor(60, 80, 110)
C_TEXT_DIM    = QColor(150, 165, 185)
C_TEXT        = QColor(220, 225, 235)


def _fmt_money(v: float) -> str:
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


class IntervalMapCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.vt = Viewport()
        self.grid = None            # IntervalGrid | None
        self.message = "No data for this selection"
        self._initialized = False
        self.dot_scale = 1.0        # full-size dot = dot_scale * grid.vmax

        # sparse nonzero-cell list, rebuilt in set_grid
        self._dot_rows = np.empty(0, dtype=np.int64)
        self._dot_cols = np.empty(0, dtype=np.int64)
        self._dot_frac = np.empty(0)        # |v| / vmax
        self._dot_pos = np.empty(0, dtype=bool)

        self._dragging = False
        self._drag_start_x = 0.0
        self._drag_offset_x = 0.0
        self._drag_start_y = 0.0
        self._drag_center_price = 0.0
        self._mx = 0.0
        self._my = 0.0
        self._show_tooltip = False

    # ── public API ────────────────────────────────────────────────────
    def set_grid(self, grid) -> None:
        prev = self.grid
        same_axes = (
            prev is not None and grid is not None
            and np.array_equal(prev.strikes, grid.strikes)
            and np.array_equal(prev.t_idx, grid.t_idx)
        )
        self.grid = grid
        if not same_axes:
            self._initialized = False
        if grid is not None:
            r, c = np.nonzero(np.abs(grid.total) >= DOT_THRESHOLD * grid.vmax)
            v = grid.total[r, c]
            self._dot_rows, self._dot_cols = r, c
            self._dot_frac = np.abs(v) / grid.vmax
            self._dot_pos = v >= 0
        self.update()

    def set_message(self, msg: str) -> None:
        self.message = msg
        self.update()

    def set_dot_scale(self, scale: float) -> None:
        self.dot_scale = max(1e-4, float(scale))
        self.update()

    def reset_view(self) -> None:
        self._initialized = False
        self.update()

    # ── view init ─────────────────────────────────────────────────────
    def _init_view(self) -> None:
        g = self.grid
        if g is None or g.n_rows == 0:
            return
        n_rows, n_cols = g.n_rows, g.n_cols
        vt = self.vt
        chart_w = max(1.0, self.width() - STRIKE_AXIS_W)
        vt.candle_w = max(0.5, min(200.0,
                                   (chart_w / max(1, n_cols)) / (1 + Viewport.GAP_RATIO)))
        vt.offset_x = 0.0
        vt.price_min = 0.0
        vt.price_max = float(n_rows)
        m = np.isfinite(g.f_row)
        if m.any():
            lo = float(g.f_row[m].min()) + 0.5
            hi = float(g.f_row[m].max()) + 0.5
            pad = max(4.0, 0.25 * (hi - lo))
            span = min(float(n_rows), max(10.0, (hi - lo) + 2 * pad))
            vt.center_price = (lo + hi) / 2
        else:
            span = float(n_rows)
            vt.center_price = n_rows / 2
        vt.scale_y = max(1.0, n_rows / span)
        self._initialized = True

    # ── painting ──────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), C_BG)

        if self.grid is None or self.grid.n_rows == 0:
            self._draw_center_text(p, self.message)
            p.end()
            return

        if not self._initialized and self.width() > 0:
            self._init_view()

        vt = self.vt
        vt.left = STRIKE_AXIS_W
        vt.top = 0
        vt.right = self.width()
        vt.bottom = self.height() - TIME_AXIS_H

        self._draw_strike_axis(p)
        self._draw_time_axis(p)
        self._draw_dots(p)
        self._draw_price_line(p)
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
        return self.grid is not None and self.grid.units_label.startswith("$")

    # ── axes ──────────────────────────────────────────────────────────
    def _draw_strike_axis(self, p):
        vt = self.vt
        g = self.grid
        p.fillRect(QRectF(0, vt.top, STRIKE_AXIS_W, vt.chart_h()), C_PANEL)
        row_px = vt.pixels_per_price()
        if row_px <= 0:
            return
        step = max(1, math.ceil(14 / row_px))
        pen = QPen(C_GRID)
        pen.setWidthF(0.5)
        for i in range(0, g.n_rows, step):
            y = vt.price_to_y(i + 0.5)
            if not (vt.top <= y <= vt.bottom):
                continue
            p.setPen(pen)
            p.drawLine(QPointF(STRIKE_AXIS_W, y), QPointF(vt.right, y))
            self._text(p, STRIKE_AXIS_W - 4, y + 3, f"{g.strikes[i]:g}",
                       C_AXIS_TEXT, "right", 9)

    def _draw_time_axis(self, p):
        vt = self.vt
        g = self.grid
        p.fillRect(QRectF(0, self.height() - TIME_AXIS_H, vt.right, TIME_AXIS_H), C_PANEL)
        if vt.slot_w() <= 0:
            return
        step = max(1, math.ceil(56 / vt.slot_w()))
        for j in range(0, g.n_cols, step):
            x = vt.candle_x(j) + vt.candle_w / 2
            if x < STRIKE_AXIS_W or x > vt.right:
                continue
            self._text(p, x, self.height() - 5, g.times[j].strftime("%H:%M"),
                       C_AXIS_TEXT, "center", 9)

    # ── content ───────────────────────────────────────────────────────
    def _draw_dots(self, p):
        vt = self.vt
        g = self.grid
        if len(self._dot_rows) == 0:
            return
        p.save()
        p.setClipRect(QRectF(STRIKE_AXIS_W, vt.top, vt.right - STRIKE_AXIS_W, vt.chart_h()))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        c0 = max(0, vt.x_to_candle_floor(STRIKE_AXIS_W))
        c1 = min(g.n_cols - 1, vt.x_to_candle_floor(vt.right) + 1)
        r0 = max(0, math.floor(vt.y_to_price(vt.bottom)))
        r1 = min(g.n_rows - 1, math.ceil(vt.y_to_price(vt.top)))
        m = ((self._dot_cols >= c0) & (self._dot_cols <= c1)
             & (self._dot_rows >= r0) & (self._dot_rows <= r1))
        if not m.any():
            p.restore()
            return
        rows, cols = self._dot_rows[m], self._dot_cols[m]
        frac, pos = self._dot_frac[m], self._dot_pos[m]

        # vectorized screen coords (raw viewport formulas)
        xs = vt.left + cols * vt.slot_w() - vt.offset_x + vt.candle_w / 2
        vis = vt.price_span()
        vmin = vt.center_price - vis / 2
        ys = vt.top + vt.chart_h() * (1 - ((rows + 0.5) - vmin) / vis)
        r_max = 0.45 * min(vt.slot_w(), vt.pixels_per_price())
        frac_eff = np.minimum(1.0, frac / self.dot_scale)   # saturate at the adjusted ref
        radii = np.maximum(1.0, r_max * np.sqrt(frac_eff))

        for want_pos, color in ((True, C_POS), (False, C_NEG)):
            sel = pos == want_pos
            if not sel.any():
                continue
            p.setBrush(color)
            for x, y, r in zip(xs[sel], ys[sel], radii[sel]):
                p.drawEllipse(QPointF(x, y), r, r)
        p.restore()

    def _draw_price_line(self, p):
        vt = self.vt
        g = self.grid
        p.save()
        p.setClipRect(QRectF(STRIKE_AXIS_W, vt.top, vt.right - STRIKE_AXIS_W, vt.chart_h()))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(C_LINE)
        pen.setWidthF(1.5)
        p.setPen(pen)
        poly = QPolygonF()
        for j in range(g.n_cols):
            fr = g.f_row[j]
            if not np.isfinite(fr):
                if poly.count() > 1:
                    p.drawPolyline(poly)
                poly = QPolygonF()
                continue
            poly.append(QPointF(vt.candle_x(j) + vt.candle_w / 2,
                                vt.price_to_y(fr + 0.5)))
        if poly.count() > 1:
            p.drawPolyline(poly)
        p.restore()

    def _draw_header(self, p):
        g = self.grid
        ref = g.vmax * self.dot_scale
        s = f"{g.times[0].strftime('%m/%d')}   {g.units_label}   dot max {_fmt_value(ref, self._dollars())}"
        self._text(p, STRIKE_AXIS_W + 8, 16, s, C_TEXT_DIM, "left", 11)

    # ── mouse ─────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if self.grid is None:
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        self._drag_start_x = e.position().x()
        self._drag_offset_x = self.vt.offset_x
        self._drag_start_y = e.position().y()
        self._drag_center_price = self.vt.center_price

    def mouseMoveEvent(self, e):
        if self.grid is None:
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
        if self.grid is None:
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
        g = self.grid
        col = vt.x_to_candle_floor(self._mx)
        row = math.floor(vt.y_to_price(self._my))
        if col < 0 or col >= g.n_cols or row < 0 or row >= g.n_rows:
            return
        dollars = self._dollars()
        lines = [
            (f"{g.times[col].strftime('%a %H:%M')}   Strike {g.strikes[row]:g}", C_TEXT_DIM),
            (f"Total {_fmt_value(g.total[row, col], dollars)}", C_TEXT),
            (f"Calls {_fmt_value(g.call_part[row, col], dollars)}   "
             f"Puts {_fmt_value(g.put_part[row, col], dollars)}", C_TEXT),
        ]
        if np.isfinite(g.F[col]):
            lines.append((f"Underlying {g.F[col]:g}", C_TEXT_DIM))
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
