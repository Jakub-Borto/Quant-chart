"""Shared timeframe selector for chart toolbars.

Two combos: a value combo (popular values + "Custom…" which prompts for any
integer) and a unit combo (m/h/d/w/mo/y mapping to the resampler's unit names).
"""
from PyQt6.QtWidgets import QComboBox, QInputDialog

TF_VALUES = [1, 4, 5, 15, 30]
TF_UNITS = [
    ("m",  "Minutes"),
    ("h",  "Hours"),
    ("d",  "Days"),
    ("w",  "Weeks"),
    ("mo", "Months"),
    ("y",  "Years"),
]
_CUSTOM = "Custom…"


class TimeframeSelector:
    """Owns the two combos; calls on_change(value, unit) on user selection."""

    def __init__(self, config, on_change) -> None:
        self.config = config
        self.on_change = on_change

        self.value_combo = QComboBox()
        for v in TF_VALUES:
            self.value_combo.addItem(str(v), v)
        self.value_combo.addItem(_CUSTOM, None)
        self.value_combo.setFixedWidth(72)
        self.value_combo.setToolTip("Timeframe value")

        self.unit_combo = QComboBox()
        for label, unit in TF_UNITS:
            self.unit_combo.addItem(label, unit)
        self.unit_combo.setFixedWidth(52)
        self.unit_combo.setToolTip("Timeframe unit")

        self._select_value(config.tf_value)
        unit_idx = next((i for i, (_, u) in enumerate(TF_UNITS)
                         if u == config.tf_unit), 0)
        self.unit_combo.setCurrentIndex(unit_idx)

        # `activated` fires only on user picks (not programmatic changes)
        self.value_combo.activated.connect(self._on_value)
        self.unit_combo.activated.connect(lambda _i: self._emit())

    # ------------------------------------------------------------------
    def _select_value(self, value: int) -> None:
        for i in range(self.value_combo.count()):
            if self.value_combo.itemData(i) == value:
                self.value_combo.setCurrentIndex(i)
                return
        # non-preset value: insert just before "Custom…"
        pos = self.value_combo.count() - 1
        self.value_combo.insertItem(pos, str(value), value)
        self.value_combo.setCurrentIndex(pos)

    def _on_value(self, index: int) -> None:
        if self.value_combo.itemData(index) is None:   # "Custom…"
            value, ok = QInputDialog.getInt(
                self.value_combo, "Custom timeframe", "Timeframe value:",
                self.config.tf_value, 1, 999)
            self._select_value(value if ok else self.config.tf_value)
            if not ok:
                return
        self._emit()

    def _emit(self) -> None:
        self.on_change(self.value_combo.currentData(),
                       self.unit_combo.currentData())
