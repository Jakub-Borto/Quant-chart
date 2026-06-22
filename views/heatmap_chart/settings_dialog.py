"""Heatmap chart settings dialog.

Three categories: General (RTH window + grid/ladder), RTH heatmap colors,
ETH heatmap colors. Color edits repaint live; the RTH window and crop ticks
affect the precomputed pyramid, so they trigger a rebuild via on_rebuild.
"""
from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QListWidget, QPushButton, QSpinBox, QStackedWidget, QTimeEdit,
    QVBoxLayout, QWidget,
)

from core.styles import PALETTE


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {PALETTE['TEXT_DIM']}; background: transparent; font-size: 8pt;")
    return lbl


def _to_qtime(value: str, default: QTime) -> QTime:
    t = QTime.fromString(str(value), "HH:mm")
    return t if t.isValid() else default


class HeatmapSettingsDialog(QDialog):
    def __init__(self, settings, on_change, on_rebuild=None, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.on_change = on_change
        self.on_rebuild = on_rebuild
        self.setWindowTitle("Chart Settings")
        self.setMinimumSize(560, 380)

        self.categories = QListWidget()
        for name in ("General", "RTH heatmap", "ETH heatmap"):
            self.categories.addItem(name)
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
        self.stack.addWidget(self._color_page(rth=True))
        self.stack.addWidget(self._color_page(rth=False))
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

    # ── pages ─────────────────────────────────────────────────────────
    def _general_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._title("General"))
        layout.addWidget(_hint(
            "The RTH window splits the day into the regular-hours session and ETH "
            "(overnight); each gets its own color scale. Crop ticks sets how far "
            "above/below the price the book is drawn. Changing the RTH window or crop "
            "rebuilds the heatmap cache once."))
        layout.addSpacing(6)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        s = self.settings

        self.t_rth_start = QTimeEdit(_to_qtime(s.rth_start, QTime(9, 30)))
        self.t_rth_start.setDisplayFormat("HH:mm")
        self.t_rth_start.setFixedWidth(100)
        self.t_rth_start.editingFinished.connect(self._on_rth_start)
        form.addRow(self._label("RTH start (incl.)"), self.t_rth_start)

        self.t_rth_end = QTimeEdit(_to_qtime(s.rth_end, QTime(16, 0)))
        self.t_rth_end.setDisplayFormat("HH:mm")
        self.t_rth_end.setFixedWidth(100)
        self.t_rth_end.editingFinished.connect(self._on_rth_end)
        form.addRow(self._label("RTH end (excl.)"), self.t_rth_end)

        self.sp_crop = QSpinBox()
        self.sp_crop.setRange(8, 2000)
        self.sp_crop.setSingleStep(16)
        self.sp_crop.setFixedWidth(100)
        self.sp_crop.setValue(s.crop_ticks)
        self.sp_crop.editingFinished.connect(self._on_crop)
        form.addRow(self._label("Crop ticks (± touch)"), self.sp_crop)

        self.cb_dom = QCheckBox("Show price-ladder panel (right)")
        self.cb_dom.setChecked(s.show_dom_panel)
        self.cb_dom.toggled.connect(self._on_dom)
        form.addRow("", self.cb_dom)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _color_page(self, rth: bool) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._title("RTH heatmap" if rth else "ETH heatmap"))
        layout.addWidget(_hint(
            "Resting liquidity is colored dark → teal → green → yellow → orange → red as "
            "quantity grows. Contrast brightens the whole range; high-level contrast pushes "
            "only the largest orders to the hot end; full-color qty is the size mapped to red "
            "(0 = auto). " + ("Day session." if rth else "Overnight session.")))
        layout.addSpacing(6)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        s = self.settings
        contrast = s.rth_contrast if rth else s.eth_contrast
        high = s.rth_high_contrast if rth else s.eth_high_contrast
        ref = s.rth_max_ref if rth else s.eth_max_ref

        sp_contrast = self._ratio_spin(contrast)
        sp_contrast.valueChanged.connect(lambda v: self._set_color(rth, "contrast", v))
        form.addRow(self._label("Heatmap contrast"), sp_contrast)

        sp_high = self._ratio_spin(high)
        sp_high.valueChanged.connect(lambda v: self._set_color(rth, "high", v))
        form.addRow(self._label("High-level contrast"), sp_high)

        sp_ref = QDoubleSpinBox()
        sp_ref.setRange(0.0, 100000.0)
        sp_ref.setSingleStep(10.0)
        sp_ref.setDecimals(0)
        sp_ref.setFixedWidth(100)
        sp_ref.setValue(ref)
        sp_ref.setSpecialValueText("Auto")
        sp_ref.valueChanged.connect(lambda v: self._set_color(rth, "ref", v))
        form.addRow(self._label("Full-color qty (0=auto)"), sp_ref)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _ratio_spin(self, value) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(0.2, 5.0)
        sp.setSingleStep(0.1)
        sp.setDecimals(2)
        sp.setFixedWidth(100)
        sp.setValue(value)
        return sp

    def _title(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {PALETTE['TEXT_PRI']}; font-size: 11pt; font-weight: 600;")
        return lbl

    def _label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {PALETTE['TEXT_SEC']}; background: transparent; font-size: 9pt;")
        return lbl

    # ── callbacks ─────────────────────────────────────────────────────
    def _apply(self):
        self.settings.save()
        if callable(self.on_change):
            self.on_change()

    def _rebuild(self):
        self.settings.save()
        if callable(self.on_rebuild):
            self.on_rebuild()
        elif callable(self.on_change):
            self.on_change()

    def _set_color(self, rth: bool, which: str, v):
        s = self.settings
        if which == "contrast":
            if rth: s.rth_contrast = float(v)
            else:   s.eth_contrast = float(v)
        elif which == "high":
            if rth: s.rth_high_contrast = float(v)
            else:   s.eth_high_contrast = float(v)
        else:
            if rth: s.rth_max_ref = float(v)
            else:   s.eth_max_ref = float(v)
        self._apply()

    def _on_rth_start(self):
        v = self.t_rth_start.time().toString("HH:mm")
        if v != self.settings.rth_start:
            self.settings.rth_start = v
            self._rebuild()

    def _on_rth_end(self):
        v = self.t_rth_end.time().toString("HH:mm")
        if v != self.settings.rth_end:
            self.settings.rth_end = v
            self._rebuild()

    def _on_crop(self):
        v = int(self.sp_crop.value())
        if v != self.settings.crop_ticks:
            self.settings.crop_ticks = v
            self._rebuild()

    def _on_dom(self, v):
        self.settings.show_dom_panel = bool(v)
        self._apply()
