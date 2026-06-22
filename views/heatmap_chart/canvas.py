"""Order-book heatmap canvas (QPainter).

Renders resting liquidity (bid_depth / ask_depth) as a colored grid over time,
with best-bid / best-ask lines and a right-edge per-price quantity ladder for
the rightmost visible second.  Shares the drawing-tool set with the other
charts (hline, ray, vline, box, long/short positions, edit, delete).
"""
import math
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core.viewport import Viewport
from views.heatmap_chart.heatmap_settings import HeatmapSettings

# ── Layout constants ──────────────────────────────────────────────────
PRICE_AXIS_W  = 60
DOM_PANEL_W   = 58
TIME_AXIS_H   = 20
HIT_THRESHOLD = 6
HANDLE_R      = 5

# ── Colors ────────────────────────────────────────────────────────────
C_BG          = QColor(13, 17, 23)
C_PANEL       = QColor(19, 27, 42)
C_GRID        = QColor(30, 42, 61)
C_AXIS_TEXT   = QColor(120, 135, 160)

C_BID_LINE    = QColor(60, 220, 130)
C_ASK_LINE    = QColor(235, 80, 80)
C_OHLC        = QColor(200, 205, 215)   # gray price (OHLC) bars
C_BID_TINT    = QColor(46, 200, 120)
C_ASK_TINT    = QColor(220, 90, 90)
C_DOM_TEXT    = QColor(225, 232, 242)

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

# Heatmap colormap stops: (t, r, g, b). dark -> teal -> green -> yellow -> orange -> red.
_HEAT_STOPS = [
    (0.00,  6,  14,  28),
    (0.18,  10,  70,  90),
    (0.38,  20, 150, 120),
    (0.58, 120, 200,  60),
    (0.74, 240, 220,  50),
    (0.88, 245, 150,  30),
    (1.00, 235,  45,  35),
]


def _build_heat_lut(n=256):
    lut = []
    for k in range(n):
        t = k / (n - 1)
        # locate segment
        for j in range(len(_HEAT_STOPS) - 1):
            t0, r0, g0, b0 = _HEAT_STOPS[j]
            t1, r1, g1, b1 = _HEAT_STOPS[j + 1]
            if t0 <= t <= t1:
                f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                lut.append(QColor(int(r0 + (r1 - r0) * f),
                                  int(g0 + (g1 - g0) * f),
                                  int(b0 + (b1 - b0) * f)))
                break
        else:
            r, g, b = _HEAT_STOPS[-1][1:]
            lut.append(QColor(r, g, b))
    return lut


_HEAT_LUT = _build_heat_lut(256)
# target on-screen width (px) of one pyramid bucket when zoomed out
_TARGET_BUCKET_PX = 3.0
# numpy RGBA copy of the LUT for vectorized image rendering
_HEAT_LUT_NP = np.array(
    [[c.red(), c.green(), c.blue(), 255] for c in _HEAT_LUT], dtype=np.uint8)


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


