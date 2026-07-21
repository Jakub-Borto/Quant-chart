"""Table model + filter proxy for the trades table (notes column excluded)."""
import math

import numpy as np
import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QColor

from core.styles import PALETTE

HEADER_NAMES = {
    "date": "Date", "direction": "Dir", "trade_type": "Trade Type",
    "entry_time": "Entry", "exit_time": "Exit",
    "entry_price": "Entry Px", "exit_price": "Exit Px",
    "sl": "SL", "tp": "TP", "sl_ticks": "SL Ticks", "tp_ticks": "TP Ticks",
    "rr": "RR", "ticks": "Ticks", "cumulative_ticks": "Cum Ticks",
    "duration_min": "Duration", "exit_reason": "Exit Reason",
    "pnl_points": "PnL Pts",
}

_SIGN_COLS = {"ticks", "pnl_points", "cumulative_ticks"}


def header_name(col: str) -> str:
    return HEADER_NAMES.get(col, col.replace("_", " ").title())


def format_duration(minutes: float) -> str:
    if minutes is None or (isinstance(minutes, float) and math.isnan(minutes)):
        return "—"
    m = int(round(minutes))
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def format_value(col: str, value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if col == "duration_min":
        return format_duration(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%H:%M")
    if isinstance(value, (float, np.floating)):
        return f"{value:g}" if float(value).is_integer() else f"{value:.2f}"
    return str(value)


class TradesTableModel(QAbstractTableModel):
    def __init__(self, trade_set, parent=None) -> None:
        super().__init__(parent)
        self.trade_set = trade_set
        self.cols = trade_set.table_cols
        self._green = QColor(PALETTE["SUCCESS"])
        self._red = QColor(PALETTE["DANGER"])

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.trade_set)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.cols)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return header_name(self.cols[section])
        return str(section + 1)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        col = self.cols[index.column()]
        value = self.trade_set.df.iloc[index.row(), self.trade_set.df.columns.get_loc(col)]

        if role == Qt.ItemDataRole.DisplayRole:
            return format_value(col, value)

        if role == Qt.ItemDataRole.UserRole:      # raw, for sorting
            if isinstance(value, pd.Timestamp):
                return float(value.value)
            if isinstance(value, (int, float, np.integer, np.floating)):
                return float(value)
            return str(value)

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == "direction":
                return self._green if value == "long" else self._red
            if col in _SIGN_COLS and isinstance(value, (int, float, np.integer, np.floating)):
                if not (isinstance(value, float) and math.isnan(value)):
                    return self._green if value >= 0 else self._red
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole:
            kind = self.trade_set.column_kind(col)
            if kind == "numeric":
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        return None


class TradesFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.mask = None
        self.setSortRole(Qt.ItemDataRole.UserRole)

    def set_mask(self, mask) -> None:
        self.mask = mask
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        return self.mask is None or bool(self.mask[source_row])

    def lessThan(self, left, right) -> bool:
        a = self.sourceModel().data(left, Qt.ItemDataRole.UserRole)
        b = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)
        if isinstance(a, float) and isinstance(b, float):
            # NaNs always sort last regardless of direction
            if math.isnan(a):
                return False
            if math.isnan(b):
                return True
            return a < b
        return str(a) < str(b)
