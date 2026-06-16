"""Footprint chart display settings, persisted via QSettings.

OrderFootprintSettings  -> the "orders" footprint (per-level buy/sell imbalance).
PassiveOrderSettings    -> resting bid/ask liquidity coloring.
"""
from dataclasses import dataclass

from PyQt6.QtCore import QSettings

_ORG, _APP = "QuantChart", "QuantChartApp"


@dataclass
class OrderFootprintSettings:
    # imbalance ratio (dominant / other) where tinting begins
    gradient_start_ratio: float = 1.0
    # ratio at which the cell reaches full green/purple saturation
    gradient_full_ratio: float = 4.0
    # ratio at/above which a cell gets the highlight border
    highlight_ratio: float = 3.0
    show_highlight: bool = True

    @classmethod
    def load(cls) -> "OrderFootprintSettings":
        s = QSettings(_ORG, _APP)
        return cls(
            gradient_start_ratio=float(s.value("fp_orders/grad_start", 1.0)),
            gradient_full_ratio=float(s.value("fp_orders/grad_full", 4.0)),
            highlight_ratio=float(s.value("fp_orders/highlight", 3.0)),
            show_highlight=s.value("fp_orders/show_highlight", True, type=bool),
        )

    def save(self) -> None:
        s = QSettings(_ORG, _APP)
        s.setValue("fp_orders/grad_start", self.gradient_start_ratio)
        s.setValue("fp_orders/grad_full", self.gradient_full_ratio)
        s.setValue("fp_orders/highlight", self.highlight_ratio)
        s.setValue("fp_orders/show_highlight", self.show_highlight)
        s.sync()


@dataclass
class PassiveOrderSettings:
    # resting size at which the cell reaches full green/purple saturation
    gradient_full_size: float = 200.0
    # size at/above which a cell gets the highlight border
    highlight_size: float = 100.0
    show_highlight: bool = True

    @classmethod
    def load(cls) -> "PassiveOrderSettings":
        s = QSettings(_ORG, _APP)
        return cls(
            gradient_full_size=float(s.value("fp_passive/grad_full", 200.0)),
            highlight_size=float(s.value("fp_passive/highlight", 100.0)),
            show_highlight=s.value("fp_passive/show_highlight", True, type=bool),
        )

    def save(self) -> None:
        s = QSettings(_ORG, _APP)
        s.setValue("fp_passive/grad_full", self.gradient_full_size)
        s.setValue("fp_passive/highlight", self.highlight_size)
        s.setValue("fp_passive/show_highlight", self.show_highlight)
        s.sync()


@dataclass
class VolumeFootprintSettings:
    # imbalance ratio (dominant / other) where tinting begins
    gradient_start_ratio: float = 1.0
    # ratio at which the bar reaches full green/purple saturation
    gradient_full_ratio: float = 4.0
    # draw the per-level delta number on each bar
    show_delta: bool = True

    @classmethod
    def load(cls) -> "VolumeFootprintSettings":
        s = QSettings(_ORG, _APP)
        return cls(
            gradient_start_ratio=float(s.value("fp_volume/grad_start", 1.0)),
            gradient_full_ratio=float(s.value("fp_volume/grad_full", 4.0)),
            show_delta=s.value("fp_volume/show_delta", True, type=bool),
        )

    def save(self) -> None:
        s = QSettings(_ORG, _APP)
        s.setValue("fp_volume/grad_start", self.gradient_start_ratio)
        s.setValue("fp_volume/grad_full", self.gradient_full_ratio)
        s.setValue("fp_volume/show_delta", self.show_delta)
        s.sync()


@dataclass
class BigTradeSettings:
    min_bubble_px: float = 4.0      # radius at the session min-contract threshold
    max_bubble_px: float = 26.0     # radius at/above max_contracts
    max_contracts: float = 200.0    # size at/above which a bubble is max_bubble_px
    eth_min_contracts: float = 0.0  # keep ETH trades with size >= this
    rth_min_contracts: float = 0.0  # keep RTH trades with size >= this
    days_back: int = 1              # how many days of trades to load

    @classmethod
    def load(cls) -> "BigTradeSettings":
        s = QSettings(_ORG, _APP)
        return cls(
            min_bubble_px=float(s.value("big_trades/min_px", 4.0)),
            max_bubble_px=float(s.value("big_trades/max_px", 26.0)),
            max_contracts=float(s.value("big_trades/max_contracts", 200.0)),
            eth_min_contracts=float(s.value("big_trades/eth_min", 0.0)),
            rth_min_contracts=float(s.value("big_trades/rth_min", 0.0)),
            days_back=int(s.value("big_trades/days_back", 1)),
        )

    def save(self) -> None:
        s = QSettings(_ORG, _APP)
        s.setValue("big_trades/min_px", self.min_bubble_px)
        s.setValue("big_trades/max_px", self.max_bubble_px)
        s.setValue("big_trades/max_contracts", self.max_contracts)
        s.setValue("big_trades/eth_min", self.eth_min_contracts)
        s.setValue("big_trades/rth_min", self.rth_min_contracts)
        s.setValue("big_trades/days_back", self.days_back)
        s.sync()


def _hhmm_to_min(hhmm: str) -> int:
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


@dataclass
class GeneralSettings:
    """Chart-wide settings shared across features."""
    rth_start: str = "09:30"   # RTH session start (inclusive), NY
    rth_end: str = "16:00"     # RTH session end (exclusive), NY

    def rth_start_min(self) -> int:
        return _hhmm_to_min(self.rth_start)

    def rth_end_min(self) -> int:
        return _hhmm_to_min(self.rth_end)

    @classmethod
    def load(cls) -> "GeneralSettings":
        s = QSettings(_ORG, _APP)
        return cls(
            rth_start=str(s.value("general/rth_start", "09:30")),
            rth_end=str(s.value("general/rth_end", "16:00")),
        )

    def save(self) -> None:
        s = QSettings(_ORG, _APP)
        s.setValue("general/rth_start", self.rth_start)
        s.setValue("general/rth_end", self.rth_end)
        s.sync()


@dataclass
class VolumeProfileSettings:
    rth_minutes: int = 30          # RTH VP spans this many minutes from RTH start
    composite_days: int = 5        # day-files (incl. current) the composite aggregates
    composite_end: str = "09:30"   # composite stops here on the LAST day (exclusive)
    vol_width: int = 80            # max width (px) of profile volume bars
    delta_width: int = 80          # max width (px) of profile delta bars
    composite_width: int = 150     # max width (px) of the right-side composite bars

    def composite_end_min(self) -> int:
        return _hhmm_to_min(self.composite_end)

    @classmethod
    def load(cls) -> "VolumeProfileSettings":
        s = QSettings(_ORG, _APP)
        return cls(
            rth_minutes=int(s.value("vp/rth_minutes", 30)),
            composite_days=int(s.value("vp/composite_days", 5)),
            composite_end=str(s.value("vp/composite_end", "09:30")),
            vol_width=int(s.value("vp/vol_width", 80)),
            delta_width=int(s.value("vp/delta_width", 80)),
            composite_width=int(s.value("vp/composite_width", 150)),
        )

    def save(self) -> None:
        s = QSettings(_ORG, _APP)
        s.setValue("vp/rth_minutes", self.rth_minutes)
        s.setValue("vp/composite_days", self.composite_days)
        s.setValue("vp/composite_end", self.composite_end)
        s.setValue("vp/vol_width", self.vol_width)
        s.setValue("vp/delta_width", self.delta_width)
        s.setValue("vp/composite_width", self.composite_width)
        s.sync()
