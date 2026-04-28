"""Lorcana set release-order helpers.

The catalog API doesn't expose `released_on`, so we keep the canonical
sequence as a code-side constant of stable Disney facts. Used by both
the scan upload form (set selector) and the /collection page (per-set
completion list) so they show sets in the same order users expect.

Adding a new chapter is a one-line append to LORCANA_RELEASE_ORDER.
"""

from __future__ import annotations

LORCANA_RELEASE_ORDER: tuple[str, ...] = (
    "TFC",  # 1.  The First Chapter
    "ROF",  # 2.  Rise of the Floodborn
    "ITI",  # 3.  Into the Inklands
    "URS",  # 4.  Ursula's Return
    "SSK",  # 5.  Shimmering Skies
    "AZS",  # 6.  Azurite Sea
    "ARI",  # 7.  Archazia's Island
    "ROJ",  # 8.  Reign of Jafar
    "FAB",  # 9.  Fabled
    "WHI",  # 10. Whispers in the Well
    "WIN",  # 11. Winterspell
    "WUN",  # 12. Wilds Unknown
    "AOV",  # 13. Attack of the Vine    (placeholder — 0 cards in upstream)
    "HYC",  # 14. Hyperia City          (placeholder — 0 cards in upstream)
)


def release_sort_key(set_code: str) -> tuple[int, int, str]:
    """Sort key placing main sets first in release order, then anything
    else (supplementary/promo sets) alphabetically below them."""
    try:
        idx = LORCANA_RELEASE_ORDER.index(set_code)
        return (0, idx, "")
    except ValueError:
        return (1, 0, set_code)


def release_index(set_code: str) -> int | None:
    """1-based chapter number for main sets; None for supplementary."""
    try:
        return LORCANA_RELEASE_ORDER.index(set_code) + 1
    except ValueError:
        return None


__all__ = ["LORCANA_RELEASE_ORDER", "release_index", "release_sort_key"]
