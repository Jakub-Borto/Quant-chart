"""Interval map window: toolbar + canvas (no slider — the whole day is shown)."""
import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QMainWindow, QProgressDialog,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from core.styles import PALETTE
from views.interval_map.canvas import IntervalMapCanvas
from views.interval_map.interval_compute import (
    INTERVALS, STRIKE_STEPS, build_interval_grid,
)
from views.options_chart.options_compute import (
    EXPIRY_BUCKETS, GREEKS, OI_SRCS, SIGNS, TOTAL_MODES, UNITS, ExposureParams,
)
from views.options_chart.options_config import OptionsConfig
from views.options_chart.options_data import load_options_day
from views.options_chart.options_settings import OptionsSettings
from views.options_chart.settings_dialog import OptionsSettingsDialog


def _sep() -> QWidget:
    w = QWidget()
    w.setFixedWidth(1)
    w.setStyleSheet(f"background-color: {PALETTE['BORDER']};")
    return w


class IntervalMapWindow(QMainWindow):
    def __init__(self, config: OptionsConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self._set_title()

        self.settings = OptionsSettings.load()
        self.canvas = IntervalMapCanvas()
        self.day = None
        self.iv_cache: dict = {}

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self.canvas, 1)
        self.setCentralWidget(central)
        # maximize once the layout exists, so the canvas is sized before loading
        self.showMaximized()

        self._reload_chart_data()

    # ── public API (menu Live Date Control) ───────────────────────────
    def set_date(self, date: str) -> None:
        self.config.date = date
        self._set_title()
        self._reload_chart_data()

    # ── data loading / grid rebuild ───────────────────────────────────
    def _set_title(self) -> None:
        c = self.config
        self.setWindowTitle(f"Interval Map  ·  {c.asset}  ·  {c.dataset}  ·  {c.date}")

    def _reload_chart_data(self) -> None:
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
        self.canvas.set_grid(None)
        if day is None or day.n_t == 0:
            self.canvas.set_message("No options / futures data for this date")
            return
        self._rebuild_grid()

    def _params(self) -> ExposureParams:
        src = self.src_combo.currentData()
        greek = self.greek_combo.currentData()
        # dealer_flow and the raw-OI modes ignore the sign assumption; raw-OI modes
        # are contracts-only — pin the fields so the cache key doesn't fragment
        sign = ("calls_long" if src == "dealer_flow" or greek in TOTAL_MODES
                else self.sign_combo.currentData())
        units = "contracts" if greek in TOTAL_MODES else self.units_combo.currentData()
        return ExposureParams(
            greek=greek,
            oi_source=src,
            sign_mode=sign,
            units=units,
            bucket=self.expiry_combo.currentData(),
            r=self.settings.r(),
        )

    def _rebuild_grid(self) -> None:
        if self.day is None or self.day.n_t == 0:
            self.canvas.set_grid(None)
            self.canvas.set_message("No options / futures data for this date")
            return

        # deferred progress dialog: cold builds (>0.3 s) show it, warm stay silent
        holder = {"dlg": None}
        t0 = time.monotonic()

        def progress(done: int, total: int) -> None:
            dlg = holder["dlg"]
            if dlg is None:
                if time.monotonic() - t0 < 0.3:
                    return
                dlg = QProgressDialog("Computing exposure grid…", "Cancel", 0, 100, self)
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
            grid = build_interval_grid(
                self.day, self._params(),
                interval_min=self.interval_combo.currentData(),
                strike_step=self.step_combo.currentData(),
                iv_cache=self.iv_cache,
                progress_cb=progress, cancel_cb=cancelled,
            )
        finally:
            if holder["dlg"] is not None:
                holder["dlg"].close()

        if grid is None:
            self.canvas.set_grid(None)
            self.canvas.set_message(
                "Computation cancelled" if cancelled()
                else "No nonzero exposure for these settings")
            return
        self.canvas.set_grid(grid)

    def _on_param_changed(self) -> None:
        total = self.greek_combo.currentData() in TOTAL_MODES
        self.sign_combo.setEnabled(
            not total and self.src_combo.currentData() != "dealer_flow")
        self.units_combo.setEnabled(not total)
        self._rebuild_grid()

    def _on_rate_changed(self) -> None:
        self.iv_cache.clear()
        self._rebuild_grid()

    def _on_dot_scale(self, v: int) -> None:
        self.canvas.set_dot_scale(10 ** ((v - 80) / 40))

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

        # oi_split is a two-sided bar display — not representable as one dot per cell
        self.greek_combo = self._combo([g for g in GREEKS if g[1] != "oi_split"], 90)
        self.src_combo = self._combo(OI_SRCS, 120)
        self.sign_combo = self._combo(SIGNS, 170)
        self.sign_combo.setToolTip(
            "Dealer direction assumed for OI / Est. OI positions. Not used with "
            "Dealer Flow — that source carries its own signs (fallback contracts "
            "use the fixed calls-long / puts-short convention).")
        self.units_combo = self._combo(UNITS, 110)
        self.expiry_combo = self._combo([(b, b) for b in EXPIRY_BUCKETS], 110)

        self.interval_combo = self._combo(INTERVALS, 80)
        self.interval_combo.blockSignals(True)
        self.interval_combo.setCurrentIndex(1)      # 10 min default
        self.interval_combo.blockSignals(False)
        self.step_combo = self._combo(STRIKE_STEPS, 70)
        self.step_combo.setToolTip("Show only strikes divisible by this step")

        for w in (self.greek_combo, self.src_combo, self.sign_combo,
                  self.units_combo, self.expiry_combo):
            row.addWidget(w)
        row.addWidget(_sep())
        row.addWidget(self.interval_combo)
        row.addWidget(self.step_combo)
        row.addWidget(_sep())

        # dot-max slider: log scale, 80 = day max (1.0x), left = lower reference
        # (small dots grow and saturate), right = higher reference (all shrink)
        self.dot_slider = QSlider(Qt.Orientation.Horizontal)
        self.dot_slider.setRange(0, 100)
        self.dot_slider.setValue(80)
        self.dot_slider.setFixedWidth(120)
        self.dot_slider.setToolTip(
            "Dot max — the exposure at which a dot reaches full size "
            "(left: enlarge small dots, right: shrink everything)")
        self.dot_slider.valueChanged.connect(self._on_dot_scale)
        row.addWidget(self.dot_slider)
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

    def _open_settings(self) -> None:
        dlg = getattr(self, "_settings_dlg", None)
        if dlg is None:
            dlg = OptionsSettingsDialog(
                self.settings,
                on_recompute=self._on_rate_changed,
                on_reload=self._reload_chart_data,
                on_repaint=self.canvas.update,
                on_speed=lambda: None,
                parent=self,
            )
            self._settings_dlg = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
