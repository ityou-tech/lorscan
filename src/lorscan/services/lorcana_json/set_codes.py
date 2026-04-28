"""Translate LorcanaJSON's numeric `setCode` to lorscan's 3-letter codes.

LorcanaJSON labels sets numerically as printed on the card ("1" for The
First Chapter, "Q1" for Illumineer's Quest, etc.). lorscan has used
3-letter friendly codes since launch; collection rows reference those
codes via the composite `card_id`. Update this map (and the README's
set-codes table) whenever a new Lorcana set drops.
"""

from __future__ import annotations

LORCANA_JSON_SET_CODE_MAP: dict[str, str] = {
    "1":  "TFC",   # The First Chapter         (Aug 2023)
    "2":  "ROF",   # Rise of the Floodborn     (Nov 2023)
    "3":  "ITI",   # Into the Inklands         (Feb 2024)
    "4":  "URS",   # Ursula's Return           (May 2024)
    "5":  "SSK",   # Shimmering Skies          (Aug 2024)
    "6":  "AZS",   # Azurite Sea               (Nov 2024)
    "7":  "ARI",   # Archazia's Island         (Feb 2025)
    "8":  "ROJ",   # Reign of Jafar            (May 2025)
    "9":  "FAB",   # Fabled                    (Aug 2025)
    "10": "WHI",   # Whispers in the Well      (Nov 2025)
    "11": "WIN",   # Winterspell               (Feb 2026)
    "12": "WUN",   # Wilds Unknown             (May 2026)
    # 13/14 are upstream placeholders — 0 cards as of 2026-04. Codes are
    # provisional; update once cards drop and the official 3-letter code
    # is known. The empty rows are harmless because _build_binders skips
    # sets without cards.
    "13": "AOV",   # Attack of the Vine        (placeholder)
    "14": "HYC",   # Hyperia City              (placeholder)
}


def to_lorscan_set_code(numeric: str) -> str:
    """Map LorcanaJSON's numeric set code to lorscan's 3-letter code.

    Illumineer's Quest codes ("Q1" etc.) pass through unchanged because
    they are already in lorscan's friendly form.

    Raises KeyError if `numeric` isn't a known set; callers should log
    and skip the card so an unknown set doesn't take down the whole sync.
    """
    if numeric.startswith("Q"):
        return numeric
    return LORCANA_JSON_SET_CODE_MAP[numeric]
