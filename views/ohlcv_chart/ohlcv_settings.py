"""OHLCV chart display settings, persisted via QSettings."""
from dataclasses import dataclass
from PyQt6.QtCore import QSettings

_ORG, _APP = "QuantChart", "QuantChartApp"


def _hhmm_to_min(hhmm: str) -> int:
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


@dataclass
class OhlcvGeneralSettings:
    rth_start: str = "09:30"
    rth_end: str = "16:00"

    def rth_start_min(self) -> int:
        return _hhmm_to_min(self.rth_start)

    def rth_end_min(self) -> int:
        return _hhmm_to_min(self.rth_end)

    @classmethod
    def load(cls) -> "OhlcvGeneralSettings":
        s = QSettings(_ORG, _APP)
        return cls(
            rth_start=str(s.value("ohlcv_general/rth_start", "09:30")),
            rth_end=str(s.value("ohlcv_general/rth_end", "16:00")),
        )

    def save(self) -> None:
        s = QSettings(_ORG, _APP)
        s.setValue("ohlcv_general/rth_start", self.rth_start)
        s.setValue("ohlcv_general/rth_end", self.rth_end)
        s.sync()
