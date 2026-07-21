"""Options exposure chart window: toolbar + canvas + time-slider bar."""
import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QMainWindow, QProgressDialog,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from core.styles import PALETTE
from views.options_chart.canvas import OptionsCanvas
from views.options_chart.options_compute import (
    EXPIRY_BUCKETS, ExposureParams, compute_exposure,
)
from views.options_chart.options_config import OptionsConfig
from views.options_chart.options_data import load_options_day
from views.options_chart.options_settings import OptionsSettings
from views.options_chart.settings_dialog import OptionsSettingsDialog

GREEKS = [("Delta", "delta"), ("Gamma", "gamma"), ("Vanna", "vanna"), ("Charm", "charm")]
OI_SRCS = [("Open Interest", "open_interest"), ("Est. OI", "est_oi"),
           ("Dealer Flow", "dealer_flow")]
SIGNS = [("Calls long / Puts short", "calls_long"),
         ("Puts long / Calls short", "puts_long"),
         ("All long (gross)", "all_long")]
UNITS = [("$ / 1% move", "pct"), ("$ / 1 point", "point"), ("Contracts", "contracts")]


def _sep() -> QWidget:
    w = QWidget()
    w.setFixedWidth(1)
    w.setStyleSheet(f"background-color: {PALETTE['BORDER']};")
    return w


