"""Reusable widgets for the trade replay window."""
import numpy as np
from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHeaderView, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from core.styles import PALETTE


# ── multi-select combo ─────────────────────────────────────────────────
class CheckableComboBox(QComboBox):
    """Combo with checkable value items. No checks = no filter ("All")."""
    changed = pyqtSignal()

    def __init__(self, values, parent=None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        model = QStandardItemModel(self)
        all_item = QStandardItem("(All)")
        all_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        model.appendRow(all_item)
        for v in values:
            item = QStandardItem(str(v))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
            model.appendRow(item)
        self.setModel(model)
        self.view().viewport().installEventFilter(self)
        self._update_text()

    def eventFilter(self, obj, event):
        # toggle on click without closing the popup
        if (event.type() == QEvent.Type.MouseButtonRelease
                and obj is self.view().viewport()):
            index = self.view().indexAt(event.position().toPoint())
            item = self.model().itemFromIndex(index)
            if item is not None:
                if item.row() == 0:      # "(All)" clears every check
                    for r in range(1, self.model().rowCount()):
                        self.model().item(r).setCheckState(Qt.CheckState.Unchecked)
                elif item.isCheckable():
                    state = (Qt.CheckState.Unchecked
                             if item.checkState() == Qt.CheckState.Checked
                             else Qt.CheckState.Checked)
                    item.setCheckState(state)
                self._update_text()
                self.changed.emit()
            return True
        return super().eventFilter(obj, event)

    def checked_values(self) -> set:
        return {self.model().item(r).text()
                for r in range(1, self.model().rowCount())
                if self.model().item(r).checkState() == Qt.CheckState.Checked}

    def _update_text(self) -> None:
        checked = self.checked_values()
        if not checked:
            text = "All"
        elif len(checked) == 1:
            text = next(iter(checked))
        else:
            text = f"{len(checked)} selected"
        self.lineEdit().setText(text)

    def hidePopup(self) -> None:
        super().hidePopup()
        self._update_text()


# ── header with an embedded filter row ─────────────────────────────────
class FilterHeader(QHeaderView):
    """Horizontal header with one filter editor per column below the labels."""
    filters_changed = pyqtSignal()

    _EDITOR_H = 24

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._editors: list = []          # per column: QLineEdit | CheckableComboBox
        self._kinds: list = []            # per column: 'numeric'|'time'|'date'|'categorical'
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self.filters_changed.emit)
        self.setSectionsClickable(True)
        self.sectionResized.connect(lambda *_: self._position_editors())
        self.sectionMoved.connect(lambda *_: self._position_editors())

    _PLACEHOLDER = {
        "numeric": ">5  |  3..8  |  1,4",
        "time": ">10:00",
        "date": ">=2026-01-01",
    }

    def set_columns(self, kinds: list, categorical_values: dict) -> None:
        """kinds[i] for view column i; categorical_values[i] -> distinct values."""
        for e in self._editors:
            e.deleteLater()
        self._editors = []
        self._kinds = kinds
        for i, kind in enumerate(kinds):
            if kind == "categorical":
                e = CheckableComboBox(categorical_values.get(i, []), self)
                e.changed.connect(self._debounce.start)
            else:
                e = QLineEdit(self)
                e.setPlaceholderText(self._PLACEHOLDER[kind])
                e.setClearButtonEnabled(True)
                e.textChanged.connect(self._debounce.start)
            e.setFixedHeight(self._EDITOR_H)
            e.show()
            self._editors.append(e)
        self._position_editors()

    def filters(self) -> dict:
        """view-column index -> spec str (line edits) or checked set (combos)."""
        out = {}
        for i, e in enumerate(self._editors):
            if isinstance(e, CheckableComboBox):
                checked = e.checked_values()
                if checked:
                    out[i] = checked
            else:
                text = e.text().strip()
                if text:
                    out[i] = text
        return out

    def mark_invalid(self, index: int, invalid: bool) -> None:
        e = self._editors[index] if index < len(self._editors) else None
        if isinstance(e, QLineEdit):
            e.setStyleSheet(
                f"border: 1px solid {PALETTE['DANGER']};" if invalid else "")

    def clear_filters(self) -> None:
        for e in self._editors:
            if isinstance(e, QLineEdit):
                e.blockSignals(True)
                e.clear()
                e.blockSignals(False)
                e.setStyleSheet("")

    # geometry: reserve a strip below the labels for the editors
    def sizeHint(self):
        size = super().sizeHint()
        size.setHeight(size.height() + self._EDITOR_H + 4)
        return size

    def updateGeometries(self):
        self.setViewportMargins(0, 0, 0, self._EDITOR_H + 4)
        super().updateGeometries()
        self._position_editors()

    def _position_editors(self) -> None:
        if not self._editors:
            return
        y = self.height() - self._EDITOR_H - 2
        for i, e in enumerate(self._editors):
            if self.isSectionHidden(i):
                e.hide()
                continue
            e.show()
            e.move(self.sectionViewportPosition(i) + 1, y)
            e.resize(max(self.sectionSize(i) - 2, 10), self._EDITOR_H)


