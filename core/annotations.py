"""Plugin annotation overlay, shared by the footprint and OHLCV canvases.

Annotations are script-drawn furniture (colored lines/rays/boxes/text) kept in
`canvas.annotations`. Unlike the interactive drawings they are anchored by
**timestamp** (epoch ns) and resolved to candle indices at paint time, so they
survive timeframe and date reloads without any drawing_anchors support — and
they are deliberately not hit-testable, draggable, or deletable by click.

Dict shapes (colors are (r, g, b, a) tuples, resolved in trade_replay.helpers):
  {"kind": "hline", "price", "color", "label", "width", "dash"}
  {"kind": "vline", "ts", "color", "label", "width"}
  {"kind": "ray",   "ts", "price", "color", "label", "width"}
  {"kind": "box",   "ts1", "ts2", "price1", "price2", "color", "fill_alpha", "width"}
  {"kind": "text",  "ts", "price", "text", "color", "px"}
"""
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPen

from core.drawing_anchors import times_ns_of


def draw_annotations(canvas, p) -> None:
    """Render canvas.annotations. Called from paintEvent of both canvases."""
    ann = getattr(canvas, "annotations", None)
    if not ann:
        return
    d = canvas.data
    if d is None or not len(d):
        return
    vt = canvas.vt
    t = times_ns_of(d)

    def x_of(ts, clamp=False):
        if not clamp and (ts < t[0] or ts > t[-1]):
            return None   # a clamped v-line would lie about its time
        idx = int(np.clip(np.searchsorted(t, ts, side="right") - 1, 0, len(t) - 1))
        return vt.candle_x(idx) + vt.candle_w / 2

    p.save()
    p.setClipRect(QRectF(vt.left, vt.top, vt.right - vt.left, vt.chart_h()))
    for a in ann:
        col = QColor(*a["color"])
        kind = a["kind"]
        if kind == "hline":
            y = vt.price_to_y(a["price"])
            pen = QPen(col)
            pen.setWidthF(a.get("width", 1.0))
            if a.get("dash", True):
                pen.setDashPattern([4, 4])
            p.setPen(pen)
            p.drawLine(QPointF(vt.left, y), QPointF(vt.right, y))
            label = a.get("label")
            text = f"{label} {a['price']:g}" if label else f"{a['price']:g}"
            canvas._text(p, vt.left + 4, y - 3, text, col, "left", 10)
        elif kind == "vline":
            x = x_of(a["ts"])
            if x is None:
                continue
            pen = QPen(col)
            pen.setWidthF(a.get("width", 1.0))
            p.setPen(pen)
            p.drawLine(QPointF(x, vt.top), QPointF(x, vt.bottom))
            if a.get("label"):
                canvas._text(p, x, vt.top + 14, a["label"], col, "center", 10)
        elif kind == "ray":
            x = max(vt.left, x_of(a["ts"], clamp=True))
            y = vt.price_to_y(a["price"])
            pen = QPen(col)
            pen.setWidthF(a.get("width", 1.6))
            p.setPen(pen)
            p.drawLine(QPointF(x, y), QPointF(vt.right, y))
            if a.get("label"):
                canvas._text(p, x + 4, y - 3, a["label"], col, "left", 10)
        elif kind == "box":
            x1 = x_of(a["ts1"], clamp=True)
            x2 = x_of(a["ts2"], clamp=True)
            y1 = vt.price_to_y(a["price1"])
            y2 = vt.price_to_y(a["price2"])
            rect = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
            fill = QColor(col)
            fill.setAlpha(a.get("fill_alpha", 40))
            p.fillRect(rect, fill)
            pen = QPen(col)
            pen.setWidthF(a.get("width", 1.6))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
        elif kind == "text":
            x = x_of(a["ts"], clamp=True)
            canvas._text(p, x, vt.price_to_y(a["price"]) - 3, a["text"], col,
                         "center", a.get("px", 10))
    p.restore()
