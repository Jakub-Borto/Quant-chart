"""Order-book heatmap chart window."""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QProgressDialog, QPushButton,
    QVBoxLayout, QWidget,
)

from core.asset_info import tick_size_for
from views.heatmap_chart.heatmap_config import HeatmapConfig
from views.heatmap_chart.heatmap_data import load_heatmap, build_or_load_pyramid
from views.heatmap_chart.canvas import HeatmapCanvas
from views.heatmap_chart.settings_dialog import HeatmapSettingsDialog
from core.styles import PALETTE


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


class HeatmapWindow(QMainWindow):
    def __init__(self, config: HeatmapConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(
            f"Heatmap  ·  {config.asset}  ·  {config.dataset}  ·  {config.date}"
        )
        self.showMaximized()

        self.canvas = HeatmapCanvas()
        data = load_heatmap(config)
        self._tick = tick_size_for(config.asset)
        pyr = self._load_pyramid(data, config, self._tick)
        self.canvas.set_data(data, self._tick, focus_last_session=False)
        self.canvas.set_pyramid(pyr)

        self.canvas.state_changed.connect(self._sync_buttons)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self.canvas, 1)
        self.setCentralWidget(central)

        self._sync_buttons()

    def _load_pyramid(self, data, config, tick):
        """Load/build the aggregation pyramid, showing a progress dialog only
        when an actual build happens (cache hits stay silent)."""
        if data is None or len(data) == 0:
            return None
        holder = {"dlg": None}

        def progress(done, total):
            dlg = holder["dlg"]
            if dlg is None:
                dlg = QProgressDialog("Building heatmap…", "Cancel", 0, 100, self)
                dlg.setWindowTitle("DOM Heatmap")
                dlg.setWindowModality(Qt.WindowModality.WindowModal)
                dlg.setMinimumDuration(0)
                dlg.setAutoClose(False)
                dlg.setAutoReset(False)
                holder["dlg"] = dlg
            dlg.setValue(int(done * 100 / max(1, total)))
            QApplication.processEvents()

        def cancel():
            return holder["dlg"] is not None and holder["dlg"].wasCanceled()

        s = self.canvas.settings
        try:
            pyr = build_or_load_pyramid(
                data, config, tick,
                crop_ticks=s.crop_ticks,
                rth_lo=s.rth_start_min(), rth_hi=s.rth_end_min(),
                progress_cb=progress, cancel_cb=cancel)
        finally:
            if holder["dlg"] is not None:
                holder["dlg"].close()
        return pyr

    def _rebuild_pyramid(self) -> None:
        """Rebuild the pyramid after an RTH-window or crop change (settings)."""
        pyr = self._load_pyramid(self.canvas.data, self.config, self._tick)
        self.canvas.set_pyramid(pyr)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {PALETTE['BG_PANEL']};")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        self.btn_lines = self._toggle("OHLC", lambda: self.canvas.toggle_layer("lines"))
        self.btn_dom   = self._toggle("Ladder",  lambda: self.canvas.toggle_layer("dom"))
        row.addWidget(self.btn_lines)
        row.addWidget(self.btn_dom)

        row.addWidget(_sep())

        self.btn_hline  = self._icon("hline", "Horizontal line",     lambda: self.canvas.set_draw_mode("hline"))
        self.btn_ray    = self._icon("ray",   "Ray — extends right", lambda: self.canvas.set_draw_mode("ray"))
        self.btn_vline  = self._icon("vline", "Vertical line",       lambda: self.canvas.set_draw_mode("vline"))
        self.btn_box    = self._icon("box",   "Box",                 lambda: self.canvas.set_draw_mode("box"))
        self.btn_long   = self._icon("long",  "Long position",       lambda: self.canvas.set_draw_mode("long"))
        self.btn_short  = self._icon("short", "Short position",      lambda: self.canvas.set_draw_mode("short"))
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
            dlg = HeatmapSettingsDialog(
                self.canvas.settings,
                on_change=self.canvas.apply_settings,
                on_rebuild=self._rebuild_pyramid,
                parent=self,
            )
            self._settings_dlg = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _sync_buttons(self) -> None:
        self.btn_lines.setChecked(self.canvas.layers["lines"])
        self.btn_dom.setChecked(self.canvas.layers["dom"])
        mode = self.canvas.draw_mode
        self.btn_hline.setChecked(mode == "hline")
        self.btn_ray.setChecked(mode == "ray")
        self.btn_vline.setChecked(mode == "vline")
        self.btn_box.setChecked(mode == "box")
        self.btn_long.setChecked(mode == "long")
        self.btn_short.setChecked(mode == "short")
        self.btn_delete.setChecked(mode == "delete")
