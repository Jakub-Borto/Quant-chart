"""Persistent app settings.

Backed by QSettings, which writes to the Windows registry (or plist on Mac).
No config file to manage by hand. Values survive app restarts.
"""
from PyQt6.QtCore import QSettings


class Keys:
    """Centralised settings keys so they aren't scattered as raw strings."""
    ROOT = "data/root"
    FUTURES = "data/futures_folder"
    OPTIONS = "data/options_folder"
    ASSET = "data/asset"
    DATE = "data/date"             # stored as "yyyy-MM-dd"
    TIME_START = "data/time_start"  # stored as "HH:mm"
    TIME_END = "data/time_end"      # stored as "HH:mm"


class AppSettings:
    def __init__(self) -> None:
        self._s = QSettings("QuantChart", "QuantChartApp")

    def get(self, key: str, default="", type_=str):
        return self._s.value(key, default, type=type_)

    def set(self, key: str, value) -> None:
        self._s.setValue(key, value)
        self._s.sync()
