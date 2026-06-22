"""Resolved selection handed to a heatmap chart window when it opens."""
import os
from dataclasses import dataclass


@dataclass
class HeatmapConfig:
    root: str
    type_folder: str
    asset: str
    dataset: str            # "" = none selected
    date: str               # anchor date YYYY-MM-DD
    days_back: int
    time_start: str         # HH:mm
    time_end: str           # HH:mm
    # kept for dataclass parity with the other charts; the heatmap is always
    # rendered at 1-second native resolution (the book cannot be resampled).
    tf_value: int = 1
    tf_unit: str = "Seconds"

    def has_dataset(self) -> bool:
        return bool(self.dataset)

    def dataset_path(self) -> str:
        return os.path.join(self.root, self.type_folder, self.asset, self.dataset)

    def timeframe_str(self) -> str:
        return "1 Second"
