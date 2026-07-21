"""Trade replay window.

Steps through trades from a backtest parquet file, shows a detail panel +
filterable table, and pushes the selected trade to every open chart window:
each chart reloads on the trade's date and footprint/OHLCV charts get the
trade auto-drawn as a position (entry/exit time, SL, TP). The heatmap only
follows the date (no drawing).
"""
import math
import os
import traceback
import weakref
from pathlib import Path

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSplitter, QTableView, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.drawing_anchors import times_ns_of
from core.settings import AppSettings, Keys
from core.styles import PALETTE
from views.footprint_chart.window import FootprintWindow
from views.ohlcv_chart.window import OhlcvWindow
from views.trade_replay.filter_expr import compute_mask, parse_spec
from views.trade_replay.helpers import (
    ChartHandle, PluginContext, discover_plugins, parse_params, plugins_dir,
    run_plugin,
)
from views.trade_replay.trades_data import (
    default_trades_dir, list_trade_files, load_trades,
)
from views.trade_replay.trades_table import (
    TradesFilterProxy, TradesTableModel, format_duration, format_value,
    header_name,
)
from views.trade_replay.widgets import (
    EquityCurveView, EquitySparkline, FilterHeader, StatCard,
)

# fixed detail cards, in display order (only columns present in the file show)
CARD_SPECS = [
    ("Direction", "direction"), ("Tick PnL", "ticks"),
    ("SL Ticks", "sl_ticks"), ("TP Ticks", "tp_ticks"), ("RR", "rr"),
    ("Duration", "duration_min"), ("Exit Reason", "exit_reason"),
    ("Trade Type", "trade_type"),
]
_CARDS_PER_ROW = 5
_NOTES_PER_ROW = 4


