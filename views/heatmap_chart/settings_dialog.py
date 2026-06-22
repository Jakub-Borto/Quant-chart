"""Heatmap chart settings dialog."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QListWidget, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from core.styles import PALETTE


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {PALETTE['TEXT_DIM']}; background: transparent; font-size: 8pt;")
    return lbl


class HeatmapSettingsDialog(QDialog):
    def __init__(self, settings, on_change, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.on_change = on_change
        self.setWindowTitle("Chart Settings")
        self.setMinimumSize(520, 360)

        self.categories = QListWidget()
        self.categories.addItem("Heatmap")
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
        self.stack.addWidget(self._heatmap_page())
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

    # ── page ──────────────────────────────────────────────────────────
    def _heatmap_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Heatmap Coloring")
        title.setStyleSheet(f"color: {PALETTE['TEXT_PRI']}; font-size: 11pt; font-weight: 600;")
        layout.addWidget(title)
        layout.addWidget(_hint(
            "Resting liquidity is colored dark → teal → green → yellow → orange → red as "
            "quantity grows. Contrast brightens the whole range; high-level contrast pushes "
            "only the largest orders toward the hot end."))
        layout.addSpacing(6)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        s = self.settings

        self.sp_contrast = QDoubleSpinBox()
        self.sp_contrast.setRange(0.2, 5.0)
        self.sp_contrast.setSingleStep(0.1)
        self.sp_contrast.setDecimals(2)
        self.sp_contrast.setFixedWidth(100)
        self.sp_contrast.setValue(s.contrast)
        self.sp_contrast.valueChanged.connect(self._on_contrast)
        form.addRow(self._label("Heatmap contrast"), self.sp_contrast)

        self.sp_high = QDoubleSpinBox()
        self.sp_high.setRange(0.2, 5.0)
        self.sp_high.setSingleStep(0.1)
        self.sp_high.setDecimals(2)
        self.sp_high.setFixedWidth(100)
        self.sp_high.setValue(s.high_contrast)
        self.sp_high.valueChanged.connect(self._on_high)
        form.addRow(self._label("High-level contrast"), self.sp_high)

        self.sp_ref = QDoubleSpinBox()
        self.sp_ref.setRange(0.0, 100000.0)
        self.sp_ref.setSingleStep(10.0)
        self.sp_ref.setDecimals(0)
        self.sp_ref.setFixedWidth(100)
        self.sp_ref.setValue(s.max_ref)
        self.sp_ref.setSpecialValueText("Auto")
        self.sp_ref.valueChanged.connect(self._on_ref)
        form.addRow(self._label("Full-color qty (0=auto)"), self.sp_ref)

        self.sp_crop = QSpinBox()
        self.sp_crop.setRange(8, 2000)
        self.sp_crop.setSingleStep(16)
        self.sp_crop.setFixedWidth(100)
        self.sp_crop.setValue(s.crop_ticks)
        self.sp_crop.valueChanged.connect(self._on_crop)
        form.addRow(self._label("Crop ticks (± touch)"), self.sp_crop)

        self.cb_dom = QCheckBox("Show price-ladder panel (right)")
        self.cb_dom.setChecked(s.show_dom_panel)
        self.cb_dom.toggled.connect(self._on_dom)
        form.addRow("", self.cb_dom)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {PALETTE['TEXT_SEC']}; background: transparent; font-size: 9pt;")
        return lbl

    # ── live callbacks ────────────────────────────────────────────────
    def _apply(self):
        self.settings.save()
        if callable(self.on_change):
            self.on_change()

    def _on_contrast(self, v): self.settings.contrast = float(v); self._apply()
    def _on_high(self, v):     self.settings.high_contrast = float(v); self._apply()
    def _on_ref(self, v):      self.settings.max_ref = float(v); self._apply()
    def _on_crop(self, v):     self.settings.crop_ticks = int(v); self._apply()
    def _on_dom(self, v):      self.settings.show_dom_panel = bool(v); self._apply()
