"""Translate LorcanaJSON's card schema to lorscan's CardRecord."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from lorscan.services.lorcana_json.set_codes import to_lorscan_set_code

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CardRecord:
    """The flattened shape lorscan stores in the `cards` table."""

    card_id: str
    set_code: str
    collector_number: str
    name: str
    full_name: str
    type: str | None
    rarity: str | None
    cost: int | None
    ink_color: str | None
    cardmarket_id: int | None
    cardmarket_url: str | None
    cardtrader_id: int | None
    cardtrader_url: str | None
    tcgplayer_id: int | None
    tcgplayer_url: str | None
    image_url: str | None


def map_lorcana_json_card(raw: dict[str, Any]) -> CardRecord:
    """Map ONE LorcanaJSON card dict to a CardRecord.

    Raises KeyError if the card's setCode is not in LORCANA_JSON_SET_CODE_MAP
    (callers should catch and skip).

    card_id format: `<SET>-<NNN>` with 3-digit zero-padding for purely
    numeric collector numbers (e.g. `TFC-001`, `TFC-127`, `ARI-205`). This
    matches the format the prior lorcana-api.com importer wrote, so existing
    `cards`, `collection_items`, and `marketplace_listings` rows continue
    to round-trip without a renaming migration. `collector_number` itself
    stays unpadded for display, matching the existing column convention.
    """
    numeric_set = str(raw["setCode"])
    set_code = to_lorscan_set_code(numeric_set)
    raw_number = raw["number"]
    collector_number = str(raw_number)
    card_id_number = f"{int(raw_number):03d}" if isinstance(raw_number, int) else collector_number
    card_id = f"{set_code}-{card_id_number}"

    external = raw.get("externalLinks") or {}
    images = raw.get("images") or {}
    image_url = images.get("full") or images.get("foilFull") or images.get("thumbnail")

    return CardRecord(
        card_id=card_id,
        set_code=set_code,
        collector_number=collector_number,
        name=raw.get("name", ""),
        full_name=raw.get("fullName", raw.get("name", "")),
        type=raw.get("type"),
        rarity=raw.get("rarity"),
        cost=raw.get("cost"),
        ink_color=raw.get("color"),
        cardmarket_id=external.get("cardmarketId"),
        cardmarket_url=external.get("cardmarketUrl"),
        cardtrader_id=external.get("cardTraderId"),
        cardtrader_url=external.get("cardTraderUrl"),
        tcgplayer_id=external.get("tcgPlayerId"),
        tcgplayer_url=external.get("tcgPlayerUrl"),
        image_url=image_url,
    )


def map_lorcana_json_payload(payload: dict[str, Any]) -> list[CardRecord]:
    """Map the full allCards.json payload, dropping unknown-set cards.

    Cards from unmapped sets are logged at WARNING and skipped — one bad
    set entry must not abort the whole sync.
    """
    records: list[CardRecord] = []
    for raw in payload.get("cards", []):
        try:
            records.append(map_lorcana_json_card(raw))
        except KeyError as exc:
            log.warning(
                "Skipping card from unmapped set %s (id=%s): %s",
                raw.get("setCode"),
                raw.get("id"),
                exc,
            )
    return records