class HeatmapCanvas(QWidget):
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

        self.layers = {"lines": True, "dom": True}
        self.settings = HeatmapSettings.load()
        self.pyramid = None

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
        self.layers["dom"] = self.settings.show_dom_panel
        self.update()

    def set_pyramid(self, pyr) -> None:
        """Aggregation pyramid for fast zoomed-out rendering (None = exact only)."""
        self.pyramid = pyr
        self.update()

    def toggle_layer(self, name: str) -> None:
        if name in self.layers:
            self.layers[name] = not self.layers[name]
            if name == "dom":
                self.settings.show_dom_panel = self.layers[name]
                self.settings.save()
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

    def apply_settings(self) -> None:
        """Reconcile live settings (called by the settings dialog on change)."""
        self.layers["dom"] = self.settings.show_dom_panel
        self.state_changed.emit()
        self.update()

    def reset_view(self) -> None:
        self._init_view()
        self.update()

    # ── view init ─────────────────────────────────────────────────────
    _INIT_WINDOW_SEC = 1800   # open zoomed to ~30 min

    def _rth_open_index(self) -> int:
        """First index at/after the RTH open on the session's main day."""
        d = self.data
        times = d.times
        if not times:
            return 0
        target = self.settings.rth_start_min()
        # main day = the session that starts at the latest session boundary
        start = d.session_starts[-1] if d.session_starts else 0
        for i in range(start, len(times)):
            t = times[i]
            if t.hour * 60 + t.minute >= target and t.hour < 18:
                return i
        return start

    def _init_view(self) -> None:
        d = self.data
        if not d or len(d) == 0:
            return
        n = len(d)
        start_idx = self._rth_open_index()
        visible = min(self._INIT_WINDOW_SEC, max(1, n - start_idx))
        if visible < self._INIT_WINDOW_SEC // 4:
            # RTH open not really in this (time-filtered) data — fall back
            start_idx = 0
            visible = min(self._INIT_WINDOW_SEC, n)
        end_idx = min(n, start_idx + visible)

        seg_l = d.l[start_idx:end_idx]
        seg_h = d.h[start_idx:end_idx]
        pmin = float(np.nanmin(seg_l)) if seg_l.size else 0.0
        pmax = float(np.nanmax(seg_h)) if seg_h.size else 0.0
        if not math.isfinite(pmin) or not math.isfinite(pmax) or pmax <= pmin:
            pmin = float(np.nanmin(d.c)) if n else 0.0
            pmax = pmin + self.tick_size * 40
        # a little vertical padding around the window's range
        pad = (pmax - pmin) * 0.15 + self.tick_size
        self.vt.price_min = pmin - pad
        self.vt.price_max = pmax + pad
        self.vt.center_price = (pmin + pmax) / 2
        self.vt.scale_y = 1.0

        chart_w = max(1.0, self.width() - PRICE_AXIS_W - self._dom_w())
        slot_needed = chart_w / visible
        self.vt.candle_w = max(0.01, min(120.0, slot_needed / (1 + Viewport.GAP_RATIO)))
        self.vt.offset_x = start_idx * self.vt.slot_w()
        self._initialized = True

    def _dom_w(self) -> int:
        return DOM_PANEL_W if self.layers.get("dom") else 0

    def _is_rth(self, sec_idx: int) -> bool:
        tod = self.data.tod_min
        i = max(0, min(len(tod) - 1, int(sec_idx)))
        s = self.settings
        return s.rth_start_min() <= int(tod[i]) < s.rth_end_min()

    def _session_params(self, is_rth: bool):
        """(ref, inv_contrast, high) for the ETH or RTH color scale."""
        s = self.settings
        if is_rth:
            ref, contrast, high = s.rth_max_ref, s.rth_contrast, s.rth_high_contrast
            auto = getattr(self.pyramid, "ref_rth", 0.0) if self.pyramid else 0.0
        else:
            ref, contrast, high = s.eth_max_ref, s.eth_contrast, s.eth_high_contrast
            auto = getattr(self.pyramid, "ref_eth", 0.0) if self.pyramid else 0.0
        if not (ref and ref > 0):
            ref = auto or (getattr(self.data, "default_ref", 0.0) or 1.0)
        return float(ref) if ref > 0 else 1.0, 1.0 / max(0.05, contrast), max(0.05, high)

    def _use_pyramid(self) -> bool:
        # Render from the precomputed pyramid at every zoom level (its 1s base
        # is exact per-second). The exact per-column path is only a fallback
        # for when the pyramid couldn't be built.
        return self.pyramid is not None

    def _pick_level(self) -> int:
        """Pyramid level for the current zoom — aim for ~a few px per bucket so
        we never oversample below pixel resolution when zoomed out."""
        slot = self.vt.slot_w()
        spp = (1.0 / slot) if slot > 0 else 1e9
        return self.pyramid.pick_level(spp * _TARGET_BUCKET_PX)

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
        vt.top = 0
        vt.right = self.width() - self._dom_w()
        vt.bottom = self.height() - TIME_AXIS_H

        use_pyr = self._use_pyramid()
        self._draw_price_axis(p)
        self._draw_time_axis(p)
        if use_pyr:
            self._draw_heatmap_pyramid(p)
        else:
            self._draw_heatmap(p)
        if self.layers["lines"]:
            self._draw_ohlc(p, pyramid=use_pyr)
        if self.layers["dom"]:
            self._draw_dom_panel(p)
        self._draw_lines(p)
        self._draw_rays(p)
        self._draw_boxes(p)
        self._draw_positions(p)
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
        p.fillRect(QRectF(0, self.height() - TIME_AXIS_H, self.width(), TIME_AXIS_H), C_PANEL)
        slot = vt.slot_w()
        # aim for a label roughly every ~80px
        step = max(1, int(round(80 / slot))) if slot > 0 else 1
        i = 0
        n = len(d)
        while i < n:
            x = vt.candle_x(i) + vt.candle_w / 2
            if PRICE_AXIS_W <= x <= vt.right:
                self._text(p, x, self.height() - 5, d.times[i].strftime("%H:%M:%S"),
                           C_AXIS_TEXT, "center", 9)
            i += step

    # ── heatmap ───────────────────────────────────────────────────────
    def _draw_heatmap(self, p):
        """Render resting liquidity into an RGBA image (numpy) and blit it.

        Each visible second is one column; each price level one cell, colored by
        resting quantity.  Vectorized per column so a fully zoomed-out 82,800s
        session paints in well under a frame.
        """
        vt = self.vt
        d = self.data
        n = len(d)
        left = int(round(vt.left))
        right = int(round(vt.right))
        topp = int(round(vt.top))
        botp = int(round(vt.bottom))
        W = right - left
        H = botp - topp
        if W <= 0 or H <= 0:
            return

        crop = max(1, int(self.settings.crop_ticks))
        tick = self.tick_size

        vis = vt.price_span()
        vmin = vt.center_price - vis / 2          # price at the bottom edge
        chart_h = vt.chart_h()
        ptop = vmin + vis                          # price at the top edge
        pbot = vmin
        ch = max(1, int(round(vt.tick_px(tick))))  # cell height in pixels

        slot = vt.slot_w()
        step = 1 if slot >= 1.0 else max(1, int(math.ceil(1.0 / slot)))
        first = max(0, vt.x_to_candle_floor(vt.left))
        last = min(n - 1, vt.x_to_candle_round(vt.right))

        img = np.empty((H, W, 4), dtype=np.uint8)
        img[..., 0] = C_BG.red()
        img[..., 1] = C_BG.green()
        img[..., 2] = C_BG.blue()
        img[..., 3] = 255

        offs = np.arange(ch, dtype=np.int32) if ch > 1 else None

        i = first
        while i <= last:
            xa = int(round(vt.candle_x(i) - left))
            xb = int(round(vt.candle_x(min(i + step, n)) - left))
            if xb <= xa:
                xb = xa + 1
            xa = max(0, xa)
            xb = min(W, xb)
            if xa >= W or xb <= 0 or xa >= xb:
                i += step
                continue

            bb = d.best_bid[i]
            ba = d.best_ask[i]
            if math.isfinite(bb) and math.isfinite(ba):
                mid = (bb + ba) / 2
            elif math.isfinite(d.c[i]):
                mid = d.c[i]
            else:
                i += step
                continue
            lo = mid - crop * tick
            hi = mid + crop * tick

            bp, bq, ap, aq = d.level_arrays(i)
            prices = np.concatenate((bp, ap)) if bp.size or ap.size else bp
            qtys = np.concatenate((bq, aq)) if bq.size or aq.size else bq
            if prices.size == 0:
                i += step
                continue

            mask = (qtys > 0) & (prices >= lo) & (prices <= hi) & (prices >= pbot) & (prices <= ptop)
            prices = prices[mask]
            qtys = qtys[mask]
            if prices.size == 0:
                i += step
                continue

            rows = (chart_h * (1.0 - (prices - vmin) / vis)).astype(np.int32)
            ref, inv_contrast, high = self._session_params(self._is_rth(i))
            t = np.clip(qtys / ref, 0.0, 1.0) ** inv_contrast
            t = t ** high
            idx = np.clip((t * 255).astype(np.int32), 0, 255)
            colors = _HEAT_LUT_NP[idx]

            order = np.argsort(qtys, kind="stable")   # hottest assigned last
            rows = rows[order]
            colors = colors[order]

            if offs is not None:
                rr = (rows[:, None] + offs[None, :]).reshape(-1)
                cc = np.repeat(colors, ch, axis=0)
            else:
                rr, cc = rows, colors
            valid = (rr >= 0) & (rr < H)
            rr = rr[valid]
            if rr.size:
                img[rr, xa:xb, :] = cc[valid][:, None, :]
            i += step

        self._heat_img = img  # keep a reference alive during drawImage
        qimg = QImage(img.data, W, H, 4 * W, QImage.Format.Format_RGBA8888)
        p.drawImage(QPointF(left, topp), qimg)

    def _draw_heatmap_pyramid(self, p):
        """Zoomed-out render from the precomputed aggregation pyramid.

        Builds a small (price-bin × time-bucket) color image from one pyramid
        level and lets QPainter scale it across the chart rect — a single blit,
        no per-column Python loop.
        """
        vt = self.vt
        d = self.data
        pyr = self.pyramid
        n = len(d)
        L = self._pick_level()
        lv = pyr.levels[L]
        B = lv["B"]
        depth = lv["depth"]            # int16 [nbuckets, nbins]
        nbk, nbins = depth.shape

        # visible bucket range (a bucket spans B seconds = B candle slots)
        first = max(0, vt.x_to_candle_floor(vt.left))
        last = min(n - 1, vt.x_to_candle_round(vt.right))
        b0 = first // B
        b1 = min(nbk - 1, last // B)
        if b1 < b0:
            return

        # visible price-bin range
        vis = vt.price_span()
        vmin = vt.center_price - vis / 2
        ptop = vmin + vis
        bin_lo = max(0, int((vmin - pyr.p0) / pyr.tick))
        bin_hi = min(nbins - 1, int((ptop - pyr.p0) / pyr.tick) + 1)
        if bin_hi < bin_lo:
            return

        sub = depth[b0:b1 + 1, bin_lo:bin_hi + 1]          # [nb, nbp]
        # per-bucket session params (ETH vs RTH) from each bucket's first second
        secs = np.clip(np.arange(b0, b1 + 1) * B, 0, n - 1)
        tod = self.data.tod_min[secs]
        is_rth = (tod >= self.settings.rth_start_min()) & (tod < self.settings.rth_end_min())
        ref_e, inv_e, hi_e = self._session_params(False)
        ref_r, inv_r, hi_r = self._session_params(True)
        ref = np.where(is_rth, ref_r, ref_e).astype(np.float32)[:, None]
        inv_c = np.where(is_rth, inv_r, inv_e).astype(np.float32)[:, None]
        high = np.where(is_rth, hi_r, hi_e).astype(np.float32)[:, None]
        t = np.clip(sub.astype(np.float32) / ref, 0.0, 1.0) ** inv_c
        t = t ** high
        idx = np.clip((t * 255).astype(np.int32), 0, 255)
        colors = _HEAT_LUT_NP[idx]                          # [nb, nbp, 4]
        # orient image: rows = price bins descending (high price on top), cols = buckets
        img = np.ascontiguousarray(np.transpose(colors, (1, 0, 2))[::-1])
        self._heat_img = img
        Hh, Ww = img.shape[0], img.shape[1]
        qimg = QImage(img.data, Ww, Hh, 4 * Ww, QImage.Format.Format_RGBA8888)

        # target rect in screen space
        x_left = vt.candle_x(b0 * B)
        x_right = vt.candle_x((b1 + 1) * B)
        y_top = vt.price_to_y(pyr.price_of_bin(bin_hi) + pyr.tick / 2)
        y_bot = vt.price_to_y(pyr.price_of_bin(bin_lo) - pyr.tick / 2)
        target = QRectF(x_left, y_top, x_right - x_left, y_bot - y_top)
        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        p.drawImage(target, qimg)
        p.restore()

    # ── price (gray OHLC bars) ─────────────────────────────────────────
    def _draw_ohlc(self, p, pyramid=False):
        """Gray OHLC bars: a vertical high→low line with a left tick for open
        and a right tick for close, per time bucket. Shows O/H/L/C without
        assuming whether the high or the low printed first within the bar.
        """
        vt = self.vt
        d = self.data
        n = len(d)
        if pyramid and self.pyramid is not None:
            lv = self.pyramid.levels[self._pick_level()]
            B = lv["B"]
            nbk = lv["o"].shape[0]
            first = max(0, vt.x_to_candle_floor(vt.left))
            last = min(n - 1, vt.x_to_candle_round(vt.right))
            b0 = first // B
            b1 = min(nbk - 1, last // B)
            oo, hh, ll, cc = lv["o"], lv["h"], lv["l"], lv["c"]
            spans = ((b, b * B, (b + 1) * B) for b in range(b0, b1 + 1))
        else:
            first = max(0, vt.x_to_candle_floor(vt.left))
            last = min(n - 1, vt.x_to_candle_round(vt.right))
            oo, hh, ll, cc = d.o, d.h, d.l, d.c
            spans = ((i, i, i + 1) for i in range(first, last + 1))

        p.save()
        p.setClipRect(QRectF(PRICE_AXIS_W, vt.top, vt.right - PRICE_AXIS_W, vt.chart_h()))
        pen = QPen(C_OHLC)
        pen.setWidthF(1.0)
        p.setPen(pen)
        for k, c0, c1 in spans:
            h = hh[k]
            if not math.isfinite(h):
                continue
            o, l, c = oo[k], ll[k], cc[k]
            x0 = vt.candle_x(c0)
            x1 = vt.candle_x(c1)
            xc = (x0 + x1) / 2
            yh = vt.price_to_y(h)
            yl = vt.price_to_y(l)
            p.drawLine(QPointF(xc, yh), QPointF(xc, yl))
            tick = min((x1 - x0) * 0.42, 7.0)
            if tick >= 1.0:
                yo = vt.price_to_y(o)
                yc = vt.price_to_y(c)
                p.drawLine(QPointF(xc - tick, yo), QPointF(xc, yo))   # open (left)
                p.drawLine(QPointF(xc, yc), QPointF(xc + tick, yc))   # close (right)
        p.restore()

    # ── DOM ladder (rightmost visible second) ─────────────────────────
    def _draw_dom_panel(self, p):
        vt = self.vt
        d = self.data
        n = len(d)
        if n == 0:
            return
        idx = vt.x_to_candle_floor(vt.right)
        idx = max(0, min(n - 1, idx))
        px0 = self.width() - DOM_PANEL_W

        p.fillRect(QRectF(px0, vt.top, DOM_PANEL_W, self.height() - vt.top), C_PANEL)
        pen = QPen(C_GRID); pen.setWidthF(1)
        p.setPen(pen)
        p.drawLine(QPointF(px0, vt.top), QPointF(px0, vt.bottom))

        # header: the second this ladder reflects
        self._text(p, px0 + DOM_PANEL_W / 2, vt.top + 12,
                   d.times[idx].strftime("%H:%M:%S"), C_AXIS_TEXT, "center", 9)

        ptop = vt.y_to_price(vt.top)
        pbot = vt.y_to_price(vt.bottom)
        if ptop < pbot:
            ptop, pbot = pbot, ptop
        cell_h = vt.tick_px(self.tick_size)
        ref, _inv, _hi = self._session_params(self._is_rth(idx))
        show_text = cell_h >= 9

        bid, ask = d.levels(idx)
        for book, tint in ((bid, C_BID_TINT), (ask, C_ASK_TINT)):
            for price, qty in book.items():
                if qty <= 0 or not (pbot <= price <= ptop):
                    continue
                y = vt.price_to_y(price)
                if y < vt.top + 16 or y > vt.bottom:
                    continue
                t = min(1.0, qty / ref) if ref > 0 else 0.0
                bar_w = max(1.0, t * (DOM_PANEL_W - 4))
                bg = QColor(tint)
                bg.setAlpha(70)
                p.fillRect(QRectF(px0 + 2, y - max(1.0, cell_h) / 2,
                                  bar_w, max(1.0, min(cell_h, 14))), bg)
                if show_text:
                    self._text(p, self.width() - 4, y + 3, str(int(qty)),
                               C_DOM_TEXT, "right", min(11, cell_h * 0.7))

    # ── drawing objects (shared tool set) ─────────────────────────────
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
                lbl = d.times[idx].strftime("%H:%M:%S")
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
        self._text(p, x, vt.top + 14, d.times[idx].strftime("%H:%M:%S"), C_VLINE, "center", 10)
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
            if abs(cy - vt.price_to_y(price)) <= HIT_THRESHOLD:
                return {"type": "h", "index": i}
        for i, idx in enumerate(self.v_lines):
            x = vt.candle_x(idx) + vt.candle_w / 2
            if abs(cx - x) <= HIT_THRESHOLD:
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
            self._pos_anchor = self._box_point(cx, cy)
            self._pos_current = self._pos_anchor
            self._show_tooltip = False
            self.update()
            return

        if self.draw_mode in ("hline", "vline", "ray", "delete"):
            self._handle_draw_click(cx, cy)
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
                    elif t == "pos_entry":
                        delta = price - pos["entry"]
                        pos["entry"] += delta; pos["tp"] += delta; pos["sl"] += delta
                    else:
                        pos["idx2"] = max(pos["idx1"] + 1,
                                          min(len(d) - 1, vt.x_to_candle_round(cx)))
                    self._show_tooltip = False
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
        if self.draw_mode == "edit" and self.edit_drag:
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
            mp = vt.y_to_price(cy)
            vt.scale_y = max(0.02, min(5000.0, vt.scale_y * factor))
            vt.center_price += (cy - vt.price_to_y(mp)) * vt.price_span() / vt.chart_h()
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            idx = vt.x_to_candle_floor(cx)
            prev_x = vt.candle_x(idx)
            vt.candle_w = max(0.005, min(400.0, vt.candle_w * factor))
            vt.offset_x += vt.candle_x(idx) - prev_x
        else:
            vt.offset_x += 60 if dy > 0 else -60
        self.update()

    # ── tooltip ───────────────────────────────────────────────────────
    def _draw_tooltip(self, p):
        vt = self.vt
        d = self.data
        if self.draw_mode in ("hline", "vline", "delete", "edit"):
            return
        idx = vt.x_to_candle_floor(self._mx)
        if idx < 0 or idx >= len(d):
            return
        t = d.times[idx]
        # qty at the hovered price level
        price = round(vt.y_to_price(self._my) / self.tick_size) * self.tick_size
        bid, ask = d.levels(idx)
        q = bid.get(price, ask.get(price, 0))
        bb = d.best_bid[idx]
        ba = d.best_ask[idx]
        bb_s = _fmt(bb) if math.isfinite(bb) else "—"
        ba_s = _fmt(ba) if math.isfinite(ba) else "—"
        lines = [
            (t.strftime("%m/%d %H:%M:%S"), C_TEXT_DIM),
            (f"O {_fmt(d.o[idx])}  H {_fmt(d.h[idx])}", QColor(220, 225, 235)),
            (f"L {_fmt(d.l[idx])}  C {_fmt(d.c[idx])}", QColor(220, 225, 235)),
            (f"Vol {int(d.volume[idx]):,}", QColor(220, 225, 235)),
            (f"Bid {bb_s}   Ask {ba_s}", QColor(200, 215, 230)),
            (f"@ {_fmt(price)}: {int(q)} resting", QColor(245, 220, 130)),
        ]
        f = QFont("monospace")
        f.setPixelSize(11)
        fm = QFontMetricsF(f)
        line_h = 16
        pad = 8
        w = max(fm.horizontalAdvance(s) for s, _ in lines) + pad * 2
        h = line_h * len(lines) + pad * 2
        tx = min(self._mx + 12, self.width() - w - 2)
        ty = max(self._my - 10, 0)
        ty = min(ty, self.height() - h - 2)
        p.setBrush(C_TOOLTIP_BG)
        p.setPen(QPen(C_TOOLTIP_BD, 1))
        p.drawRoundedRect(QRectF(tx, ty, w, h), 4, 4)
        yy = ty + pad + 11
        for s, color in lines:
            self._text(p, tx + pad, yy, s, color, "left", 11)
            yy += line_h
