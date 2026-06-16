"""Resolved selection handed to an OHLCV chart window when it opens."""
import os
from dataclasses import dataclass


@dataclass
class OhlcvConfig:
    root: str
    type_folder: str
    asset: str
    dataset: str            # "" = none selected
    date: str               # anchor date YYYY-MM-DD
    days_back: int
    time_start: str         # HH:mm
    time_end: str           # HH:mm
    tf_value: int = 1
    tf_unit: str = "Minutes"
    indicators_dataset: str = ""

    def has_dataset(self) -> bool:
        return bool(self.dataset)

    def dataset_path(self) -> str:
        return os.path.join(self.root, self.type_folder, self.asset, self.dataset)

    def has_indicators(self) -> bool:
        return bool(self.indicators_dataset)

    def indicators_path(self):
        if not self.indicators_dataset:
            return None
        return os.path.join(self.root, self.type_folder, self.asset, self.indicators_dataset)

    def timeframe_str(self) -> str:
        return f"{self.tf_value} {self.tf_unit}"
