"""Marketplace-listing → catalog card_id resolver.

Strategy is two-tiered:

1. Strict `(set_code, collector_number)` lookup — fast and unambiguous when
   the listing exposes a collector number.
2. Name-based fallback parsed from the listing title — needed because real
   shops (e.g. Bazaar) almost never include a `#NNN` collector number in
   their product titles. Conservative: only accepts a single unambiguous
   match so we under-match before we ever mis-match.

Future shops (eBay etc.) with messier listings will need fuzzier matching;
that logic slots in behind this same function signature without changing
the adapter or storage layers.
"""

from __future__ import annotations

import re

from lorscan.services.marketplaces.base import Listing
from lorscan.storage.db import Database

_FINISH_SUFFIXES = re.compile(
    r"\s*\((?:foil|cold foil|cold-foil|alternate art|altart|errata version|errata)\)$",
    re.IGNORECASE,
)


def _parse_title_to_name_subtitle(title: str) -> tuple[str, str | None]:
    """Strip finish/variant suffixes from a Bazaar title and split on ', '
    into (name, subtitle).

    Examples:
      "Yzma, Without Beauty Sleep (foil)" -> ("Yzma", "Without Beauty Sleep")
      "Zero to Hero (foil)"               -> ("Zero to Hero", None)
      "Bucky, Squirrel Squeak Tutor (errata version) (foil)" ->
        ("Bucky", "Squirrel Squeak Tutor")
    """
    cleaned = title
    # Strip up to 3 trailing parenthetical suffixes (handles "X (errata) (foil)").
    for _ in range(3):
        new = _FINISH_SUFFIXES.sub("", cleaned).strip()
        if new == cleaned:
            break
        cleaned = new
    if ", " in cleaned:
        head, _, tail = cleaned.partition(", ")
        return head.strip(), tail.strip() or None
    return cleaned.strip(), None


def resolve_listing(
    db: Database,
    *,
    set_code: str,
    listing: Listing,
) -> str | None:
    """Return the catalog card_id for a listing, or None if no match.

    Strategy:
      1. Strict: (set_code, collector_number) lookup if collector_number is set.
      2. Fallback: parse the title into (name, subtitle) and look up by name
         within set_code. Only accepts a single unambiguous match — if the
         search returns 0 or 2+ cards, we return None (no false matches).
    """
    # 1. Strict path.
    if listing.collector_number is not None:
        card = db.get_card_by_collector_number(set_code, listing.collector_number)
        if card is not None:
            return card.card_id

    # 2. Fallback: name match within set, using the parsed Bazaar title.
    name, subtitle = _parse_title_to_name_subtitle(listing.title)
    candidates = db.search_cards_by_name(name, set_code=set_code)
    if len(candidates) == 1:
        return candidates[0].card_id
    # If multiple cards share the name within the set, disambiguate by subtitle.
    if subtitle is not None:
        narrowed = [c for c in candidates if c.subtitle == subtitle]
        if len(narrowed) == 1:
            return narrowed[0].card_id
    return None
