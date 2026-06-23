"""Footprint chart window.

Hosts the toolbar (layer toggles, indicator/big-trade controls, drawing tools)
and the canvas. Loads candle, indicator, and big-trade data on open.
"""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton,
    QVBoxLayout, QWidget,
)

from core.asset_info import tick_size_for
from views.footprint_chart.footprint_config import FootprintConfig
from views.footprint_chart.footprint_data import (
    load_candles, load_indicators, load_big_trades, load_composite_volume,
)
from core.styles import PALETTE
from views.footprint_chart.canvas import FootprintCanvas
from views.footprint_chart.settings_dialog import FootprintSettingsDialog

# (label shown in the dropdown, vwap_type key on the canvas)
VWAP_TYPES = [
    ("Bar · Globex", "bar_globex"),
    ("Bar · RTH",    "bar_rth"),
    ("Tick · Globex", "tick_globex"),
    ("Tick · RTH",   "tick_rth"),
]


def _sep() -> QWidget:
    w = QWidget()
    w.setFixedWidth(1)
    w.setStyleSheet(f"background-color: {PALETTE['BORDER']};")
    return w


def _tool_icon(kind: str) -> QIcon:
    """Crisp little drawn icons for the drawing-tool buttons."""
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


class FootprintWindow(QMainWindow):
    def __init__(self, config: FootprintConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(
            f"Footprint  ·  {config.asset}  ·  {config.dataset}  ·  {config.date}"
        )
        self.showMaximized()

        self.canvas = FootprintCanvas()
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

    # ------------------------------------------------------------------
    def set_date(self, date: str) -> None:
        """Reload this chart for a new anchor date (keeps its own days-back)."""
        self.config.date = date
        self.setWindowTitle(
            f"Footprint  ·  {self.config.asset}  ·  {self.config.dataset}  ·  {date}")
        self._reload_chart_data()

    def _reload_chart_data(self) -> None:
        config = self.config
        candles = load_candles(config)
        self.canvas.set_data(
            candles,
            tick_size_for(config.asset),
            focus_last_session=config.tf_unit in ("Minutes", "Hours"),
        )
        if candles is not None and config.has_indicators():
            self.canvas.set_indicators(load_indicators(config, candles.times))
        else:
            self.canvas.set_indicators(None)
        self._reload_big_trades()

    def _reload_big_trades(self) -> None:
        if self.config.has_big_trades():
            self.canvas.set_big_trades(
                load_big_trades(self.config, self.canvas.bt_settings.days_back))
        else:
            self.canvas.set_big_trades(None)

    def _toggle_composite(self, checked: bool) -> None:
        if checked:
            self._load_composite()
        else:
            self.canvas.clear_composite()

    def _load_composite(self) -> None:
        vp = self.canvas.vp_settings
        levels, days = load_composite_volume(self.config, vp.composite_days, vp.composite_end)
        self.canvas.set_composite(levels, days)

    def _reload_composite(self) -> None:
        """Re-run the composite if it's currently shown (settings changed)."""
        if self.canvas.composite_on:
            self._load_composite()

    # ------------------------------------------------------------------
    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {PALETTE['BG_PANEL']};")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        # footprint layer toggles
        self.btn_footprint = self._toggle("Footprint", lambda: self.canvas.toggle_layer("footprint"))
        self.btn_volume = self._toggle("Footprint Volume", lambda: self.canvas.toggle_layer("volume"))
        self.btn_passive = self._toggle("Passive", lambda: self.canvas.toggle_layer("passive"))
        row.addWidget(self.btn_footprint)
        row.addWidget(self.btn_volume)
        row.addWidget(self.btn_passive)

        row.addWidget(_sep())

        # indicators + big trades
        has_ind = self.config.has_indicators()
        has_bt = self.config.has_big_trades()

        self.btn_vwap = self._toggle("VWAP", lambda: self.canvas.toggle_layer("vwap"))
        self.vwap_type_combo = QComboBox()
        for label, key in VWAP_TYPES:
            self.vwap_type_combo.addItem(label, key)
        self.vwap_type_combo.setFixedWidth(120)
        self.vwap_type_combo.currentIndexChanged.connect(
            lambda i: self.canvas.set_vwap_type(self.vwap_type_combo.itemData(i)))
        self.btn_cvd = self._toggle("CVD", lambda: self.canvas.toggle_layer("cvd"))
        self.btn_big_trades = self._toggle("Big Trades", lambda: self.canvas.toggle_layer("big_trades"))

        self.btn_vwap.setEnabled(has_ind)
        self.vwap_type_combo.setEnabled(has_ind)
        self.btn_cvd.setEnabled(has_ind)
        self.btn_big_trades.setEnabled(has_bt)
        if not has_ind:
            self.btn_vwap.setToolTip("No indicators dataset selected")
            self.btn_cvd.setToolTip("No indicators dataset selected")
        if not has_bt:
            self.btn_big_trades.setToolTip("No big-trades dataset selected")

        row.addWidget(self.btn_vwap)
        row.addWidget(self.vwap_type_combo)
        row.addWidget(self.btn_cvd)
        row.addWidget(self.btn_big_trades)

        row.addWidget(_sep())

        # volume profile dropdown (manual / ETH / RTH / composite)
        self.btn_vp = QPushButton("Volume Profile  ▾")
        self.btn_vp.setCheckable(True)
        self.btn_vp.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0px; }")
        vp_menu = QMenu(self.btn_vp)
        vp_menu.addAction("Volume profile (draw)", lambda: self.canvas.set_draw_mode("vp"))
        vp_menu.addAction("ETH volume profile", lambda: self.canvas.add_session_profiles("eth"))
        vp_menu.addAction("RTH volume profile", lambda: self.canvas.add_session_profiles("rth"))
        vp_menu.addSeparator()
        self.act_composite = vp_menu.addAction("Composite volume profile")
        self.act_composite.setCheckable(True)
        self.act_composite.triggered.connect(self._toggle_composite)
        self.btn_vp.setMenu(vp_menu)
        row.addWidget(self.btn_vp)

        row.addWidget(_sep())

        # drawing tools (compact icon buttons)
        self.btn_hline = self._icon("hline", "Horizontal line", lambda: self.canvas.set_draw_mode("hline"))
        self.btn_ray = self._icon("ray", "Ray — extends right", lambda: self.canvas.set_draw_mode("ray"))
        self.btn_vline = self._icon("vline", "Vertical line", lambda: self.canvas.set_draw_mode("vline"))
        self.btn_box = self._icon("box", "Box", lambda: self.canvas.set_draw_mode("box"))
        self.btn_long = self._icon("long", "Long position", lambda: self.canvas.set_draw_mode("long"))
        self.btn_short = self._icon("short", "Short position", lambda: self.canvas.set_draw_mode("short"))
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

        gear = QPushButton("\u2699")
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
            dlg = FootprintSettingsDialog(
                self.canvas.fp_settings, self.canvas.volume_settings,
                self.canvas.passive_settings, self.canvas.bt_settings,
                self.canvas.general_settings, self.canvas.vp_settings,
                on_change=self.canvas.update,
                on_bt_reload=self._reload_big_trades,
                on_composite_reload=self._reload_composite,
                parent=self)
            self._settings_dlg = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    # ------------------------------------------------------------------
    def _sync_buttons(self) -> None:
        """Reflect canvas state on the toolbar (modes auto-reset after use)."""
        self.btn_footprint.setChecked(self.canvas.layers["footprint"])
        self.btn_volume.setChecked(self.canvas.layers["volume"])
        self.btn_passive.setChecked(self.canvas.layers["passive"])
        self.btn_vwap.setChecked(self.canvas.layers["vwap"])
        self.btn_cvd.setChecked(self.canvas.layers["cvd"])
        self.btn_big_trades.setChecked(self.canvas.layers["big_trades"])
        mode = self.canvas.draw_mode
        self.btn_vp.setChecked(mode == "vp" or self.canvas.composite_on)
        self.act_composite.setChecked(self.canvas.composite_on)
        self.btn_hline.setChecked(mode == "hline")
        self.btn_ray.setChecked(mode == "ray")
        self.btn_vline.setChecked(mode == "vline")
        self.btn_box.setChecked(mode == "box")
        self.btn_long.setChecked(mode == "long")
        self.btn_short.setChecked(mode == "short")
        self.btn_delete.setChecked(mode == "delete")
