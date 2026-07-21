"""Resolved selection handed to an options exposure chart window when it opens."""
import os
from dataclasses import dataclass


@dataclass
class OptionsConfig:
    root: str
    type_folder: str          # options type folder, e.g. "Options_on_futures"
    asset: str
    dataset: str              # options 5m dataset, "" = none selected
    futures_type_folder: str  # e.g. "Futures"
    futures_dataset: str      # OHLCV dataset supplying the underlying price
    date: str                 # anchor date YYYY-MM-DD

    def has_dataset(self) -> bool:
        return bool(self.dataset)

    def dataset_path(self) -> str:
        return os.path.join(self.root, self.type_folder, self.asset, self.dataset)

    def has_futures(self) -> bool:
        return bool(self.futures_dataset)

    def futures_path(self) -> str:
        return os.path.join(self.root, self.futures_type_folder, self.asset, self.futures_dataset)
