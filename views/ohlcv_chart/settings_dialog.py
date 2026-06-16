"""OHLCV chart settings dialog."""
from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QStackedWidget, QTimeEdit, QVBoxLayout, QWidget,
)

from core.styles import PALETTE


def _to_qtime(value: str) -> QTime:
    t = QTime.fromString(str(value), "HH:mm")
    return t if t.isValid() else QTime(9, 30)


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {PALETTE['TEXT_DIM']}; background: transparent; font-size: 8pt;")
    return lbl


class OhlcvSettingsDialog(QDialog):
    def __init__(self, general_settings, on_change, parent=None) -> None:
        super().__init__(parent)
        self.general_settings = general_settings
        self.on_change = on_change
        self.setWindowTitle("Chart Settings")
        self.setMinimumSize(520, 320)

        self.categories = QListWidget()
        self.categories.addItem("General")
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

    def _general_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("RTH Session")
        title.setStyleSheet(f"color: {PALETTE['TEXT_PRI']}; font-size: 11pt; font-weight: 600;")
        layout.addWidget(title)
        layout.addWidget(_hint(
            "The regular-trading-hours window used for the VWAP RTH anchor. "
            "Start is inclusive, end exclusive."))
        layout.addSpacing(6)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        g = self.general_settings

        def _lbl(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {PALETTE['TEXT_SEC']}; background: transparent; font-size: 9pt;")
            return lbl

        self.g_rth_start = QTimeEdit(_to_qtime(g.rth_start))
        self.g_rth_start.setDisplayFormat("HH:mm")
        self.g_rth_start.setFixedWidth(100)
        self.g_rth_start.timeChanged.connect(self._on_rth_start)
        form.addRow(_lbl("RTH start (incl.)"), self.g_rth_start)

        self.g_rth_end = QTimeEdit(_to_qtime(g.rth_end))
        self.g_rth_end.setDisplayFormat("HH:mm")
        self.g_rth_end.setFixedWidth(100)
        self.g_rth_end.timeChanged.connect(self._on_rth_end)
        form.addRow(_lbl("RTH end (excl.)"), self.g_rth_end)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _on_rth_start(self, t):
        self.general_settings.rth_start = t.toString("HH:mm")
        self.general_settings.save()
        if callable(self.on_change):
            self.on_change()

    def _on_rth_end(self, t):
        self.general_settings.rth_end = t.toString("HH:mm")
        self.general_settings.save()
        if callable(self.on_change):
            self.on_change()
