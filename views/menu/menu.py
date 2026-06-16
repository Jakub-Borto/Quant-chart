"""Main menu window."""
import os

from PyQt6.QtCore import QDate, QTime, Qt
from PyQt6.QtWidgets import (
    QComboBox, QDateEdit, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QTimeEdit, QVBoxLayout, QWidget,
)

from core import data_paths
from views.footprint_chart.open_dialog import OpenChartDialog
from core.settings import AppSettings, Keys
from core.styles import PALETTE
from views.footprint_chart.window import FootprintWindow

NO_ASSETS = "No assets found"


class MenuWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Quant Chart")
        self.setMinimumSize(560, 660)
        self.resize(640, 720)

        self.settings = AppSettings()
        self.open_windows: list = []

        self._build_ui()
        self._load_settings()
        self._reload_folder_combos()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralWidget")

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        root_layout.addWidget(self._build_title())
        root_layout.addWidget(self._build_data_group())
        root_layout.addWidget(self._build_selection_group())
        root_layout.addWidget(self._build_charts_group())
        root_layout.addStretch(1)

        self.setCentralWidget(central)

    def _build_title(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 4, 0, 8)
        layout.setSpacing(2)

        title = QLabel("QUANT CHART")
        title.setStyleSheet(f"""
            color: {PALETTE['TEXT_PRI']};
            font-size: 18pt;
            font-weight: 700;
            letter-spacing: 2px;
            background: transparent;
        """)

        subtitle = QLabel("Research & Analysis Platform")
        subtitle.setStyleSheet(f"""
            color: {PALETTE['TEXT_DIM']};
            font-size: 9pt;
            background: transparent;
        """)

        # accent line under title
        line = QWidget()
        line.setFixedHeight(2)
        line.setStyleSheet(f"background-color: {PALETTE['ACCENT']}; border-radius: 1px;")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(line)
        return w

    def _build_data_group(self) -> QGroupBox:
        box = QGroupBox("Data Configuration")
        form = QFormLayout(box)
        form.setSpacing(8)
        form.setContentsMargins(10, 16, 10, 10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("Select parquet root folder...")
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_root)
        root_row = QHBoxLayout()
        root_row.setSpacing(6)
        root_row.addWidget(self.root_edit)
        root_row.addWidget(browse_btn)

        self.futures_combo = QComboBox()
        self.options_combo = QComboBox()

        form.addRow(_label("Parquet folder"), root_row)
        form.addRow(_label("Futures folder"), self.futures_combo)
        form.addRow(_label("Options folder"), self.options_combo)

        self.root_edit.editingFinished.connect(self._on_root_changed)
        self.futures_combo.currentTextChanged.connect(self._on_futures_changed)
        self.options_combo.currentTextChanged.connect(self._on_options_changed)
        return box

    def _build_selection_group(self) -> QGroupBox:
        box = QGroupBox("Asset & Date")
        form = QFormLayout(box)
        form.setSpacing(8)
        form.setContentsMargins(10, 16, 10, 10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.asset_combo = QComboBox()

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())

        self.start_edit = QTimeEdit(QTime(0, 0))
        self.start_edit.setDisplayFormat("HH:mm")
        self.end_edit = QTimeEdit(QTime(23, 59))
        self.end_edit.setDisplayFormat("HH:mm")

        time_row = QHBoxLayout()
        time_row.setSpacing(6)
        sep = QLabel("→")
        sep.setStyleSheet(f"color: {PALETTE['TEXT_DIM']}; background: transparent;")
        sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_row.addWidget(self.start_edit)
        time_row.addWidget(sep)
        time_row.addWidget(self.end_edit)

        form.addRow(_label("Asset"), self.asset_combo)
        form.addRow(_label("Date"), self.date_edit)
        form.addRow(_label("Time filter"), time_row)

        self.asset_combo.currentTextChanged.connect(self._on_asset_changed)
        self.date_edit.dateChanged.connect(self._on_date_changed)
        self.start_edit.timeChanged.connect(self._on_time_changed)
        self.end_edit.timeChanged.connect(self._on_time_changed)
        return box

    def _build_charts_group(self) -> QGroupBox:
        box = QGroupBox("Open Chart")
        grid = QGridLayout(box)
        grid.setSpacing(10)
        grid.setContentsMargins(10, 16, 10, 10)

        charts = [
            ("Footprint Chart",  "Footprint & order flow",   lambda: self._open_chart("Footprint Chart", FootprintWindow)),
            ("Simple Chart",     "OHLCV multi-timeframe",    lambda: self._coming_soon("Simple Chart")),
            ("DOM Heatmap",      "Order book replay",        lambda: self._coming_soon("DOM Heatmap")),
            ("Options",          "Options analytics",        lambda: self._coming_soon("Options")),
        ]

        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for (title, subtitle, handler), (row, col) in zip(charts, positions):
            btn = self._chart_button(title, subtitle)
            btn.clicked.connect(handler)
            grid.addWidget(btn, row, col)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return box

    def _chart_button(self, title: str, subtitle: str) -> QPushButton:
        """A tall button with a title and a subtitle line."""
        btn = QPushButton()
        btn.setProperty("chartButton", True)
        btn.setMinimumHeight(72)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(btn)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"""
            color: {PALETTE['TEXT_PRI']};
            font-size: 11pt;
            font-weight: 600;
            background: transparent;
        """)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setStyleSheet(f"""
            color: {PALETTE['TEXT_DIM']};
            font-size: 8pt;
            background: transparent;
        """)
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout.addWidget(title_lbl)
        layout.addWidget(sub_lbl)
        return btn

    # ------------------------------------------------------------------
    # Settings load
    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        self.root_edit.setText(self.settings.get(Keys.ROOT, ""))

        date_str = self.settings.get(Keys.DATE, "")
        d = QDate.fromString(date_str, "yyyy-MM-dd")
        if d.isValid():
            self.date_edit.setDate(d)

        t_start = QTime.fromString(self.settings.get(Keys.TIME_START, "00:00"), "HH:mm")
        t_end   = QTime.fromString(self.settings.get(Keys.TIME_END,   "23:59"), "HH:mm")
        if t_start.isValid(): self.start_edit.setTime(t_start)
        if t_end.isValid():   self.end_edit.setTime(t_end)

    # ------------------------------------------------------------------
    # Folder combo population
    # ------------------------------------------------------------------
    def _reload_folder_combos(self) -> None:
        root    = self.root_edit.text().strip()
        subdirs = data_paths.list_type_folders(root)

        saved_fut = self.settings.get(Keys.FUTURES, "Futures")
        saved_opt = self.settings.get(Keys.OPTIONS, "Options_on_futures")

        for combo, saved in (
            (self.futures_combo, saved_fut),
            (self.options_combo, saved_opt),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(subdirs)
            if saved in subdirs:
                combo.setCurrentText(saved)
            combo.blockSignals(False)

        self._reload_assets()

    def _reload_assets(self) -> None:
        root   = self.root_edit.text().strip()
        assets = data_paths.list_assets(root, self.futures_combo.currentText())
        saved  = self.settings.get(Keys.ASSET, "ES")

        self.asset_combo.blockSignals(True)
        self.asset_combo.clear()
        if assets:
            self.asset_combo.addItems(assets)
            if saved in assets:
                self.asset_combo.setCurrentText(saved)
        else:
            self.asset_combo.addItem(NO_ASSETS)
        self.asset_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _browse_root(self) -> None:
        start = self.root_edit.text().strip() or ""
        path  = QFileDialog.getExistingDirectory(self, "Select parquet folder", start)
        if path:
            self.root_edit.setText(path)
            self._on_root_changed()

    def _on_root_changed(self)    -> None:
        self.settings.set(Keys.ROOT, self.root_edit.text().strip())
        self._reload_folder_combos()

    def _on_futures_changed(self) -> None:
        self.settings.set(Keys.FUTURES, self.futures_combo.currentText())
        self._reload_assets()

    def _on_options_changed(self) -> None:
        self.settings.set(Keys.OPTIONS, self.options_combo.currentText())

    def _on_asset_changed(self)   -> None:
        if self.asset_combo.currentText() != NO_ASSETS:
            self.settings.set(Keys.ASSET, self.asset_combo.currentText())

    def _on_date_changed(self)    -> None:
        self.settings.set(Keys.DATE, self.date_edit.date().toString("yyyy-MM-dd"))

    def _on_time_changed(self)    -> None:
        self.settings.set(Keys.TIME_START, self.start_edit.time().toString("HH:mm"))
        self.settings.set(Keys.TIME_END,   self.end_edit.time().toString("HH:mm"))

    # ------------------------------------------------------------------
    # Chart launching
    # ------------------------------------------------------------------
    def _open_chart(self, chart_name: str, window_cls) -> None:
        root = self.root_edit.text().strip()
        if not root or not os.path.isdir(root):
            QMessageBox.warning(self, "No data folder",
                                "Pick a valid parquet folder first.")
            return

        dialog = OpenChartDialog(
            root=root,
            futures_folder=self.futures_combo.currentText(),
            options_folder=self.options_combo.currentText(),
            default_type=self.futures_combo.currentText(),
            default_asset=self.asset_combo.currentText(),
            date=self.date_edit.date().toString("yyyy-MM-dd"),
            time_start=self.start_edit.time().toString("HH:mm"),
            time_end=self.end_edit.time().toString("HH:mm"),
            chart_name=chart_name,
            parent=self,
        )
        if dialog.exec() and dialog.config is not None:
            window = window_cls(dialog.config)
            window.show()
            self.open_windows.append(window)

    def _coming_soon(self, name: str) -> None:
        QMessageBox.information(self, name, f"{name} is not implemented yet.")


# ------------------------------------------------------------------
def _label(text: str) -> QLabel:
    """Styled form label."""
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        color: {PALETTE['TEXT_SEC']};
        background: transparent;
        font-size: 9pt;
    """)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return lbl
