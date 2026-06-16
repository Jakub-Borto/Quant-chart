"""Filesystem helpers.

All chart selection is driven by folder names on disk:

    root / type_folder / asset / dataset / YYYY-MM-DD.parquet

These helpers list each level. Every function fails soft: a missing or
invalid path returns an empty list rather than raising.
"""
import os
from typing import List


def _list_subdirs(path: str) -> List[str]:
    if not path or not os.path.isdir(path):
        return []
    return sorted(
        d for d in os.listdir(path)
        if os.path.isdir(os.path.join(path, d))
    )


def list_type_folders(root: str) -> List[str]:
    """Subfolders directly under the root (e.g. Futures, Options_on_futures)."""
    return _list_subdirs(root)


def list_assets(root: str, type_folder: str) -> List[str]:
    """Asset folders (e.g. ES, NQ, GC) under root/type_folder."""
    return _list_subdirs(os.path.join(root, type_folder))


def list_datasets(root: str, type_folder: str, asset: str) -> List[str]:
    """Dataset folders (e.g. ES_1m_advanced) under root/type_folder/asset."""
    return _list_subdirs(os.path.join(root, type_folder, asset))


def list_dates(root: str, type_folder: str, asset: str, dataset: str) -> List[str]:
    """Available dates, newest first, derived from .parquet filenames.

    A file '2024-01-15.parquet' becomes the date string '2024-01-15'.
    """
    path = os.path.join(root, type_folder, asset, dataset)
    if not os.path.isdir(path):
        return []
    dates = [
        f[:-len(".parquet")]
        for f in os.listdir(path)
        if f.endswith(".parquet")
    ]
    return sorted(dates, reverse=True)
