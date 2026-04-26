"""Strict marketplace-listing → catalog card_id resolver.

Future shops (eBay etc.) with messier listings will need fuzzy matching;
that logic slots in behind this same function signature without changing
the adapter or storage layers.
"""

from __future__ import annotations

from lorscan.services.marketplaces.base import Listing
from lorscan.storage.db import Database


def resolve_listing(
    db: Database,
    *,
    set_code: str,
    listing: Listing,
) -> str | None:
    """Return the catalog card_id for a listing, or None if no strict match."""
    if listing.collector_number is None:
        return None
    card = db.get_card_by_collector_number(set_code, listing.collector_number)
    return card.card_id if card else None