# ── stat card ──────────────────────────────────────────────────────────
class StatCard(QFrame):
    """Small titled value box, like the trade-detail cards in the mockup."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        self._title = QLabel(title.upper())
        self._title.setStyleSheet(
            f"color: {PALETTE['TEXT_DIM']}; font-size: 8pt; letter-spacing: 0.5px;")
        self._value = QLabel("—")
        self._value.setStyleSheet(
            f"color: {PALETTE['TEXT_PRI']}; font-size: 12pt; font-weight: 600;")
        lay.addWidget(self._title)
        lay.addWidget(self._value)

    def set_value(self, text: str, color: str = None) -> None:
        self._value.setText(text if text else "—")
        self._value.setStyleSheet(
            f"color: {color or PALETTE['TEXT_PRI']}; font-size: 12pt; font-weight: 600;")


# ── equity sparkline ───────────────────────────────────────────────────
class EquitySparkline(QWidget):
    """Tiny cumulative-ticks curve for the filtered trade set. Click = enlarge."""
    clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(180, 44)
        self.setToolTip("Equity curve (cumulative ticks, filtered trades)\n"
                        "Click to enlarge")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._series = np.array([])

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()

    def set_series(self, series: np.ndarray) -> None:
        self._series = np.asarray(series, dtype=float)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(PALETTE["BG_PANEL"]))
        s = self._series
        if len(s) < 2:
            p.end()
            return
        lo, hi = float(np.min(s)), float(np.max(s))
        lo, hi = min(lo, 0.0), max(hi, 0.0)
        span = (hi - lo) or 1.0
        pad = 3
        xs = np.linspace(pad, w - pad, len(s))
        ys = (h - pad) - (s - lo) / span * (h - 2 * pad)

        y0 = (h - pad) - (0.0 - lo) / span * (h - 2 * pad)
        p.setPen(QPen(QColor(PALETTE["BORDER"]), 1, Qt.PenStyle.DashLine))
        p.drawLine(pad, int(y0), w - pad, int(y0))

        path = QPainterPath()
        path.moveTo(xs[0], ys[0])
        for x, y in zip(xs[1:], ys[1:]):
            path.lineTo(x, y)
        fill = QPainterPath(path)
        fill.lineTo(xs[-1], h - pad)
        fill.lineTo(xs[0], h - pad)
        fill.closeSubpath()
        color = QColor(PALETTE["SUCCESS"] if s[-1] >= 0 else PALETTE["DANGER"])
        fill_c = QColor(color)
        fill_c.setAlpha(38)
        p.fillPath(fill, fill_c)
        p.setPen(QPen(color, 1.4))
        p.drawPath(path)
        p.end()


# ── full equity curve (enlarged, clickable) ────────────────────────────
class EquityCurveView(QWidget):
    """Large cumulative-ticks curve with drawdown shading.

    Clicking a point emits trade_clicked(source_row); hovering shows the
    trade under the cursor.
    """
    trade_clicked = pyqtSignal(int)

    _M_LEFT, _M_RIGHT, _M_TOP, _M_BOT = 54, 16, 14, 30

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(500, 260)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._cum = np.array([])
        self._src_rows = np.array([], dtype=int)
        self._dates: list = []
        self._ticks = np.array([])
        self._hover = -1          # hovered point index
        self._selected = -1       # selected point index (synced from table)

    def set_data(self, cum, ticks, src_rows, dates) -> None:
        self._cum = np.asarray(cum, dtype=float)
        self._ticks = np.asarray(ticks, dtype=float)
        self._src_rows = np.asarray(src_rows, dtype=int)
        self._dates = list(dates)
        self._hover = -1
        self.update()

    def set_selected_source_row(self, src_row) -> None:
        idx = np.where(self._src_rows == src_row)[0] if src_row is not None else []
        self._selected = int(idx[0]) if len(idx) else -1
        self.update()

    # ── geometry ───────────────────────────────────────────────────────
    def _plot_rect(self):
        return (self._M_LEFT, self._M_TOP,
                self.width() - self._M_LEFT - self._M_RIGHT,
                self.height() - self._M_TOP - self._M_BOT)

    def _xy(self):
        x0, y0, w, h = self._plot_rect()
        s = self._cum
        lo = min(float(s.min()), 0.0)
        hi = max(float(s.max()), 0.0)
        span = (hi - lo) or 1.0
        xs = (x0 + np.linspace(0, w, len(s))) if len(s) > 1 else np.array([x0 + w / 2])
        ys = y0 + h - (s - lo) / span * h
        return xs, ys, lo, hi

    def _nearest(self, pos) -> int:
        if not len(self._cum):
            return -1
        xs, ys, _, _ = self._xy()
        d2 = (xs - pos.x()) ** 2 + (ys - pos.y()) ** 2
        i = int(np.argmin(d2))
        return i if d2[i] <= 18 ** 2 else int(np.argmin(np.abs(xs - pos.x())))

    # ── interaction ────────────────────────────────────────────────────
    def mouseMoveEvent(self, event) -> None:
        i = self._nearest(event.position())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, event) -> None:
        self._hover = -1
        self.update()

    def mousePressEvent(self, event) -> None:
        i = self._nearest(event.position())
        if 0 <= i < len(self._src_rows):
            self._selected = i
            self.update()
            self.trade_clicked.emit(int(self._src_rows[i]))

    # ── painting ───────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(PALETTE["BG_BASE"]))
        x0, y0, w, h = self._plot_rect()
        p.setPen(QPen(QColor(PALETTE["BORDER"]), 1))
        p.drawRect(x0, y0, w, h)
        s = self._cum
        if len(s) < 2:
            p.setPen(QColor(PALETTE["TEXT_DIM"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Not enough trades")
            p.end()
            return
        xs, ys, lo, hi = self._xy()

        # y grid + labels
        f = QFont(p.font())
        f.setPointSize(8)
        p.setFont(f)
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            val = lo + (hi - lo) * frac
            y = y0 + h - frac * h
            p.setPen(QPen(QColor(PALETTE["BORDER"]), 1, Qt.PenStyle.DotLine))
            p.drawLine(int(x0), int(y), int(x0 + w), int(y))
            p.setPen(QColor(PALETTE["TEXT_DIM"]))
            p.drawText(QRectF(0, y - 8, x0 - 6, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{val:+.0f}")

        # x labels: a few dates along the curve
        n_lbl = max(2, min(6, len(s) // 15 + 2))
        p.setPen(QColor(PALETTE["TEXT_DIM"]))
        for j in range(n_lbl):
            i = int(round(j * (len(s) - 1) / (n_lbl - 1)))
            p.drawText(QRectF(xs[i] - 45, y0 + h + 4, 90, 16),
                       Qt.AlignmentFlag.AlignHCenter, self._dates[i])

        # zero line
        span = (hi - lo) or 1.0
        y_zero = y0 + h - (0.0 - lo) / span * h
        p.setPen(QPen(QColor(PALETTE["TEXT_DIM"]), 1, Qt.PenStyle.DashLine))
        p.drawLine(int(x0), int(y_zero), int(x0 + w), int(y_zero))

        # drawdown shading: running peak -> curve
        peak = np.maximum.accumulate(s)
        ys_peak = y0 + h - (peak - lo) / span * h
        dd = QPainterPath()
        dd.moveTo(xs[0], ys_peak[0])
        for x, y in zip(xs[1:], ys_peak[1:]):
            dd.lineTo(x, y)
        for x, y in zip(xs[::-1], ys[::-1]):
            dd.lineTo(x, y)
        dd.closeSubpath()
        dd_c = QColor(PALETTE["DANGER"])
        dd_c.setAlpha(26)
        p.fillPath(dd, dd_c)

        # equity line
        path = QPainterPath()
        path.moveTo(xs[0], ys[0])
        for x, y in zip(xs[1:], ys[1:]):
            path.lineTo(x, y)
        color = QColor(PALETTE["SUCCESS"] if s[-1] >= 0 else PALETTE["DANGER"])
        p.setPen(QPen(color, 1.6))
        p.drawPath(path)

        # points (only when they have room to breathe)
        if w / len(s) > 3.5:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            for x, y in zip(xs, ys):
                p.drawEllipse(QPointF(x, y), 2.2, 2.2)

        # selected + hovered markers
        for i, c in ((self._selected, PALETTE["ACCENT_HOV"]),
                     (self._hover, PALETTE["TEXT_PRI"])):
            if 0 <= i < len(s):
                p.setPen(QPen(QColor(c), 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(xs[i], ys[i]), 5, 5)

        # hover readout
        if 0 <= self._hover < len(s):
            i = self._hover
            txt = (f"{self._dates[i]}   trade {i + 1}/{len(s)}   "
                   f"{self._ticks[i]:+.0f} ticks   cum {s[i]:+.0f}")
            p.setPen(QColor(PALETTE["TEXT_PRI"]))
            p.drawText(QRectF(x0, 0, w, self._M_TOP),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                       txt)
        p.end()
