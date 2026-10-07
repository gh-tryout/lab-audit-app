"""Load quality-norm clause items from a local Excel workbook (no header row)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re

import pandas as pd

from app_paths import data_dir, ensure_bundled_excels

ensure_bundled_excels()
ROOT = data_dir()
DEFAULT_EXCEL = "17025.xlsx"
DEFAULT_NORM = DEFAULT_EXCEL
EXCEL_PATH = ROOT / DEFAULT_EXCEL


def list_excel_bestanden() -> list[str]:
    return [
        pad.name
        for pad in sorted(ROOT.glob("*.xlsx"), key=lambda item: item.name.lower())
        if not pad.name.startswith("~$")
    ]


def default_excel_naam(bestanden: list[str] | None = None) -> str:
    bestanden = list_excel_bestanden() if bestanden is None else bestanden
    if DEFAULT_EXCEL in bestanden:
        return DEFAULT_EXCEL
    return bestanden[0] if bestanden else DEFAULT_EXCEL


def excel_path_for(norm: str) -> Path:
    naam = Path(str(norm or "")).name
    bestanden = list_excel_bestanden()
    if naam in bestanden:
        return ROOT / naam
    if naam.lower() == "iso 17025" or str(norm).strip() == "ISO 17025":
        return ROOT / default_excel_naam(bestanden)
    stam = Path(naam).stem
    for bestand in bestanden:
        if Path(bestand).stem == stam:
            return ROOT / bestand
    return ROOT / default_excel_naam(bestanden)


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def _display_title(paragraaf_nr: str, niveau_titel: str) -> str:
    titel = niveau_titel
    if paragraaf_nr and titel.startswith(paragraaf_nr):
        titel = titel[len(paragraaf_nr) :].strip(" -–—")
    else:
        titel = re.sub(r"^\d+(?:\.\d+)*\s+", "", titel).strip(" -–—")
    label = f"§{paragraaf_nr}" if paragraaf_nr else "§"
    if titel and titel.lower() != "algemeen":
        return f"{label} — {titel}"
    return label


def load_norm_items(path: Path | None = None) -> list[dict[str, str]]:
    workbook = path or EXCEL_PATH
    df = pd.read_excel(workbook, header=None)

    items: list[dict[str, str]] = []
    for excel_index, row in df.iterrows():
        sub = _clean(row.iloc[1] if len(row) > 1 else "")
        titel = _clean(row.iloc[2] if len(row) > 2 else "")
        tekst = _clean(row.iloc[5] if len(row) > 5 else "")
        par_nr = _clean(row.iloc[6] if len(row) > 6 else "")
        hoofdstuk = _clean(row.iloc[0] if len(row) > 0 else "")

        if not sub or not par_nr:
            continue

        items.append(
            {
                "hoofdstuk": hoofdstuk,
                "sub_hoofdstuk": sub,
                "paragraaf_id": par_nr or f"row-{excel_index}",
                "niveau_titel": titel,
                "weergave_titel": _display_title(par_nr, titel),
                "tekst": tekst,
                "volgorde": str(excel_index),
            }
        )
    return items


def unique_subchapters(items: list[dict[str, str]]) -> list[str]:
    seen: list[str] = []
    for item in items:
        name = item["sub_hoofdstuk"]
        if name and name not in seen:
            seen.append(name)
    return seen
