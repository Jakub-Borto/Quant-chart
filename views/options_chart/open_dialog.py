"""Options exposure chart 'Open chart' dialog."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QMessageBox, QVBoxLayout, QWidget,
)

from core import data_paths
from views.options_chart.options_config import OptionsConfig
from core.styles import PALETTE

NO_ASSETS = "No assets found"
NONE_LABEL = "-None-"

DATASET_KEYWORD = "5m"
FUTURES_KEYWORD = "ohlcv"


def _label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        color: {PALETTE['TEXT_SEC']};
        background: transparent;
        font-size: 9pt;
    """)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return lbl


def _pick_default(folders, keyword):
    for f in folders:
        if keyword.lower() in f.lower():
            return f
    return NONE_LABEL


class OptionsOpenDialog(QDialog):
    def __init__(
        self,
        *,
        root: str,
        futures_folder: str,
        options_folder: str,
        default_type: str = "",
        default_asset: str = "",
        date: str = "",
        time_start: str = "00:00",
        time_end: str = "23:59",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open  ·  Options Exposure")
        self.setMinimumWidth(400)

        self.root             = root
        self.date             = date
        self.options_folder   = options_folder
        self.futures_folder   = futures_folder
        self._preferred_asset = default_asset
        self.config: OptionsConfig | None = None

        self.asset_combo   = QComboBox()
        self.dataset_combo = QComboBox()
        self.futures_combo = QComboBox()

        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow(_label("Asset"),           self.asset_combo)
        form.addRow(_label("Options dataset"), self.dataset_combo)
        form.addRow(_label("Futures dataset"), self.futures_combo)

        fut_lbl = QLabel("Futures dataset supplies the underlying price for the greeks.")
        fut_lbl.setStyleSheet(f"""
            color: {PALETTE['TEXT_DIM']};
            background: transparent;
            font-size: 8pt;
        """)

        date_lbl = QLabel(f"Anchor date: {self.date}")
        date_lbl.setStyleSheet(f"""
            color: {PALETTE['TEXT_DIM']};
            background: transparent;
            font-size: 8pt;
            padding: 4px 0 0 0;
        """)

        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {PALETTE['BORDER']};")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(fut_lbl)
        layout.addWidget(date_lbl)
        layout.addWidget(divider)
        layout.addWidget(buttons)

        self.asset_combo.currentTextChanged.connect(self._reload_datasets)
        self._reload_assets()

    def _reload_assets(self) -> None:
        assets = data_paths.list_assets(self.root, self.options_folder)
        self.asset_combo.blockSignals(True)
        self.asset_combo.clear()
        if assets:
            self.asset_combo.addItems(assets)
            if self._preferred_asset in assets:
                self.asset_combo.setCurrentText(self._preferred_asset)
        else:
            self.asset_combo.addItem(NO_ASSETS)
        self.asset_combo.blockSignals(False)
        self._reload_datasets()

    def _reload_datasets(self) -> None:
        asset = self.asset_combo.currentText()
        opt = ([] if asset == NO_ASSETS
               else data_paths.list_datasets(self.root, self.options_folder, asset))
        fut = ([] if asset == NO_ASSETS
               else data_paths.list_datasets(self.root, self.futures_folder, asset))
        for combo, folders, keyword in (
                (self.dataset_combo, opt, DATASET_KEYWORD),
                (self.futures_combo, fut, FUTURES_KEYWORD)):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(NONE_LABEL)
            combo.addItems(folders)
            combo.setCurrentText(_pick_default(folders, keyword))
            combo.blockSignals(False)

    @staticmethod
    def _value(combo) -> str:
        text = combo.currentText()
        return "" if text == NONE_LABEL else text

    def accept(self) -> None:
        if self.asset_combo.currentText() == NO_ASSETS:
            QMessageBox.warning(self, "Cannot open", "No assets found for this folder.")
            return
        if not self._value(self.dataset_combo):
            QMessageBox.warning(self, "Cannot open", "Select an options dataset.")
            return
        if not self._value(self.futures_combo):
            QMessageBox.warning(self, "Cannot open",
                                "Select a futures dataset (underlying price source).")
            return
        self.config = OptionsConfig(
            root=self.root,
            type_folder=self.options_folder,
            asset=self.asset_combo.currentText(),
            dataset=self._value(self.dataset_combo),
            futures_type_folder=self.futures_folder,
            futures_dataset=self._value(self.futures_combo),
            date=self.date,
        )
        super().accept()
