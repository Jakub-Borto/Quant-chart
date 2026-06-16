"""Footprint chart settings dialog.

Categorised preferences: a category list on the left, the matching settings
page on the right. Changes apply live and persist via QSettings.

Categories:
  - Footprint Chart (Orders)  -> per-level buy/sell imbalance coloring
  - Footprint Volume          -> per-candle volume-bar imbalance coloring
  - Passive Orders            -> resting bid/ask liquidity coloring
"""
from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QListWidget, QPushButton, QSlider, QSpinBox, QStackedWidget, QTimeEdit,
    QVBoxLayout, QWidget,
)


def _to_qtime(value: str) -> QTime:
    t = QTime.fromString(str(value), "HH:mm")
    return t if t.isValid() else QTime(9, 30)

from core.styles import PALETTE


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {PALETTE['TEXT_DIM']}; background: transparent; font-size: 8pt;")
    return lbl


class FootprintSettingsDialog(QDialog):
    def __init__(self, order_settings, volume_settings, passive_settings,
                 big_trade_settings, general_settings, vp_settings,
                 on_change, on_bt_reload=None, on_composite_reload=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.order_settings = order_settings
        self.volume_settings = volume_settings
        self.passive_settings = passive_settings
        self.big_trade_settings = big_trade_settings
        self.general_settings = general_settings
        self.vp_settings = vp_settings
        self.on_change = on_change
        self.on_bt_reload = on_bt_reload
        self.on_composite_reload = on_composite_reload
        self.setWindowTitle("Chart Settings")
        self.setMinimumSize(600, 460)

        self.categories = QListWidget()
        self.categories.addItem("General")
        self.categories.addItem("Footprint Chart (Orders)")
        self.categories.addItem("Footprint Volume")
        self.categories.addItem("Passive Orders")
        self.categories.addItem("Volume Profile")
        self.categories.addItem("Big Trades")
        self.categories.setCurrentRow(0)
        self.categories.setFixedWidth(210)
        self.categories.setStyleSheet(f"""
            QListWidget {{
                background-color: {PALETTE['BG_INPUT']};
                border: 1px solid {PALETTE['BORDER']};
                border-radius: 4px;
                padding: 4px;
                outline: none;
            }}
            QListWidget::item {{ padding: 8px 8px; border-radius: 4px; }}
            QListWidget::item:selected {{
                background-color: {PALETTE['BG_PRESS']};
                color: {PALETTE['ACCENT_HOV']};
            }}
        """)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._general_page())
        self.stack.addWidget(self._orders_page())
        self.stack.addWidget(self._volume_page())
        self.stack.addWidget(self._passive_page())
        self.stack.addWidget(self._vp_page())
        self.stack.addWidget(self._big_trades_page())
        self.categories.currentRowChanged.connect(self.stack.setCurrentIndex)

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(self.categories)
        top.addWidget(self.stack, 1)

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addLayout(top, 1)
        root.addLayout(bottom)

    # ── pages ──────────────────────────────────────────────────────────
    def _orders_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._title("Imbalance Coloring"))
        layout.addWidget(_hint(
            "Each price level's cell is light gray when balanced and tints toward "
            "green (buy-dominant) or purple (sell-dominant). Ratio = larger side / "
            "smaller side at that level."))
        layout.addSpacing(6)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        o = self.order_settings

        self.o_start = self._ratio_spin(o.gradient_start_ratio, 0.1, 50.0)
        self.o_start.valueChanged.connect(self._on_o_start)
        form.addRow(self._label("Tint starts at ratio"), self.o_start)

        self.o_full = self._ratio_spin(o.gradient_full_ratio, 0.1, 100.0)
        self.o_full.valueChanged.connect(self._on_o_full)
        form.addRow(self._label("Full color at ratio"), self.o_full)

        self.o_highlight = self._ratio_spin(o.highlight_ratio, 1.0, 100.0)
        self.o_highlight.valueChanged.connect(self._on_o_highlight)
        form.addRow(self._label("Highlight border ratio"), self.o_highlight)

        self.o_show = QCheckBox("Show highlight border")
        self.o_show.setChecked(o.show_highlight)
        self.o_show.toggled.connect(self._on_o_show)
        form.addRow("", self.o_show)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _volume_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._title("Volume Bar Coloring"))
        layout.addWidget(_hint(
            "Each candle's volume bars are light gray when balanced and tint toward "
            "green (more buyers) or purple (more sellers). Ratio = larger side / "
            "smaller side at that level. The highest-volume level (POC) stays yellow."))
        layout.addSpacing(6)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        v = self.volume_settings

        self.v_start = self._ratio_spin(v.gradient_start_ratio, 0.1, 50.0)
        self.v_start.valueChanged.connect(self._on_v_start)
        form.addRow(self._label("Tint starts at ratio"), self.v_start)

        self.v_full = self._ratio_spin(v.gradient_full_ratio, 0.1, 100.0)
        self.v_full.valueChanged.connect(self._on_v_full)
        form.addRow(self._label("Full color at ratio"), self.v_full)

        self.v_show_delta = QCheckBox("Show delta")
        self.v_show_delta.setChecked(v.show_delta)
        self.v_show_delta.toggled.connect(self._on_v_show_delta)
        form.addRow("", self.v_show_delta)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _passive_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._title("Resting Liquidity Coloring"))
        layout.addWidget(_hint(
            "Resting size at each level tints the cell from light gray toward purple "
            "(resting asks above the open = resistance) or green (resting bids below "
            "the open = support)."))
        layout.addSpacing(6)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        ps = self.passive_settings

        self.p_full = self._ratio_spin(ps.gradient_full_size, 1.0, 100000.0, step=10, dec=0)
        self.p_full.valueChanged.connect(self._on_p_full)
        form.addRow(self._label("Full color at size"), self.p_full)

        self.p_highlight = self._ratio_spin(ps.highlight_size, 1.0, 100000.0, step=10, dec=0)
        self.p_highlight.valueChanged.connect(self._on_p_highlight)
        form.addRow(self._label("Highlight border size"), self.p_highlight)

        self.p_show = QCheckBox("Show highlight border")
        self.p_show.setChecked(ps.show_highlight)
        self.p_show.toggled.connect(self._on_p_show)
        form.addRow("", self.p_show)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _big_trades_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._title("Big-Trade Bubbles"))
        layout.addWidget(_hint(
            "Each large trade is a bubble: blue for buys, purple for sells. Bubble "
            "radius scales with contract size between the min/max below; trades at or "
            "above 'Max contracts' all draw at the max size. Min-contract filters are "
            "inclusive (>=) and set separately for ETH and RTH."))
        layout.addSpacing(6)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        b = self.big_trade_settings

        self.b_min_px = self._ratio_spin(b.min_bubble_px, 1.0, 200.0, step=1, dec=0)
        self.b_min_px.valueChanged.connect(self._on_b_min_px)
        form.addRow(self._label("Min bubble size (px)"), self.b_min_px)

        self.b_max_px = self._ratio_spin(b.max_bubble_px, 1.0, 200.0, step=1, dec=0)
        self.b_max_px.valueChanged.connect(self._on_b_max_px)
        form.addRow(self._label("Max bubble size (px)"), self.b_max_px)

        self.b_max_c = self._ratio_spin(b.max_contracts, 1.0, 100000.0, step=10, dec=0)
        self.b_max_c.valueChanged.connect(self._on_b_max_c)
        form.addRow(self._label("Max contracts (size cap)"), self.b_max_c)

        self.b_eth = self._ratio_spin(b.eth_min_contracts, 0.0, 100000.0, step=1, dec=0)
        self.b_eth.valueChanged.connect(self._on_b_eth)
        form.addRow(self._label("ETH min contracts (>=)"), self.b_eth)

        self.b_rth = self._ratio_spin(b.rth_min_contracts, 0.0, 100000.0, step=1, dec=0)
        self.b_rth.valueChanged.connect(self._on_b_rth)
        form.addRow(self._label("RTH min contracts (>=)"), self.b_rth)

        self.b_days = QSpinBox()
        self.b_days.setRange(1, 365)
        self.b_days.setValue(int(b.days_back))
        self.b_days.setFixedWidth(100)
        self.b_days.valueChanged.connect(self._on_b_days)
        form.addRow(self._label("Days back to load"), self.b_days)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _general_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._title("RTH Session"))
        layout.addWidget(_hint(
            "The regular-trading-hours window, shared across the chart (big-trade "
            "ETH/RTH split, ETH/RTH volume profiles). Start is inclusive, end exclusive."))
        layout.addSpacing(6)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        g = self.general_settings

        self.g_rth_start = QTimeEdit(_to_qtime(g.rth_start))
        self.g_rth_start.setDisplayFormat("HH:mm")
        self.g_rth_start.setFixedWidth(100)
        self.g_rth_start.timeChanged.connect(self._on_g_rth_start)
        form.addRow(self._label("RTH start (incl.)"), self.g_rth_start)

        self.g_rth_end = QTimeEdit(_to_qtime(g.rth_end))
        self.g_rth_end.setDisplayFormat("HH:mm")
        self.g_rth_end.setFixedWidth(100)
        self.g_rth_end.timeChanged.connect(self._on_g_rth_end)
        form.addRow(self._label("RTH end (excl.)"), self.g_rth_end)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _vp_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._title("Volume Profiles"))
        layout.addWidget(_hint(
            "RTH profile spans this many minutes from the RTH start. The composite "
            "profile aggregates total volume over the given number of day-files "
            "(including the current day); on the last day it stops at the end time."))
        layout.addSpacing(6)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        v = self.vp_settings

        self.vp_rth_min = QSpinBox()
        self.vp_rth_min.setRange(1, 1440)
        self.vp_rth_min.setValue(int(v.rth_minutes))
        self.vp_rth_min.setFixedWidth(100)
        self.vp_rth_min.valueChanged.connect(self._on_vp_rth_min)
        form.addRow(self._label("RTH profile minutes"), self.vp_rth_min)

        self.vp_days = QSpinBox()
        self.vp_days.setRange(1, 365)
        self.vp_days.setValue(int(v.composite_days))
        self.vp_days.setFixedWidth(100)
        self.vp_days.valueChanged.connect(self._on_vp_days)
        form.addRow(self._label("Composite days back"), self.vp_days)

        self.vp_end = QTimeEdit(_to_qtime(v.composite_end))
        self.vp_end.setDisplayFormat("HH:mm")
        self.vp_end.setFixedWidth(100)
        self.vp_end.timeChanged.connect(self._on_vp_end)
        form.addRow(self._label("Composite end (excl.)"), self.vp_end)

        form.addRow(self._label("Profile volume width"),
                    self._width_slider(v.vol_width, 20, 1000, self._on_vp_vol_width))
        form.addRow(self._label("Profile delta width"),
                    self._width_slider(v.delta_width, 20, 1800, self._on_vp_delta_width))
        form.addRow(self._label("Composite width"),
                    self._width_slider(v.composite_width, 20, 600, self._on_vp_comp_width))

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _width_slider(self, value, lo, hi, on_val) -> QWidget:
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(int(value))
        s.setFixedWidth(150)
        val = QLabel(str(int(value)))
        val.setFixedWidth(36)
        val.setStyleSheet(f"color: {PALETTE['TEXT_SEC']}; background: transparent; font-size: 9pt;")

        def changed(x):
            val.setText(str(x))
            on_val(x)
        s.valueChanged.connect(changed)
        h.addWidget(s)
        h.addWidget(val)
        h.addStretch(1)
        return box

    # ── helpers ────────────────────────────────────────────────────────
    def _title(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {PALETTE['TEXT_PRI']}; font-size: 11pt; font-weight: 600;")
        return lbl

    def _label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {PALETTE['TEXT_SEC']}; background: transparent; font-size: 9pt;")
        return lbl

    def _ratio_spin(self, value, lo, hi, step=0.5, dec=1):
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setDecimals(dec)
        sp.setValue(value)
        sp.setFixedWidth(100)
        return sp

    def _apply_orders(self):
        self.order_settings.save()
        if callable(self.on_change):
            self.on_change()

    def _apply_volume(self):
        self.volume_settings.save()
        if callable(self.on_change):
            self.on_change()

    def _apply_passive(self):
        self.passive_settings.save()
        if callable(self.on_change):
            self.on_change()

    def _apply_big_trades(self, reload=False):
        self.big_trade_settings.save()
        if reload and callable(self.on_bt_reload):
            self.on_bt_reload()      # reloads data + repaints
        elif callable(self.on_change):
            self.on_change()

    # orders
    def _on_o_start(self, v):     self.order_settings.gradient_start_ratio = v; self._apply_orders()
    def _on_o_full(self, v):      self.order_settings.gradient_full_ratio = v;  self._apply_orders()
    def _on_o_highlight(self, v): self.order_settings.highlight_ratio = v;      self._apply_orders()
    def _on_o_show(self, v):      self.order_settings.show_highlight = v;       self._apply_orders()

    # volume
    def _on_v_start(self, v):     self.volume_settings.gradient_start_ratio = v; self._apply_volume()
    def _on_v_full(self, v):      self.volume_settings.gradient_full_ratio = v;  self._apply_volume()
    def _on_v_show_delta(self, v): self.volume_settings.show_delta = v;          self._apply_volume()

    # passive
    def _on_p_full(self, v):      self.passive_settings.gradient_full_size = v; self._apply_passive()
    def _on_p_highlight(self, v): self.passive_settings.highlight_size = v;     self._apply_passive()
    def _on_p_show(self, v):      self.passive_settings.show_highlight = v;     self._apply_passive()

    # big trades
    def _on_b_min_px(self, v): self.big_trade_settings.min_bubble_px = v;     self._apply_big_trades()
    def _on_b_max_px(self, v): self.big_trade_settings.max_bubble_px = v;     self._apply_big_trades()
    def _on_b_max_c(self, v):  self.big_trade_settings.max_contracts = v;     self._apply_big_trades()
    def _on_b_eth(self, v):    self.big_trade_settings.eth_min_contracts = v; self._apply_big_trades()
    def _on_b_rth(self, v):    self.big_trade_settings.rth_min_contracts = v; self._apply_big_trades()
    def _on_b_days(self, v):   self.big_trade_settings.days_back = int(v);    self._apply_big_trades(reload=True)

    # general (RTH session) — repaint reclassifies big trades live
    def _apply_general(self):
        self.general_settings.save()
        if callable(self.on_change):
            self.on_change()

    def _on_g_rth_start(self, t): self.general_settings.rth_start = t.toString("HH:mm"); self._apply_general()
    def _on_g_rth_end(self, t):   self.general_settings.rth_end = t.toString("HH:mm");   self._apply_general()

    # volume profile
    def _apply_vp(self, reload_composite=False):
        self.vp_settings.save()
        if reload_composite and callable(self.on_composite_reload):
            self.on_composite_reload()
        elif callable(self.on_change):
            self.on_change()

    def _on_vp_rth_min(self, v): self.vp_settings.rth_minutes = int(v);  self._apply_vp()
    def _on_vp_days(self, v):    self.vp_settings.composite_days = int(v); self._apply_vp(reload_composite=True)
    def _on_vp_end(self, t):     self.vp_settings.composite_end = t.toString("HH:mm"); self._apply_vp(reload_composite=True)
    def _on_vp_vol_width(self, v):   self.vp_settings.vol_width = int(v);       self._apply_vp()
    def _on_vp_delta_width(self, v): self.vp_settings.delta_width = int(v);     self._apply_vp()
    def _on_vp_comp_width(self, v):  self.vp_settings.composite_width = int(v); self._apply_vp()
