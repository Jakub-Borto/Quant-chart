"""Heatmap chart display settings, persisted via QSettings.

Color settings are split per session (ETH overnight vs RTH day) because RTH
resting size is much larger than ETH; one global color scale washes ETH out.
Most settings are read live on every paint; the RTH window and crop ticks
affect the precomputed pyramid, so changing them rebuilds it.
"""
from dataclasses import dataclass
from PyQt6.QtCore import QSettings

_ORG, _APP = "QuantChart", "QuantChartApp"


def _hhmm_to_min(hhmm: str, default: int) -> int:
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return default


@dataclass
class HeatmapSettings:
    # ── General (global) ──────────────────────────────────────────────
    rth_start: str = "09:30"   # RTH session start (incl)
    rth_end: str = "16:00"     # RTH session end (excl)
    crop_ticks: int = 256      # half-window in ticks around the touch (grid extent)
    show_dom_panel: bool = True

    # ── RTH heatmap colors ────────────────────────────────────────────
    rth_contrast: float = 1.0
    rth_high_contrast: float = 1.0
    rth_max_ref: float = 0.0   # 0 = auto from data

    # ── ETH heatmap colors ────────────────────────────────────────────
    eth_contrast: float = 1.0
    eth_high_contrast: float = 1.0
    eth_max_ref: float = 0.0   # 0 = auto from data

    def rth_start_min(self) -> int:
        return _hhmm_to_min(self.rth_start, 9 * 60 + 30)

    def rth_end_min(self) -> int:
        return _hhmm_to_min(self.rth_end, 16 * 60)

    @classmethod
    def load(cls) -> "HeatmapSettings":
        s = QSettings(_ORG, _APP)
        f = lambda k, d: float(s.value(k, d))
        return cls(
            rth_start=str(s.value("heatmap/rth_start", "09:30")),
            rth_end=str(s.value("heatmap/rth_end", "16:00")),
            crop_ticks=int(s.value("heatmap/crop_ticks", 256)),
            show_dom_panel=s.value("heatmap/show_dom_panel", True, type=bool),
            rth_contrast=f("heatmap/rth_contrast", 1.0),
            rth_high_contrast=f("heatmap/rth_high_contrast", 1.0),
            rth_max_ref=f("heatmap/rth_max_ref", 0.0),
            eth_contrast=f("heatmap/eth_contrast", 1.0),
            eth_high_contrast=f("heatmap/eth_high_contrast", 1.0),
            eth_max_ref=f("heatmap/eth_max_ref", 0.0),
        )

    def save(self) -> None:
        s = QSettings(_ORG, _APP)
        s.setValue("heatmap/rth_start", self.rth_start)
        s.setValue("heatmap/rth_end", self.rth_end)
        s.setValue("heatmap/crop_ticks", self.crop_ticks)
        s.setValue("heatmap/show_dom_panel", self.show_dom_panel)
        s.setValue("heatmap/rth_contrast", self.rth_contrast)
        s.setValue("heatmap/rth_high_contrast", self.rth_high_contrast)
        s.setValue("heatmap/rth_max_ref", self.rth_max_ref)
        s.setValue("heatmap/eth_contrast", self.eth_contrast)
        s.setValue("heatmap/eth_high_contrast", self.eth_high_contrast)
        s.setValue("heatmap/eth_max_ref", self.eth_max_ref)
        s.sync()
