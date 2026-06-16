"""The resolved selection handed to a footprint chart window when it opens."""
import os
from dataclasses import dataclass


@dataclass
class FootprintConfig:
    root: str               # D:/Quant_app/data/parquet
    type_folder: str        # Futures  |  Options_on_futures
    asset: str              # ES
    dataset: str            # ES_1m_advanced  ("" = none selected)
    date: str               # 2024-01-15  (anchor date, from the menu)
    days_back: int          # how many days before the anchor to also load
    time_start: str         # HH:mm
    time_end: str           # HH:mm
    tf_value: int = 1
    tf_unit: str = "Minutes"
    indicators_dataset: str = ""   # "" = none
    big_trades_dataset: str = ""   # "" = none

    # ── candle dataset ────────────────────────────────────────────────
    def has_dataset(self) -> bool:
        return bool(self.dataset)

    def dataset_path(self) -> str:
        """Folder holding the day Parquet files for this selection."""
        return os.path.join(self.root, self.type_folder, self.asset, self.dataset)

    # ── indicators dataset ────────────────────────────────────────────
    def has_indicators(self) -> bool:
        return bool(self.indicators_dataset)

    def indicators_path(self):
        if not self.indicators_dataset:
            return None
        return os.path.join(self.root, self.type_folder, self.asset, self.indicators_dataset)

    # ── big trades dataset ────────────────────────────────────────────
    def has_big_trades(self) -> bool:
        return bool(self.big_trades_dataset)

    def big_trades_path(self):
        if not self.big_trades_dataset:
            return None
        return os.path.join(self.root, self.type_folder, self.asset, self.big_trades_dataset)

    def timeframe_str(self) -> str:
        """Human readable timeframe, e.g. '5 Minutes'."""
        return f"{self.tf_value} {self.tf_unit}"
