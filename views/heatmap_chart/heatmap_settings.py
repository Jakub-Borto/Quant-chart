"""Heatmap chart display settings, persisted via QSettings.

All settings are read live on every paint, so changing one + repaint updates
the chart without reloading data.
"""
from dataclasses import dataclass
from PyQt6.QtCore import QSettings

_ORG, _APP = "QuantChart", "QuantChartApp"


@dataclass
class HeatmapSettings:
    # Overall gamma applied to normalized size -> color intensity.
    # >1 brightens small resting orders, <1 darkens them.
    contrast: float = 1.0
    # Extra boost applied to the high end of the range (the "high contrast"
    # slider) — pushes large orders toward the hot end of the colormap.
    high_contrast: float = 1.0
    # Resting quantity mapped to full (hottest) color. 0 = auto from data.
    max_ref: float = 0.0
    # Half-window in ticks around the touch to parse/draw per second.
    crop_ticks: int = 256
    # Show the per-price quantity ladder on the right edge.
    show_dom_panel: bool = True
    # Anchor for the initial view: open zoomed to the RTH session open.
    rth_start: str = "09:30"

    def rth_start_min(self) -> int:
        try:
            h, m = str(self.rth_start).split(":")
            return int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            return 9 * 60 + 30

    @classmethod
    def load(cls) -> "HeatmapSettings":
        s = QSettings(_ORG, _APP)
        return cls(
            contrast=float(s.value("heatmap/contrast", 1.0)),
            high_contrast=float(s.value("heatmap/high_contrast", 1.0)),
            max_ref=float(s.value("heatmap/max_ref", 0.0)),
            crop_ticks=int(s.value("heatmap/crop_ticks", 256)),
            show_dom_panel=s.value("heatmap/show_dom_panel", True, type=bool),
            rth_start=str(s.value("heatmap/rth_start", "09:30")),
        )

    def save(self) -> None:
        s = QSettings(_ORG, _APP)
        s.setValue("heatmap/contrast", self.contrast)
        s.setValue("heatmap/high_contrast", self.high_contrast)
        s.setValue("heatmap/max_ref", self.max_ref)
        s.setValue("heatmap/crop_ticks", self.crop_ticks)
        s.setValue("heatmap/show_dom_panel", self.show_dom_panel)
        s.setValue("heatmap/rth_start", self.rth_start)
        s.sync()
