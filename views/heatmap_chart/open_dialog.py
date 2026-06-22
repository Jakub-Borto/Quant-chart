"""Heatmap chart 'Open chart' dialog."""
from PyQt6.QtCore import QTime, Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QSpinBox, QTimeEdit, QVBoxLayout, QWidget,
)

from core import data_paths
from views.heatmap_chart.heatmap_config import HeatmapConfig
from core.styles import PALETTE

NO_ASSETS = "No assets found"
NONE_LABEL = "-None-"

DATASET_KEYWORD = "mbo"


def _to_qtime(value: str) -> QTime:
    t = QTime.fromString(value, "HH:mm")
    return t if t.isValid() else QTime(0, 0)


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


class HeatmapOpenDialog(QDialog):
    def __init__(
        self,
        *,
        root: str,
        futures_folder: str,
        options_folder: str,
        default_type: str,
        default_asset: str,
        date: str,
        time_start: str = "00:00",
        time_end: str   = "23:59",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open  ·  DOM Heatmap")
        self.setMinimumWidth(400)

        self.root             = root
        self.date             = date
        self._preferred_asset = default_asset
        self.config: HeatmapConfig | None = None

        self.type_combo    = QComboBox()
        self.asset_combo   = QComboBox()
        self.dataset_combo = QComboBox()

        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 365)
        self.days_spin.setValue(1)

        self.start_edit = QTimeEdit(_to_qtime(time_start))
        self.start_edit.setDisplayFormat("HH:mm")
        self.end_edit   = QTimeEdit(_to_qtime(time_end))
        self.end_edit.setDisplayFormat("HH:mm")

        types: list[str] = []
        for f in (futures_folder, options_folder):
            if f and f not in types:
                types.append(f)
        self.type_combo.addItems(types)
        if default_type in types:
            self.type_combo.setCurrentText(default_type)

        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        form.addRow(_label("Asset type"), self.type_combo)
        form.addRow(_label("Asset"),      self.asset_combo)
        form.addRow(_label("Dataset"),    self.dataset_combo)
        form.addRow(_label("Days back"),  self.days_spin)

        sep = QLabel("→")
        sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sep.setStyleSheet(f"color: {PALETTE['TEXT_DIM']}; background: transparent;")
        time_row = QHBoxLayout()
        time_row.setSpacing(6)
        time_row.addWidget(self.start_edit)
        time_row.addWidget(sep)
        time_row.addWidget(self.end_edit)
        form.addRow(_label("Time filter"), time_row)

        tf_lbl = QLabel("Rendered at 1-second resolution.")
        tf_lbl.setStyleSheet(f"""
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
        layout.addWidget(tf_lbl)
        layout.addWidget(date_lbl)
        layout.addWidget(divider)
        layout.addWidget(buttons)

        self.type_combo.currentTextChanged.connect(self._reload_assets)
        self.asset_combo.currentTextChanged.connect(self._reload_datasets)
        self._reload_assets()

    def _reload_assets(self) -> None:
        assets = data_paths.list_assets(self.root, self.type_combo.currentText())
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
        folders = ([] if asset == NO_ASSETS
                   else data_paths.list_datasets(self.root, self.type_combo.currentText(), asset))
        self.dataset_combo.blockSignals(True)
        self.dataset_combo.clear()
        self.dataset_combo.addItem(NONE_LABEL)
        self.dataset_combo.addItems(folders)
        self.dataset_combo.setCurrentText(_pick_default(folders, DATASET_KEYWORD))
        self.dataset_combo.blockSignals(False)

    @staticmethod
    def _value(combo) -> str:
        text = combo.currentText()
        return "" if text == NONE_LABEL else text

    def accept(self) -> None:
        if self.asset_combo.currentText() == NO_ASSETS:
            QMessageBox.warning(self, "Cannot open", "No assets found for this folder.")
            return
        self.config = HeatmapConfig(
            root=self.root,
            type_folder=self.type_combo.currentText(),
            asset=self.asset_combo.currentText(),
            dataset=self._value(self.dataset_combo),
            date=self.date,
            days_back=self.days_spin.value(),
            time_start=self.start_edit.time().toString("HH:mm"),
            time_end=self.end_edit.time().toString("HH:mm"),
        )
        super().accept()