def _fmt_note(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


class TradeReplayWindow(QMainWindow):
    def __init__(self, menu, parent=None) -> None:
        super().__init__(parent)
        self.menu = menu
        self.settings = AppSettings()
        self._trade_set = None
        self.model = None
        self._mask = None
        self._equity = None       # (cum, ticks, src_rows, dates) of filtered set
        # (weakref to chart window, position dict) of the auto-drawn trade
        self._auto_positions: list = []

        self.setWindowTitle("Trade Replay")
        self.resize(1500, 950)
        self._build_ui()
        self._refresh_files()

    # ── UI construction ────────────────────────────────────────────────
    def _build_ui(self) -> None:
        left = QWidget()
        root = QVBoxLayout(left)
        root.setContentsMargins(10, 8, 4, 8)
        root.setSpacing(8)
        root.addWidget(self._build_file_bar())
        root.addWidget(self._build_nav_bar())
        root.addWidget(self._build_stats_bar())

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_detail_panel(), "Trade Detail")
        self.tabs.addTab(self._build_breakdown_tab(), "Breakdown")
        self.splitter.addWidget(self.tabs)
        self.splitter.addWidget(self._build_table())
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([380, 520])
        root.addWidget(self.splitter, 1)

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.side_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.side_splitter.addWidget(left)
        self.side_splitter.addWidget(self._build_plugin_panel())
        self.side_splitter.setStretchFactor(0, 1)
        self.side_splitter.setStretchFactor(1, 0)
        self.side_splitter.setSizes([1200, 280])
        outer.addWidget(self.side_splitter)
        self.setCentralWidget(central)

    def _build_file_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(QLabel("Trades folder:"))
        self.dir_label = QLabel(self._trades_dir())
        self.dir_label.setStyleSheet(f"color: {PALETTE['TEXT_PRI']};")
        row.addWidget(self.dir_label)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self._browse_dir)
        row.addWidget(btn_browse)
        row.addSpacing(12)
        row.addWidget(QLabel("File:"))
        self.file_combo = QComboBox()
        self.file_combo.setMinimumWidth(420)
        self.file_combo.activated.connect(lambda _i: self._load_file())
        row.addWidget(self.file_combo, 1)
        btn_refresh = QPushButton("⟳")
        btn_refresh.setFixedWidth(32)
        btn_refresh.setToolTip("Rescan folder")
        btn_refresh.clicked.connect(self._refresh_files)
        row.addWidget(btn_refresh)
        return bar

    def _build_nav_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.btn_prev = QPushButton("◄")
        self.btn_prev.setFixedWidth(44)
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.btn_next = QPushButton("►")
        self.btn_next.setFixedWidth(44)
        self.btn_next.clicked.connect(lambda: self._step(1))
        self.nav_label = QLabel("Trade — / —")
        self.nav_label.setStyleSheet(
            f"color: {PALETTE['TEXT_PRI']}; font-weight: 600; padding: 0 8px;")
        row.addWidget(self.btn_prev)
        row.addWidget(self.btn_next)
        row.addWidget(self.nav_label)
        row.addSpacing(16)
        self.btn_load = QPushButton("Load to charts")
        self.btn_load.setMinimumHeight(34)
        self.btn_load.setStyleSheet(
            f"QPushButton {{ background-color: {PALETTE['ACCENT']};"
            f" color: {PALETTE['TEXT_PRI']}; font-weight: 600; padding: 6px 22px; }}"
            f"QPushButton:hover {{ background-color: {PALETTE['ACCENT_HOV']}; }}")
        self.btn_load.setToolTip(
            "Set every open chart to this trade's date and draw the trade\n"
            "on footprint / OHLCV charts (heatmap follows the date only)")
        self.btn_load.clicked.connect(self._load_to_charts)
        row.addWidget(self.btn_load)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {PALETTE['TEXT_DIM']};")
        row.addWidget(self.status_label, 1)
        return bar

    def _build_stats_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.stat_cards = {}
        for key, title in [("n", "Trades"), ("win_rate", "Win Rate"),
                           ("total", "Total Ticks"), ("avg_win", "Avg Win"),
                           ("avg_loss", "Avg Loss"), ("pf", "Profit Factor"),
                           ("max_dd", "Max DD")]:
            card = StatCard(title)
            self.stat_cards[key] = card
            row.addWidget(card)
        self.sparkline = EquitySparkline()
        self.sparkline.clicked.connect(self._open_equity_dialog)
        row.addWidget(self.sparkline)
        row.addStretch(1)
        return bar

    def _build_detail_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.detail_title = QLabel("Trade Detail")
        self.detail_title.setStyleSheet(
            f"color: {PALETTE['TEXT_PRI']}; font-size: 12pt; font-weight: 600;"
            f" border-left: 3px solid {PALETTE['ACCENT']}; padding-left: 8px;")
        lay.addWidget(self.detail_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(8)

        self.cards_widget = QWidget()
        self.cards_grid = QGridLayout(self.cards_widget)
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setSpacing(6)
        inner_lay.addWidget(self.cards_widget)

        self.notes_group = QGroupBox("Trade notes")
        self.notes_grid = QGridLayout(self.notes_group)
        self.notes_grid.setContentsMargins(10, 10, 10, 10)
        self.notes_grid.setSpacing(10)
        inner_lay.addWidget(self.notes_group)
        self.notes_group.hide()
        inner_lay.addStretch(1)

        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        self._detail_cards = {}       # column -> StatCard
        return panel

    def _build_table(self) -> QWidget:
        self.table = QTableView()
        self.header = FilterHeader(self.table)
        self.table.setHorizontalHeader(self.header)
        self.proxy = TradesFilterProxy(self)
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.header.setDefaultSectionSize(92)
        self.header.setMinimumSectionSize(64)
        self.header.filters_changed.connect(self._on_filters_changed)
        self.table.horizontalScrollBar().valueChanged.connect(
            lambda _v: self.header._position_editors())
        self.table.selectionModel().selectionChanged.connect(
            lambda *_: self._on_selection_changed())
        self.table.doubleClicked.connect(lambda _i: self._load_to_charts())
        return self.table

    # ── file handling ──────────────────────────────────────────────────
    def _trades_dir(self) -> str:
        stored = self.settings.get(Keys.REPLAY_DIR)
        if stored:
            return stored
        return default_trades_dir(self.settings.get(Keys.ROOT))

    def _browse_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Trades folder", self._trades_dir())
        if folder:
            self.settings.set(Keys.REPLAY_DIR, folder)
            self.dir_label.setText(folder)
            self._refresh_files()

    def _refresh_files(self) -> None:
        folder = self._trades_dir()
        self.dir_label.setText(folder)
        files = list_trade_files(folder)
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        for f in files:
            self.file_combo.addItem(f.name, str(f))
        last = self.settings.get(Keys.REPLAY_FILE)
        idx = self.file_combo.findData(last)
        if idx >= 0:
            self.file_combo.setCurrentIndex(idx)
        self.file_combo.blockSignals(False)
        self._load_file()

    def _load_file(self) -> None:
        path = self.file_combo.currentData()
        trade_set = load_trades(path) if path else None
        if trade_set is None:
            self._trade_set = None
            self.model = None
            self.proxy.setSourceModel(None)
            self.nav_label.setText("Trade — / —")
            self.detail_title.setText("Trade Detail")
            self.notes_group.hide()
            if path:
                QMessageBox.warning(self, "Trade Replay",
                                    f"Could not load trades from:\n{path}")
            return
        self.settings.set(Keys.REPLAY_FILE, path)
        self._trade_set = trade_set
        self._mask = np.ones(len(trade_set), dtype=bool)
        self.model = TradesTableModel(trade_set, self)
        self.proxy.set_mask(None)
        self.proxy.setSourceModel(self.model)
        self.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)

        kinds, cat_values = [], {}
        for i, col in enumerate(trade_set.table_cols):
            kind = trade_set.column_kind(col)
            if kind == "categorical":
                kinds.append("categorical")
                cat_values[i] = sorted({str(v) for v in trade_set.df[col] if str(v)})
            else:
                kinds.append(kind if kind in ("time", "date") else "numeric")
        self.header.set_columns(kinds, cat_values)
        self.table.resizeColumnsToContents()

        self._build_detail_cards(trade_set)
        self._refresh_breakdown_dims()
        self._update_stats()
        if self.proxy.rowCount():
            self._select_proxy_row(0)
        self.status_label.setText("")

    # ── detail panel ───────────────────────────────────────────────────
    def _build_detail_cards(self, trade_set) -> None:
        for card in self._detail_cards.values():
            card.deleteLater()
        self._detail_cards = {}
        specs = [(title, col) for title, col in CARD_SPECS
                 if col in trade_set.df.columns]
        specs += [(header_name(col), col) for col in trade_set.extra_cols]
        for i, (title, col) in enumerate(specs):
            card = StatCard(title)
            self._detail_cards[col] = card
            self.cards_grid.addWidget(card, i // _CARDS_PER_ROW, i % _CARDS_PER_ROW)

    def _show_trade(self, source_row: int) -> None:
        ts = self._trade_set
        trade = ts.df.iloc[source_row]
        self.detail_title.setText(f"Trade Detail — {trade['date']}")
        for col, card in self._detail_cards.items():
            value = trade[col]
            color = None
            if col == "direction":
                card.set_value(str(value).upper(),
                               PALETTE["SUCCESS"] if value == "long" else PALETTE["DANGER"])
                continue
            if col == "ticks" and isinstance(value, (int, float, np.floating)):
                if not (isinstance(value, float) and math.isnan(value)):
                    color = PALETTE["SUCCESS"] if value >= 0 else PALETTE["DANGER"]
            card.set_value(format_value(col, value), color)
        self._rebuild_notes(ts.notes[source_row])

    def _rebuild_notes(self, notes: dict) -> None:
        while self.notes_grid.count():
            item = self.notes_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if not notes:
            self.notes_group.hide()
            return
        for i, (key, value) in enumerate(notes.items()):
            cell = QWidget()
            lay = QVBoxLayout(cell)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(1)
            k = QLabel(str(key))
            k.setStyleSheet(f"color: {PALETTE['TEXT_DIM']}; font-size: 8pt;")
            v = QLabel(_fmt_note(value))
            v.setStyleSheet(f"color: {PALETTE['TEXT_PRI']}; font-weight: 600;")
            v.setWordWrap(True)
            lay.addWidget(k)
            lay.addWidget(v)
            self.notes_grid.addWidget(cell, i // _NOTES_PER_ROW, i % _NOTES_PER_ROW)
        self.notes_group.show()

    # ── navigation / selection ─────────────────────────────────────────
    def _current_proxy_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _current_source_row(self):
        r = self._current_proxy_row()
        if r < 0 or self.model is None:
            return None
        return self.proxy.mapToSource(self.proxy.index(r, 0)).row()

    def _select_proxy_row(self, row: int) -> None:
        if not self.proxy.rowCount():
            return
        row = max(0, min(row, self.proxy.rowCount() - 1))
        index = self.proxy.index(row, 0)
        self.table.selectionModel().setCurrentIndex(
            index,
            self.table.selectionModel().SelectionFlag.ClearAndSelect
            | self.table.selectionModel().SelectionFlag.Rows)
        self.table.scrollTo(index)

    def _step(self, delta: int) -> None:
        cur = self._current_proxy_row()
        self._select_proxy_row((cur if cur >= 0 else 0) + delta)

    def _on_selection_changed(self) -> None:
        src = self._current_source_row()
        n = self.proxy.rowCount()
        cur = self._current_proxy_row()
        self.nav_label.setText(
            f"Trade {cur + 1} / {n}" if cur >= 0 and n else "Trade — / —")
        self.btn_prev.setEnabled(cur > 0)
        self.btn_next.setEnabled(0 <= cur < n - 1)
        if src is not None:
            self._show_trade(src)
        if getattr(self, "_equity_dlg", None) is not None:
            self.equity_view.set_selected_source_row(src)

    # ── filtering / stats ──────────────────────────────────────────────
    def _on_filters_changed(self) -> None:
        ts = self._trade_set
        if ts is None:
            return
        raw = self.header.filters()
        filters = {}
        for i, col in enumerate(ts.table_cols):
            spec = raw.get(i)
            if spec is None:
                self.header.mark_invalid(i, False)
                continue
            if isinstance(spec, str):
                kind = ts.column_kind(col)
                kind = kind if kind in ("time", "date") else "numeric"
                if parse_spec(spec, kind) is None:
                    self.header.mark_invalid(i, True)
                    continue
                self.header.mark_invalid(i, False)
            filters[col] = spec
        self._mask = compute_mask(ts, filters)

        cur_src = self._current_source_row()
        self.proxy.set_mask(self._mask)
        if cur_src is not None and self.model is not None:
            pidx = self.proxy.mapFromSource(self.model.index(cur_src, 0))
            self._select_proxy_row(pidx.row() if pidx.isValid() else 0)
        elif self.proxy.rowCount():
            self._select_proxy_row(0)
        self._on_selection_changed()
        self._update_stats()

    def _update_stats(self) -> None:
        ts = self._trade_set
        cards = self.stat_cards
        if ts is None or "ticks" not in ts.df.columns:
            for card in cards.values():
                card.set_value("—")
            self.sparkline.set_series(np.array([]))
            self._equity = None
            self._push_equity_data()
            self._update_breakdown()
            return
        ticks_all = ts.df["ticks"].to_numpy(dtype=float)
        src = np.where(self._mask)[0]
        src = src[~np.isnan(ticks_all[src])]
        ticks = ticks_all[src]
        n = len(ticks)
        cards["n"].set_value(str(n))
        if not n:
            for key in ("win_rate", "total", "avg_win", "avg_loss", "pf", "max_dd"):
                cards[key].set_value("—")
            self.sparkline.set_series(np.array([]))
            self._equity = None
            self._push_equity_data()
            self._update_breakdown()
            return
        wins, losses = ticks[ticks > 0], ticks[ticks < 0]
        total = float(ticks.sum())
        cards["win_rate"].set_value(f"{len(wins) / n * 100:.1f}%")
        cards["total"].set_value(
            f"{total:+.0f}",
            PALETTE["SUCCESS"] if total >= 0 else PALETTE["DANGER"])
        cards["avg_win"].set_value(f"{wins.mean():.1f}" if len(wins) else "—",
                                   PALETTE["SUCCESS"])
        cards["avg_loss"].set_value(f"{losses.mean():.1f}" if len(losses) else "—",
                                    PALETTE["DANGER"])
        if len(losses) and abs(losses.sum()) > 0:
            cards["pf"].set_value(f"{wins.sum() / abs(losses.sum()):.2f}")
        else:
            cards["pf"].set_value("∞" if len(wins) else "—")
        cum = np.cumsum(ticks)
        max_dd = float((np.maximum.accumulate(cum) - cum).max())
        cards["max_dd"].set_value(f"-{max_dd:.0f}", PALETTE["DANGER"])
        self.sparkline.set_series(cum)
        self._equity = (cum, ticks, src, ts.df["date"].to_numpy()[src])
        self._push_equity_data()
        self._update_breakdown()

    # ── equity dialog ──────────────────────────────────────────────────
    def _open_equity_dialog(self) -> None:
        dlg = getattr(self, "_equity_dlg", None)
        if dlg is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Equity curve — filtered trades (click a point "
                               "to open that trade)")
            dlg.resize(1000, 480)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(8, 8, 8, 8)
            self.equity_view = EquityCurveView()
            self.equity_view.trade_clicked.connect(self._on_equity_trade_clicked)
            lay.addWidget(self.equity_view)
            self._equity_dlg = dlg
        self._push_equity_data()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _push_equity_data(self) -> None:
        if getattr(self, "_equity_dlg", None) is None:
            return
        if self._equity is None:
            self.equity_view.set_data([], [], [], [])
        else:
            cum, ticks, src, dates = self._equity
            self.equity_view.set_data(cum, ticks, src, dates)
        self.equity_view.set_selected_source_row(self._current_source_row())

    def _on_equity_trade_clicked(self, src_row: int) -> None:
        if self.model is None:
            return
        pidx = self.proxy.mapFromSource(self.model.index(src_row, 0))
        if pidx.isValid():
            self._select_proxy_row(pidx.row())
            self.tabs.setCurrentIndex(0)   # show the trade detail

    # ── breakdown tab ──────────────────────────────────────────────────
    _BREAKDOWN_COLS = ["Bucket", "Trades", "Win %", "Total", "Avg",
                       "Avg Win", "Avg Loss", "PF"]

    def _build_breakdown_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Group by:"))
        self.breakdown_combo = QComboBox()
        self.breakdown_combo.setFixedWidth(160)
        self.breakdown_combo.currentIndexChanged.connect(
            lambda _i: self._update_breakdown())
        row.addWidget(self.breakdown_combo)
        note = QLabel("stats over the filtered set")
        note.setStyleSheet(f"color: {PALETTE['TEXT_DIM']};")
        row.addWidget(note)
        row.addStretch(1)
        v.addLayout(row)

        self.breakdown_table = QTableWidget()
        self.breakdown_table.setColumnCount(len(self._BREAKDOWN_COLS))
        self.breakdown_table.setHorizontalHeaderLabels(self._BREAKDOWN_COLS)
        self.breakdown_table.verticalHeader().setVisible(False)
        self.breakdown_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self.breakdown_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection)
        self.breakdown_table.setAlternatingRowColors(True)
        self.breakdown_table.horizontalHeader().setDefaultSectionSize(84)
        self.breakdown_table.setColumnWidth(0, 150)
        v.addWidget(self.breakdown_table, 1)
        return w

    _DIM_ORDER = ["Trade type", "Exit reason", "Direction", "Day of week",
                  "Entry hour", "Duration", "Month"]
    _WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday"]

    def _refresh_breakdown_dims(self) -> None:
        ts = self._trade_set
        self.breakdown_combo.blockSignals(True)
        current = self.breakdown_combo.currentText()
        self.breakdown_combo.clear()
        if ts is not None:
            cols = ts.df.columns
            avail = {"Trade type": "trade_type", "Exit reason": "exit_reason",
                     "Direction": "direction", "Day of week": "date",
                     "Entry hour": "entry_time", "Duration": "duration_min",
                     "Month": "date"}
            for dim in self._DIM_ORDER:
                if avail[dim] in cols:
                    self.breakdown_combo.addItem(dim)
            idx = self.breakdown_combo.findText(current)
            if idx >= 0:
                self.breakdown_combo.setCurrentIndex(idx)
        self.breakdown_combo.blockSignals(False)

    def _bucket_labels(self, dim: str, df) -> pd.Series:
        if dim == "Trade type":
            return df["trade_type"].map(lambda v: str(v) or "(none)")
        if dim == "Exit reason":
            return df["exit_reason"].astype(str)
        if dim == "Direction":
            return df["direction"].astype(str)
        if dim == "Day of week":
            return pd.to_datetime(df["date"]).dt.day_name()
        if dim == "Entry hour":
            return pd.Series(pd.DatetimeIndex(df["entry_time"]).hour,
                             index=df.index).map(lambda h: f"{h:02d}:00")
        if dim == "Duration":
            def bucket(m):
                if math.isnan(m):
                    return "(unknown)"
                if m < 15:
                    return "< 15m"
                if m < 60:
                    return "15–60m"
                if m < 180:
                    return "1–3h"
                return "> 3h"
            return df["duration_min"].map(bucket)
        if dim == "Month":
            return df["date"].str[:7]
        return pd.Series("", index=df.index)

    def _update_breakdown(self) -> None:
        table = getattr(self, "breakdown_table", None)
        if table is None:
            return
        table.setRowCount(0)
        ts = self._trade_set
        dim = self.breakdown_combo.currentText()
        if ts is None or not dim or "ticks" not in ts.df.columns:
            return
        df = ts.df[self._mask]
        if df.empty:
            return
        g = pd.DataFrame({"bucket": self._bucket_labels(dim, df),
                          "ticks": df["ticks"].to_numpy(dtype=float)})
        g = g.dropna()
        if g.empty:
            return

        # stable, meaningful bucket order per dimension
        buckets = list(g["bucket"].unique())
        if dim == "Day of week":
            buckets.sort(key=lambda b: self._WEEKDAYS.index(b)
                         if b in self._WEEKDAYS else 99)
        elif dim == "Duration":
            order = ["< 15m", "15–60m", "1–3h", "> 3h", "(unknown)"]
            buckets.sort(key=lambda b: order.index(b) if b in order else 99)
        elif dim in ("Entry hour", "Month"):
            buckets.sort()
        else:
            totals = g.groupby("bucket")["ticks"].sum()
            buckets.sort(key=lambda b: -totals[b])

        green, red = PALETTE["SUCCESS"], PALETTE["DANGER"]
        table.setRowCount(len(buckets))
        for r, bucket in enumerate(buckets):
            t = g.loc[g["bucket"] == bucket, "ticks"].to_numpy()
            wins, losses = t[t > 0], t[t < 0]
            total = float(t.sum())
            if len(losses) and abs(losses.sum()) > 0:
                pf = f"{wins.sum() / abs(losses.sum()):.2f}"
            else:
                pf = "∞" if len(wins) else "—"
            cells = [
                (str(bucket), None),
                (str(len(t)), None),
                (f"{len(wins) / len(t) * 100:.0f}%", None),
                (f"{total:+.0f}", green if total >= 0 else red),
                (f"{t.mean():+.1f}", green if t.mean() >= 0 else red),
                (f"{wins.mean():.1f}" if len(wins) else "—", green),
                (f"{losses.mean():.1f}" if len(losses) else "—", red),
                (pf, None),
            ]
            for c, (text, color) in enumerate(cells):
                item = QTableWidgetItem(text)
                if c > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                if color:
                    item.setForeground(QColor(color))
                table.setItem(r, c, item)

    # ── plugins (right-side panel) ─────────────────────────────────────
    def _build_plugin_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(6, 8, 10, 8)
        lay.setSpacing(8)

        box = QGroupBox("Plugin")
        v = QVBoxLayout(box)
        v.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.plugin_combo = QComboBox()
        self.plugin_combo.currentIndexChanged.connect(
            lambda _i: self.settings.set(
                Keys.REPLAY_PLUGIN, self.plugin_combo.currentData() or ""))
        row.addWidget(self.plugin_combo, 1)
        btn_refresh = QPushButton("⟳")
        btn_refresh.setFixedWidth(28)
        btn_refresh.setToolTip("Rescan plugins folder")
        btn_refresh.clicked.connect(self._refresh_plugin_list)
        row.addWidget(btn_refresh)
        v.addLayout(row)

        params_lbl = QLabel("Params  (ctx.params)")
        v.addWidget(params_lbl)
        self.params_edit = QPlainTextEdit(self.settings.get(Keys.REPLAY_PARAMS))
        self.params_edit.setPlaceholderText(
            'start=09:30\nmult=2\nlabel="my note"\nfast')
        self.params_edit.setToolTip(
            "key=value pairs (space- or newline-separated), read by plugins as\n"
            "ctx.params / ctx.param(key, default). Values auto-typed: int,\n"
            "float, true/false, quoted strings; bare words become True flags.")
        self.params_edit.setMaximumHeight(88)
        self._params_save = QTimer(self)
        self._params_save.setSingleShot(True)
        self._params_save.setInterval(600)
        self._params_save.timeout.connect(
            lambda: self.settings.set(Keys.REPLAY_PARAMS,
                                      self.params_edit.toPlainText()))
        self.params_edit.textChanged.connect(self._params_save.start)
        v.addWidget(self.params_edit)

        self.chk_autorun = QCheckBox("Auto-run on every load")
        self.chk_autorun.setToolTip(
            "Re-run the selected plugin automatically each time a trade is\n"
            "loaded to the charts (Load button, double-click a row)")
        self.chk_autorun.setChecked(
            self.settings.get(Keys.REPLAY_PLUGIN_AUTORUN, True, bool))
        self.chk_autorun.toggled.connect(
            lambda on: self.settings.set(Keys.REPLAY_PLUGIN_AUTORUN, on))
        v.addWidget(self.chk_autorun)

        self.chk_loadfirst = QCheckBox("Run button loads trade first")
        self.chk_loadfirst.setChecked(
            self.settings.get(Keys.REPLAY_PLUGIN_AUTOLOAD, True, bool))
        self.chk_loadfirst.toggled.connect(
            lambda on: self.settings.set(Keys.REPLAY_PLUGIN_AUTOLOAD, on))
        v.addWidget(self.chk_loadfirst)

        self.btn_run = QPushButton("Run plugin")
        self.btn_run.setMinimumHeight(30)
        self.btn_run.setStyleSheet(
            f"QPushButton {{ background-color: {PALETTE['ACCENT']};"
            f" color: {PALETTE['TEXT_PRI']}; font-weight: 600; }}"
            f"QPushButton:hover {{ background-color: {PALETTE['ACCENT_HOV']}; }}")
        self.btn_run.clicked.connect(lambda: self._run_plugin())
        v.addWidget(self.btn_run)

        small = QHBoxLayout()
        small.setSpacing(4)
        btn_clear_ann = QPushButton("Clear drawings")
        btn_clear_ann.setToolTip("Remove plugin annotations from all charts")
        btn_clear_ann.clicked.connect(self._clear_plugin_drawings)
        small.addWidget(btn_clear_ann)
        btn_folder = QPushButton("Folder")
        btn_folder.setToolTip("Open the plugins folder")
        btn_folder.clicked.connect(lambda: os.startfile(str(plugins_dir())))
        small.addWidget(btn_folder)
        v.addLayout(small)
        lay.addWidget(box)

        out_box = QGroupBox("Output")
        ov = QVBoxLayout(out_box)
        self.output_text = QPlainTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Consolas", 9))
        ov.addWidget(self.output_text)
        btn_clear_out = QPushButton("Clear output")
        btn_clear_out.clicked.connect(self.output_text.clear)
        ov.addWidget(btn_clear_out)
        lay.addWidget(out_box, 1)

        self._refresh_plugin_list()
        return panel

    def _refresh_plugin_list(self) -> None:
        current = (self.plugin_combo.currentData()
                   or self.settings.get(Keys.REPLAY_PLUGIN))
        self.plugin_combo.blockSignals(True)
        self.plugin_combo.clear()
        for name, path in discover_plugins():
            self.plugin_combo.addItem(name, str(path))
        idx = self.plugin_combo.findData(current)
        if idx >= 0:
            self.plugin_combo.setCurrentIndex(idx)
        self.plugin_combo.blockSignals(False)
        self.settings.set(Keys.REPLAY_PLUGIN,
                          self.plugin_combo.currentData() or "")

    def _chart_handles(self) -> list:
        return [ChartHandle(w) for w in self.menu._live_windows()
                if isinstance(w, (FootprintWindow, OhlcvWindow))]

    def _run_plugin(self, load_first=None) -> None:
        path = self.plugin_combo.currentData()
        if not path:
            self.status_label.setText("No plugin selected")
            return
        path = Path(path)
        src = self._current_source_row()
        if src is None or self._trade_set is None:
            self.status_label.setText("No trade selected")
            return
        if load_first is None:
            load_first = self.chk_loadfirst.isChecked()
        if load_first:
            self._plugin_loading = True
            try:
                self._load_to_charts()
            finally:
                self._plugin_loading = False
        ctx = PluginContext(
            trade=self._trade_set.df.iloc[src],
            notes=self._trade_set.notes[src],
            charts=self._chart_handles(),
            params=parse_params(self.params_edit.toPlainText()),
        )
        name = path.stem
        try:
            run_plugin(path, ctx)
        except Exception:
            self._append_output(name, [traceback.format_exc().rstrip()])
            self.status_label.setText(f"{name}: ERROR — see plugin output")
            return
        if ctx.lines:
            self._append_output(name, ctx.lines)
            self.status_label.setText(ctx.lines[-1])
        else:
            self.status_label.setText(f"{name}: done")

    def _append_output(self, name: str, lines: list) -> None:
        stamp = pd.Timestamp.now().strftime("%H:%M:%S")
        self.output_text.appendPlainText(f"── {name}  {stamp} ──")
        for line in lines:
            self.output_text.appendPlainText(line)
        self.output_text.appendPlainText("")
        sb = self.output_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_plugin_drawings(self) -> None:
        for handle in self._chart_handles():
            try:
                handle.canvas.clear_annotations()
            except RuntimeError:
                continue
        self.status_label.setText("Annotations cleared")

    # ── load to charts ─────────────────────────────────────────────────
    def _load_to_charts(self) -> None:
        src = self._current_source_row()
        if src is None or self._trade_set is None:
            self.status_label.setText("No trade selected")
            return
        trade = self._trade_set.df.iloc[src]
        self._remove_auto_positions()
        # annotations are per-trade decorations — start each load clean
        for handle in self._chart_handles():
            try:
                handle.canvas.clear_annotations()
            except RuntimeError:
                continue

        windows = self.menu._live_windows()
        if not windows:
            self.status_label.setText(
                "No open charts — open a chart from the menu first")
            return
        date = str(trade["date"])
        drawn = date_only = skipped = failed = 0
        clamped = False
        for w in windows:
            try:
                w.set_date(date)
            except Exception:
                failed += 1
                continue
            if not isinstance(w, (FootprintWindow, OhlcvWindow)):
                date_only += 1
                continue
            result = self._draw_trade_on(w, trade)
            if result == "skipped":
                skipped += 1
            else:
                drawn += 1
                clamped = clamped or result == "clamped"

        parts = []
        if drawn:
            parts.append(f"trade drawn on {drawn} chart{'s' if drawn != 1 else ''}")
        if date_only:
            parts.append(f"date set on {date_only} more")
        if skipped:
            parts.append(f"{skipped} skipped (trade outside loaded data)")
        if failed:
            parts.append(f"{failed} failed")
        if clamped:
            parts.append("entry/exit clamped to loaded range")
        self.status_label.setText(f"{date}:  " + ", ".join(parts))

        # auto-run the selected plugin for the freshly loaded trade/day
        if (not getattr(self, "_plugin_loading", False)
                and self.chk_autorun.isChecked()
                and self.plugin_combo.currentData()):
            self._run_plugin(load_first=False)

    def _remove_auto_positions(self) -> None:
        for wref, pos in self._auto_positions:
            w = wref()
            if w is None:
                continue
            try:
                w.canvas.positions[:] = [p for p in w.canvas.positions
                                         if p is not pos]
                w.canvas.update()
            except RuntimeError:
                continue
        self._auto_positions.clear()

    def _draw_trade_on(self, window, trade) -> str:
        """Append the trade as a position drawing. 'drawn'|'clamped'|'skipped'."""
        canvas = window.canvas
        d = canvas.data
        if d is None or not len(d):
            return "skipped"
        t = times_ns_of(d)
        e_ns = int(pd.Timestamp(trade["entry_time"]).value)
        x_ns = int(pd.Timestamp(trade["exit_time"]).value)
        if x_ns < t[0] or e_ns > t[-1]:
            return "skipped"
        idx1 = int(np.clip(np.searchsorted(t, e_ns, side="right") - 1, 0, len(t) - 1))
        idx2 = int(np.clip(np.searchsorted(t, x_ns, side="right") - 1, idx1, len(t) - 1))

        entry = float(trade["entry_price"])
        tick = canvas.tick_size or 0.25
        direction = str(trade["direction"])
        up = 1.0 if direction == "long" else -1.0

        def price_or(col, fallback):
            v = trade.get(col)
            return float(v) if v is not None and not pd.isna(v) else fallback

        tp = price_or("tp", entry + up * tick)
        sl = price_or("sl", entry - up * tick)

        pos = {"dir": direction, "idx1": idx1, "idx2": idx2,
               "entry": entry, "tp": tp, "sl": sl}
        canvas.positions.append(pos)
        canvas.update()
        self._auto_positions.append((weakref.ref(window), pos))
        return "clamped" if (e_ns < t[0] or x_ns > t[-1]) else "drawn"
