"""OHLCV chart window."""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)

from core.asset_info import tick_size_for
from views.ohlcv_chart.ohlcv_config import OhlcvConfig
from views.ohlcv_chart.ohlcv_data import load_ohlcv, load_ohlcv_indicators
from views.ohlcv_chart.canvas import OhlcvCanvas
from views.ohlcv_chart.settings_dialog import OhlcvSettingsDialog
from core.styles import PALETTE

VWAP_TYPES = [
    ("Bar · Globex",  "bar_globex"),
    ("Bar · RTH",     "bar_rth"),
    ("Tick · Globex", "tick_globex"),
    ("Tick · RTH",    "tick_rth"),
]


def _sep() -> QWidget:
    w = QWidget()
    w.setFixedWidth(1)
    w.setStyleSheet(f"background-color: {PALETTE['BORDER']};")
    return w


def _tool_icon(kind: str) -> QIcon:
    px = QPixmap(18, 18)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    line = QColor(207, 214, 224)
    if kind == "hline":
        pen = QPen(line); pen.setWidthF(2); p.setPen(pen)
        p.drawLine(2, 9, 16, 9)
    elif kind == "ray":
        pen = QPen(line); pen.setWidthF(2); p.setPen(pen)
        p.drawLine(5, 9, 17, 9)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(line)
        p.drawEllipse(2, 6, 6, 6)
    elif kind == "vline":
        pen = QPen(line); pen.setWidthF(2); p.setPen(pen)
        p.drawLine(9, 2, 9, 16)
    elif kind == "box":
        pen = QPen(line); pen.setWidthF(1.6); p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(3, 4, 12, 10)
    elif kind in ("long", "short"):
        green = QColor(46, 200, 78); purple = QColor(150, 92, 198)
        top, bot = (green, purple) if kind == "long" else (purple, green)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(top); p.drawRect(3, 3, 12, 6)
        p.setBrush(bot); p.drawRect(3, 9, 12, 6)
    p.end()
    return QIcon(px)


class OhlcvWindow(QMainWindow):
    def __init__(self, config: OhlcvConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(
            f"OHLCV  ·  {config.asset}  ·  {config.dataset}  ·  {config.date}"
        )
        self.showMaximized()

        self.canvas = OhlcvCanvas()
        self._reload_chart_data()
        self.canvas.state_changed.connect(self._sync_buttons)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self.canvas, 1)
        self.setCentralWidget(central)

        self._sync_buttons()

    def set_date(self, date: str) -> None:
        """Reload this chart for a new anchor date (keeps its own days-back)."""
        self.config.date = date
        self.setWindowTitle(
            f"OHLCV  ·  {self.config.asset}  ·  {self.config.dataset}  ·  {date}")
        self._reload_chart_data()

    def _reload_chart_data(self) -> None:
        config = self.config
        data = load_ohlcv(config)
        self.canvas.set_data(
            data,
            tick_size_for(config.asset),
            focus_last_session=config.tf_unit in ("Minutes", "Hours"),
        )
        if data is not None and config.has_indicators():
            self.canvas.set_indicators(load_ohlcv_indicators(config, data.times))
        else:
            self.canvas.set_indicators(None)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {PALETTE['BG_PANEL']};")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        has_ind = self.config.has_indicators()

        self.btn_vwap = self._toggle("VWAP", lambda: self.canvas.toggle_layer("vwap"))
        self.vwap_type_combo = QComboBox()
        for label, key in VWAP_TYPES:
            self.vwap_type_combo.addItem(label, key)
        self.vwap_type_combo.setFixedWidth(120)
        self.vwap_type_combo.currentIndexChanged.connect(
            lambda i: self.canvas.set_vwap_type(self.vwap_type_combo.itemData(i)))

        self.btn_vwap.setEnabled(has_ind)
        self.vwap_type_combo.setEnabled(has_ind)
        if not has_ind:
            self.btn_vwap.setToolTip("No indicators dataset selected")

        row.addWidget(self.btn_vwap)
        row.addWidget(self.vwap_type_combo)

        row.addWidget(_sep())

        self.btn_hline  = self._icon("hline", "Horizontal line",   lambda: self.canvas.set_draw_mode("hline"))
        self.btn_ray    = self._icon("ray",   "Ray — extends right", lambda: self.canvas.set_draw_mode("ray"))
        self.btn_vline  = self._icon("vline", "Vertical line",      lambda: self.canvas.set_draw_mode("vline"))
        self.btn_box    = self._icon("box",   "Box",                lambda: self.canvas.set_draw_mode("box"))
        self.btn_long   = self._icon("long",  "Long position",      lambda: self.canvas.set_draw_mode("long"))
        self.btn_short  = self._icon("short", "Short position",     lambda: self.canvas.set_draw_mode("short"))
        self.btn_delete = self._toggle("Delete", lambda: self.canvas.set_draw_mode("delete"))
        for b in (self.btn_hline, self.btn_ray, self.btn_vline, self.btn_box,
                  self.btn_long, self.btn_short, self.btn_delete):
            row.addWidget(b)

        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self.canvas.clear_all)
        row.addWidget(btn_clear)

        row.addWidget(_sep())

        btn_reset = QPushButton("Reset View")
        btn_reset.clicked.connect(self.canvas.reset_view)
        row.addWidget(btn_reset)

        row.addStretch(1)

        gear = QPushButton("⚙")
        gear.setFixedWidth(36)
        gear.setToolTip("Chart settings")
        gear.clicked.connect(self._open_settings)
        row.addWidget(gear)
        return bar

    def _toggle(self, text: str, handler) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True)
        b.clicked.connect(handler)
        return b

    def _icon(self, kind: str, tooltip: str, handler) -> QPushButton:
        b = QPushButton()
        b.setIcon(_tool_icon(kind))
        b.setIconSize(QSize(18, 18))
        b.setCheckable(True)
        b.setToolTip(tooltip)
        b.setFixedWidth(36)
        b.clicked.connect(handler)
        return b

    def _open_settings(self) -> None:
        dlg = getattr(self, "_settings_dlg", None)
        if dlg is None:
            dlg = OhlcvSettingsDialog(
                self.canvas.general_settings,
                on_change=self.canvas.update,
                parent=self,
            )
            self._settings_dlg = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _sync_buttons(self) -> None:
        self.btn_vwap.setChecked(self.canvas.layers["vwap"])
        mode = self.canvas.draw_mode
        self.btn_hline.setChecked(mode == "hline")
        self.btn_ray.setChecked(mode == "ray")
        self.btn_vline.setChecked(mode == "vline")
        self.btn_box.setChecked(mode == "box")
        self.btn_long.setChecked(mode == "long")
        self.btn_short.setChecked(mode == "short")
        self.btn_delete.setChecked(mode == "delete")
