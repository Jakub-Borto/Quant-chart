"""Options exposure chart settings dialog."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDoubleSpinBox, QFormLayout, QLabel, QPushButton, QSpinBox,
    QVBoxLayout,
)

from core.styles import PALETTE


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {PALETTE['TEXT_DIM']}; background: transparent; font-size: 8pt;")
    return lbl


def _lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {PALETTE['TEXT_SEC']}; background: transparent; font-size: 9pt;")
    return lbl


class OptionsSettingsDialog(QDialog):
    """on_recompute: rate changed (clear caches, recompute current time).
    on_reload: quote lookback changed (data reload required).
    on_repaint: cosmetic change. on_speed: playback interval changed."""

    def __init__(self, settings, on_recompute, on_reload, on_repaint, on_speed,
                 parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.on_recompute = on_recompute
        self.on_reload = on_reload
        self.on_repaint = on_repaint
        self.on_speed = on_speed
        self.setWindowTitle("Options Exposure Settings")
        self.setMinimumWidth(420)

        title = QLabel("General")
        title.setStyleSheet(f"color: {PALETTE['TEXT_PRI']}; font-size: 11pt; font-weight: 600;")

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        s = self.settings

        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0, 20.0)
        self.rate_spin.setSingleStep(0.25)
        self.rate_spin.setSuffix(" %")
        self.rate_spin.setValue(s.risk_free_rate)
        self.rate_spin.valueChanged.connect(self._on_rate)
        form.addRow(_lbl("Risk-free rate"), self.rate_spin)

        self.lookback_spin = QSpinBox()
        self.lookback_spin.setRange(0, 10)
        self.lookback_spin.setValue(s.quote_lookback_files)
        self.lookback_spin.valueChanged.connect(self._on_lookback)
        form.addRow(_lbl("Quote lookback (files)"), self.lookback_spin)

        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(50, 2000)
        self.speed_spin.setSingleStep(50)
        self.speed_spin.setSuffix(" ms")
        self.speed_spin.setValue(s.playback_ms)
        self.speed_spin.valueChanged.connect(self._on_speed)
        form.addRow(_lbl("Playback step"), self.speed_spin)

        self.dim_spin = QDoubleSpinBox()
        self.dim_spin.setRange(0.10, 1.00)
        self.dim_spin.setSingleStep(0.05)
        self.dim_spin.setValue(s.dim_factor)
        self.dim_spin.valueChanged.connect(self._on_dim)
        form.addRow(_lbl("Fallback dim factor"), self.dim_spin)

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(_hint(
            "Rate discounts premiums in the implied-vol solve. Quote lookback is how many "
            "previous day files are searched for bid/ask of contracts that never quoted "
            "on the loaded day (0 disables). Dim factor fades bar segments whose position "
            "came from the estimated-OI fallback rather than dealer flow."))
        layout.addLayout(form)
        layout.addStretch(1)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _on_rate(self, v: float) -> None:
        self.settings.risk_free_rate = float(v)
        self.settings.save()
        if callable(self.on_recompute):
            self.on_recompute()

    def _on_lookback(self, v: int) -> None:
        self.settings.quote_lookback_files = int(v)
        self.settings.save()
        if callable(self.on_reload):
            self.on_reload()

    def _on_speed(self, v: int) -> None:
        self.settings.playback_ms = int(v)
        self.settings.save()
        if callable(self.on_speed):
            self.on_speed()

    def _on_dim(self, v: float) -> None:
        self.settings.dim_factor = float(v)
        self.settings.save()
        if callable(self.on_repaint):
            self.on_repaint()
