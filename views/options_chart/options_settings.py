"""Options exposure chart settings, persisted via QSettings."""
from dataclasses import dataclass
from PyQt6.QtCore import QSettings

_ORG, _APP = "QuantChart", "QuantChartApp"


@dataclass
class OptionsSettings:
    risk_free_rate: float = 4.0     # percent, used to discount premiums in the IV solve
    quote_lookback_files: int = 3   # previous day files searched for missing bid/ask (0 = off)
    playback_ms: int = 300          # autoplay step interval
    dim_factor: float = 0.45        # alpha multiplier for estimated-OI fallback bar segments

    def r(self) -> float:
        return self.risk_free_rate / 100.0

    @classmethod
    def load(cls) -> "OptionsSettings":
        s = QSettings(_ORG, _APP)
        return cls(
            risk_free_rate=float(s.value("options/risk_free_rate", 4.0)),
            quote_lookback_files=int(s.value("options/quote_lookback_files", 3)),
            playback_ms=int(s.value("options/playback_ms", 300)),
            dim_factor=float(s.value("options/dim_factor", 0.45)),
        )

    def save(self) -> None:
        s = QSettings(_ORG, _APP)
        s.setValue("options/risk_free_rate", self.risk_free_rate)
        s.setValue("options/quote_lookback_files", self.quote_lookback_files)
        s.setValue("options/playback_ms", self.playback_ms)
        s.setValue("options/dim_factor", self.dim_factor)
        s.sync()