class OptionsWindow(QMainWindow):
    def __init__(self, config: OptionsConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self._set_title()
        self.showMaximized()

        self.settings = OptionsSettings.load()
        self.canvas = OptionsCanvas(self.settings)
        self.day = None
        self.iv_cache: dict = {}
        self.result_cache: dict = {}

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self._build_slider_bar())
        self.setCentralWidget(central)

        self._reload_chart_data()

    # ── public API (menu Live Date Control) ───────────────────────────
    def set_date(self, date: str) -> None:
        self.config.date = date
        self._set_title()
        self._reload_chart_data()

    # ── data loading ──────────────────────────────────────────────────
    def _set_title(self) -> None:
        c = self.config
        self.setWindowTitle(f"Options  ·  {c.asset}  ·  {c.dataset}  ·  {c.date}")

    def _reload_chart_data(self) -> None:
        prev_tod = None
        if self.day is not None and self.day.n_t:
            t = self.day.times[self.slider.value()]
            prev_tod = t.hour * 60 + t.minute
        self._stop_playback()

        holder = {"dlg": None}

        def progress(done: int, total: int) -> None:
            dlg = holder["dlg"]
            if dlg is None:
                dlg = QProgressDialog("Loading options data…", "Cancel", 0, 100, self)
                dlg.setWindowModality(Qt.WindowModality.WindowModal)
                dlg.setMinimumDuration(0)
                dlg.setAutoClose(False)
                dlg.setAutoReset(False)
                holder["dlg"] = dlg
            dlg.setValue(int(done * 100 / max(1, total)))
            QApplication.processEvents()

        def cancelled() -> bool:
            dlg = holder["dlg"]
            return bool(dlg is not None and dlg.wasCanceled())

        try:
            day = load_options_day(self.config, self.settings,
                                   progress_cb=progress, cancel_cb=cancelled)
        finally:
            if holder["dlg"] is not None:
                holder["dlg"].close()

        self.day = day
        self.iv_cache.clear()
        self.result_cache.clear()
        self.canvas.set_result(None)
        self.canvas.set_day(day)

        if day is None or day.n_t == 0:
            self.canvas.set_message("No options / futures data for this date")
            self.slider.setEnabled(False)
            self.btn_play.setEnabled(False)
            self.time_label.setText("--:--")
            return

        self.slider.setEnabled(True)
        self.btn_play.setEnabled(True)
        self.slider.blockSignals(True)
        self.slider.setRange(0, day.n_t - 1)
        idx = 0
        if prev_tod is not None:
            tods = np.array([t.hour * 60 + t.minute for t in day.times])
            d = np.abs(tods - prev_tod)
            idx = int(np.argmin(np.minimum(d, 1440 - d)))
        self.slider.setValue(idx)
        self.slider.blockSignals(False)
        self._on_time_changed(idx)

    # ── exposure recompute ────────────────────────────────────────────
    def _params(self) -> ExposureParams:
        src = self.src_combo.currentData()
        # dealer_flow ignores the sign assumption (own exposure algorithm);
        # pin the field so the cache key doesn't fragment
        sign = "calls_long" if src == "dealer_flow" else self.sign_combo.currentData()
        return ExposureParams(
            greek=self.greek_combo.currentData(),
            oi_source=src,
            sign_mode=sign,
            units=self.units_combo.currentData(),
            bucket=self.expiry_combo.currentData(),
            r=self.settings.r(),
        )

    def _on_time_changed(self, i: int) -> None:
        if self.day is None:
            return
        res = compute_exposure(self.day, i, self._params(),
                               self.iv_cache, self.result_cache)
        if res is None:
            self.canvas.set_message("No underlying price at this time")
        self.canvas.set_result(res)
        self.time_label.setText(self.day.times[i].strftime("%a %H:%M"))

    def _on_param_changed(self) -> None:
        self.sign_combo.setEnabled(self.src_combo.currentData() != "dealer_flow")
        self.result_cache.clear()
        self.canvas.request_rescale()
        if self.day is not None:
            self._on_time_changed(self.slider.value())

    def _on_rate_changed(self) -> None:
        self.iv_cache.clear()
        self._on_param_changed()

    # ── playback ──────────────────────────────────────────────────────
    def _toggle_play(self) -> None:
        if self.btn_play.isChecked():
            self.btn_play.setText("⏸")
            self.timer.start(self.settings.playback_ms)
        else:
            self._stop_playback()

    def _stop_playback(self) -> None:
        self.timer.stop()
        self.btn_play.setChecked(False)
        self.btn_play.setText("▶")

    def _tick(self) -> None:
        if self.day is None or self.day.n_t == 0:
            self._stop_playback()
            return
        self.slider.setValue((self.slider.value() + 1) % self.day.n_t)

    # ── UI construction ───────────────────────────────────────────────
    def _combo(self, items, width: int) -> QComboBox:
        combo = QComboBox()
        for label, key in items:
            combo.addItem(label, key)
        combo.setFixedWidth(width)
        combo.currentIndexChanged.connect(lambda _i: self._on_param_changed())
        return combo

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {PALETTE['BG_PANEL']};")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        self.greek_combo = self._combo(GREEKS, 90)
        self.src_combo = self._combo(OI_SRCS, 120)
        self.sign_combo = self._combo(SIGNS, 170)
        self.sign_combo.setToolTip(
            "Dealer direction assumed for OI / Est. OI positions. Not used with "
            "Dealer Flow — that source carries its own signs (fallback contracts "
            "use the fixed calls-long / puts-short convention).")
        self.units_combo = self._combo(UNITS, 110)
        self.expiry_combo = self._combo([(b, b) for b in EXPIRY_BUCKETS], 110)

        row.addWidget(self.greek_combo)
        row.addWidget(self.src_combo)
        row.addWidget(self.sign_combo)
        row.addWidget(self.units_combo)
        row.addWidget(self.expiry_combo)
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

    def _build_slider_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {PALETTE['BG_PANEL']};")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)

        self.btn_play = QPushButton("▶")
        self.btn_play.setCheckable(True)
        self.btn_play.setFixedWidth(36)
        self.btn_play.setToolTip("Autoplay through the session")
        self.btn_play.clicked.connect(self._toggle_play)
        row.addWidget(self.btn_play)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setTracking(True)
        self.slider.valueChanged.connect(self._on_time_changed)
        row.addWidget(self.slider, 1)

        self.time_label = QLabel("--:--")
        self.time_label.setFixedWidth(90)
        self.time_label.setStyleSheet(
            f"color: {PALETTE['TEXT_SEC']}; font-family: monospace;")
        row.addWidget(self.time_label)
        return bar

    def _open_settings(self) -> None:
        dlg = getattr(self, "_settings_dlg", None)
        if dlg is None:
            dlg = OptionsSettingsDialog(
                self.settings,
                on_recompute=self._on_rate_changed,
                on_reload=self._reload_chart_data,
                on_repaint=self.canvas.update,
                on_speed=lambda: self.timer.setInterval(self.settings.playback_ms),
                parent=self,
            )
            self._settings_dlg = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def closeEvent(self, event) -> None:
        self._stop_playback()
        super().closeEvent(event)
