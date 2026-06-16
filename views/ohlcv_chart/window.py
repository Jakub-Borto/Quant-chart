"""OHLCV chart window — stub that displays the resolved config."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from views.ohlcv_chart.ohlcv_config import OhlcvConfig
from core.styles import PALETTE


class OhlcvWindow(QMainWindow):
    def __init__(self, config: OhlcvConfig) -> None:
        super().__init__()
        self.setWindowTitle(f"OHLCV Chart — {config.asset}")
        self.resize(520, 340)

        lines = [
            ("Asset type",   config.type_folder),
            ("Asset",        config.asset),
            ("Dataset",      config.dataset or "-None-"),
            ("Indicators",   config.indicators_dataset or "-None-"),
            ("Anchor date",  config.date),
            ("Days back",    str(config.days_back)),
            ("Timeframe",    config.timeframe_str()),
            ("Time filter",  f"{config.time_start} → {config.time_end}"),
        ]

        text = "\n".join(f"{k}:  {v}" for k, v in lines)

        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        label.setStyleSheet(f"""
            color: {PALETTE['TEXT_PRI']};
            font-size: 11pt;
            font-family: monospace;
            padding: 24px;
            background: transparent;
        """)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addStretch(1)

        self.setCentralWidget(container)
