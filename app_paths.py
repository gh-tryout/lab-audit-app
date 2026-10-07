"""Writable app folder (next to the exe) vs bundled resources."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def bundle_dir() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ensure_bundled_excels() -> None:
    bestemming = data_dir()
    bestemming.mkdir(parents=True, exist_ok=True)
    for bron in bundle_dir().glob("*.xlsx"):
        if bron.name.startswith("~$"):
            continue
        doel = bestemming / bron.name
        if not doel.exists():
            shutil.copy2(bron, doel)
